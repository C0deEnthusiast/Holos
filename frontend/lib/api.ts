import { getAccessToken } from "./supabase";
import type { ScanResponse, SavedItem, EstateReport } from "@/types";

// For scan endpoints we call FastAPI directly to avoid the Next.js dev-proxy
// 30 s timeout. NEXT_PUBLIC_API_V2_URL defaults to the local FastAPI port.
const API_V2 = process.env.NEXT_PUBLIC_API_V2_URL ?? "http://localhost:8001";

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── Scan ──────────────────────────────────────────────────────────────────────

export async function scanImage(
  file: File,
  opts: { homeName?: string; roomName?: string; userNotes?: string } = {}
): Promise<ScanResponse> {
  const form = new FormData();
  form.append("image", file);
  form.append("home_name", opts.homeName ?? "My Home");
  form.append("room_name", opts.roomName ?? "General Room");
  if (opts.userNotes) form.append("user_notes", opts.userNotes);

  const res = await fetch(`${API_V2}/api/v2/scan`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Scan failed");
  }
  return res.json();
}

export async function scanVideo(
  file: File,
  opts: {
    homeName?: string;
    roomName?: string;
    userNotes?: string;
    sampleFps?: number;
    maxFrames?: number;
  } = {}
): Promise<ScanResponse> {
  const form = new FormData();
  form.append("video", file);
  form.append("home_name", opts.homeName ?? "My Home");
  form.append("room_name", opts.roomName ?? "General Room");
  if (opts.userNotes) form.append("user_notes", opts.userNotes);
  if (opts.sampleFps) form.append("sample_fps", String(opts.sampleFps));
  if (opts.maxFrames) form.append("max_frames", String(opts.maxFrames));

  const res = await fetch(`${API_V2}/api/v2/scan/video`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Video scan failed");
  }
  return res.json();
}

// ── Items ─────────────────────────────────────────────────────────────────────

export async function getItems(opts: { query?: string; archived?: boolean } = {}): Promise<SavedItem[]> {
  const params = new URLSearchParams();
  if (opts.query) params.set("q", opts.query);
  if (opts.archived) params.set("archived", "true");

  const res = await fetch(`/api/items?${params}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch items");
  const body = await res.json();
  return body.data ?? [];
}

export async function saveItem(item: Partial<SavedItem>): Promise<SavedItem> {
  const res = await fetch("/api/items/save", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(item),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error ?? "Failed to save item");
  }
  const body = await res.json();
  return body.data;
}

export async function archiveItem(id: string): Promise<void> {
  await fetch(`/api/items/${id}/archive`, {
    method: "POST",
    headers: await authHeaders(),
  });
}

export async function unarchiveItem(id: string): Promise<void> {
  await fetch(`/api/items/${id}/unarchive`, {
    method: "POST",
    headers: await authHeaders(),
  });
}

// ── Reports ───────────────────────────────────────────────────────────────────

export async function getEstateReport(): Promise<EstateReport> {
  const res = await fetch("/api/reports/estate", {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch estate report");
  return res.json();
}
