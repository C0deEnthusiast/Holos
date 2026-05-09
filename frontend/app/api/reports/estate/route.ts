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
  const supabase = makeSupabase();
  try {
    const { data } = await supabase.auth.getUser(token);
    return data.user?.id ?? null;
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest) {
  const userId = await getUserId(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const supabase = makeSupabase();
  try {
    const { data, error } = await supabase
      .from("items")
      .select("*, scans(*)")
      .eq("user_id", userId)
      .eq("is_archived", false);

    if (error) throw error;

    const properties: Record<string, Record<string, { items: unknown[]; subtotal: number; total_insurance_value: number }>> = {};
    let totalValue = 0;
    let totalItems = 0;

    for (const item of data ?? []) {
      const scan = Array.isArray(item.scans) ? item.scans[0] : item.scans;
      const home = scan?.home_name ?? item.home_name ?? "My Property";
      const room = scan?.room_name ?? item.room_name ?? "General Areas";

      if (!properties[home]) properties[home] = {};
      if (!properties[home][room]) properties[home][room] = { items: [], subtotal: 0, total_insurance_value: 0 };

      const price = parseFloat(item.estimated_price_usd ?? 0);
      properties[home][room].items.push({
        name: item.name,
        category: item.category,
        make: item.make,
        model: item.model,
        price,
        condition: item.condition,
        thumbnail: item.thumbnail_url,
      });
      properties[home][room].subtotal += price;
      properties[home][room].total_insurance_value += price * 1.15;
      totalValue += price;
      totalItems += 1;
    }

    return NextResponse.json({
      success: true,
      report_date: new Date().toISOString().slice(0, 10),
      owner_id: userId,
      total_market_value: Math.round(totalValue * 100) / 100,
      total_items: totalItems,
      properties,
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
