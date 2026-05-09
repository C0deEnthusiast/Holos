import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";

function makeSupabase() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );
}

async function getUserId(req: NextRequest): Promise<string | null> {
  const auth = req.headers.get("authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return null;
  const token = auth.slice(7).trim();
  try {
    const { data } = await makeSupabase().auth.getUser(token);
    return data.user?.id ?? null;
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  const userId = await getUserId(req);
  if (!userId) {
    return NextResponse.json({ error: "Unauthorized — no valid session token" }, { status: 401 });
  }

  const data = await req.json();
  const supabase = makeSupabase();

  const priceStr = String(data.estimated_price_usd ?? "0").replace(/[$,]/g, "");
  const price = parseFloat(priceStr.match(/[-+]?\d*\.?\d+/)?.[0] ?? "0") || 0;

  // ── Step 1: create scan record (best-effort) ──────────────────────────────
  let scanId: string | undefined;
  const { data: scanData, error: scanErr } = await supabase
    .from("scans")
    .insert({
      user_id: userId,
      status: "item_link",
      original_image_url: data.original_image_url ?? null,
      home_name: data.home_name ?? "My Home",
      room_name: data.room_name ?? "General Room",
    })
    .select("id")
    .single();

  if (scanErr) {
    console.error("[items/save] scan insert error:", JSON.stringify(scanErr));
  } else {
    scanId = scanData?.id;
  }

  // ── Step 2: build item payload ─────────────────────────────────────────────
  const maintenanceNote = JSON.stringify({
    home: data.home_name ?? "My Home",
    room: data.room_name ?? "General Room",
    make: data.make ?? null,
    model: data.model ?? null,
    quantity: data.quantity ?? 1,
    is_set: data.is_set ?? false,
    estimated_age_years: data.estimated_age_years ?? null,
    condition_notes: data.condition_notes ?? null,
    estimated_dimensions: data.estimated_dimensions ?? null,
    bounding_box: data.bounding_box ?? null,
    confidence_score: data.confidence_score ?? null,
    unit_price_usd: data.unit_price_usd ?? null,
    resale_value_usd: data.resale_value_usd ?? null,
    retail_replacement_usd: data.retail_replacement_usd ?? null,
    insurance_replacement_usd: data.insurance_replacement_usd ?? null,
    price_basis: data.price_basis ?? null,
    identification_basis: data.identification_basis ?? null,
  });

  const fullPayload: Record<string, unknown> = {
    user_id: userId,
    name: data.name,
    category: data.category ?? null,
    condition: data.condition ?? null,
    estimated_price_usd: price,
    thumbnail_url: data.thumbnail_url ?? null,
    is_archived: false,
    maintenance_note: maintenanceNote,
    ...(scanId ? { scan_id: scanId } : {}),
  };

  // ── Step 3: try full insert, then minimal fallback ─────────────────────────
  const { data: saved, error: insertErr } = await supabase
    .from("items")
    .insert(fullPayload)
    .select()
    .single();

  if (!insertErr) {
    return NextResponse.json({ success: true, data: saved });
  }

  console.error("[items/save] full insert error:", JSON.stringify(insertErr));

  // If the error is about an unknown column, retry with only guaranteed columns
  const errMsg = insertErr.message ?? "";
  const isColumnError =
    errMsg.includes("schema cache") ||
    errMsg.includes("Could not find") ||
    errMsg.includes("column") ||
    insertErr.code === "PGRST204";

  if (isColumnError) {
    const minimalPayload: Record<string, unknown> = {
      user_id: userId,
      name: data.name,
      category: data.category ?? null,
      condition: data.condition ?? null,
      estimated_price_usd: price,
      thumbnail_url: data.thumbnail_url ?? null,
      is_archived: false,
      ...(scanId ? { scan_id: scanId } : {}),
    };

    const { data: fallbackSaved, error: fallbackErr } = await supabase
      .from("items")
      .insert(minimalPayload)
      .select()
      .single();

    if (fallbackErr) {
      console.error("[items/save] minimal insert error:", JSON.stringify(fallbackErr));
      return NextResponse.json(
        { error: `Save failed: ${fallbackErr.message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({ success: true, data: fallbackSaved });
  }

  return NextResponse.json({ error: `Save failed: ${errMsg}` }, { status: 500 });
}
