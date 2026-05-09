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

  const { searchParams } = new URL(req.url);
  const query = searchParams.get("q") ?? "";
  const showArchived = searchParams.get("archived") === "true";

  const supabase = makeSupabase();
  try {
    const { data, error } = await supabase
      .from("items")
      .select("*, scans(*)")
      .eq("user_id", userId)
      .order("created_at", { ascending: false });

    if (error) throw error;

    let items = (data ?? []).map((item) => {
      const scan = Array.isArray(item.scans) ? item.scans[0] : item.scans;

      // Parse maintenance_note JSON as fallback (matches Flask schema)
      let meta: Record<string, unknown> = {};
      const note = item.maintenance_note;
      if (typeof note === "string" && note.startsWith("{")) {
        try { meta = JSON.parse(note); } catch { /* ignore */ }
      }

      return {
        ...item,
        home_name: item.home_name ?? scan?.home_name ?? meta.home ?? "My Home",
        room_name: item.room_name ?? scan?.room_name ?? meta.room ?? "General Room",
        original_image_url: item.original_image_url ?? scan?.original_image_url ?? null,
      };
    });

    items = items.filter((item) => Boolean(item.is_archived) === showArchived);

    if (query) {
      const terms = query.toLowerCase().split(" ");
      items = items.filter((item) => {
        const haystack = [item.name, item.category, item.home_name, item.room_name]
          .filter(Boolean).join(" ").toLowerCase();
        return terms.every((t) => haystack.includes(t));
      });
    }

    return NextResponse.json({ success: true, data: items });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
