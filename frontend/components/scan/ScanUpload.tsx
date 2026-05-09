"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { Upload, Video, X, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { scanImage, scanVideo, saveItem } from "@/lib/api";
import type { ScannedItem, ScanResponse } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard } from "./ItemCard";

type ScanMode = "image" | "video";

export function ScanUpload() {
  const [mode, setMode]           = useState<ScanMode>("image");
  const [file, setFile]           = useState<File | null>(null);
  const [preview, setPreview]     = useState<string | null>(null);
  const [homeName, setHomeName]   = useState("My Home");
  const [roomName, setRoomName]   = useState("Living Room");
  const [userNotes, setUserNotes] = useState("");
  const [dragging, setDragging]   = useState(false);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [result, setResult]       = useState<ScanResponse | null>(null);
  const [savingId, setSavingId]   = useState<string | null>(null);
  const [toast, setToast]         = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.type === "error" ? 6000 : 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
  const VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/avi", "video/webm", "video/x-matroska"];

  const accept = mode === "image" ? IMAGE_TYPES.join(",") : VIDEO_TYPES.join(",");

  function handleFile(f: File) {
    setFile(f);
    setResult(null);
    setError(null);
    if (mode === "image") {
      const url = URL.createObjectURL(f);
      setPreview(url);
    } else {
      setPreview(null);
    }
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [mode]);

  async function handleScan() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = mode === "image"
        ? await scanImage(file, { homeName, roomName, userNotes })
        : await scanVideo(file, { homeName, roomName, userNotes });
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveItem(item: ScannedItem) {
    const key = item.name + (item.category ?? "");
    setSavingId(key);
    try {
      await saveItem({ ...item, home_name: homeName, room_name: roomName });
      setResult((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          data: prev.data.map((i) =>
            i.name === item.name ? { ...i, auto_saved: true } : i
          ),
        };
      });
      setToast({ type: "success", msg: `"${item.name}" saved to inventory` });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setToast({ type: "error", msg });
    } finally {
      setSavingId(null);
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="space-y-6">
      {/* Mode toggle */}
      <div className="flex gap-2">
        {(["image", "video"] as ScanMode[]).map((m) => (
          <Button
            key={m}
            variant={mode === m ? "default" : "outline"}
            size="sm"
            onClick={() => { setMode(m); reset(); }}
            className="gap-1.5"
          >
            {m === "image" ? <Upload className="h-3.5 w-3.5" /> : <Video className="h-3.5 w-3.5" />}
            {m === "image" ? "Photo" : "Video"}
          </Button>
        ))}
      </div>

      {/* Metadata fields */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Home</label>
          <Input value={homeName} onChange={(e) => setHomeName(e.target.value)} placeholder="My Home" />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Room</label>
          <Input value={roomName} onChange={(e) => setRoomName(e.target.value)} placeholder="Living Room" />
        </div>
        <div className="space-y-1.5 col-span-2 sm:col-span-1">
          <label className="text-xs font-medium text-muted-foreground">Notes (optional)</label>
          <Input value={userNotes} onChange={(e) => setUserNotes(e.target.value)} placeholder="e.g. mid-century modern" />
        </div>
      </div>

      {/* Drop zone */}
      {!file ? (
        <div
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 transition-colors ${
            dragging ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-accent/50"
          }`}
        >
          {mode === "image"
            ? <Upload className="h-8 w-8 text-muted-foreground" />
            : <Video className="h-8 w-8 text-muted-foreground" />}
          <div className="text-center">
            <p className="text-sm font-medium">
              Drop {mode === "image" ? "a room photo" : "a walkthrough video"} here
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {mode === "image" ? "JPG, PNG or WebP" : "MP4, MOV, WebM up to 200 MB"}
            </p>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </div>
      ) : (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted-foreground">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
            </div>
            <Button variant="ghost" size="icon" onClick={reset}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          {preview && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="Preview" className="rounded-md w-full object-contain max-h-[480px]" />
          )}
          <Button onClick={handleScan} disabled={loading} className="w-full gap-2">
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {loading ? "Analyzing…" : "Analyze with AI"}
          </Button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-lg px-4 py-3 text-sm font-medium shadow-lg transition-all ${
          toast.type === "success"
            ? "bg-green-600 text-white"
            : "bg-destructive text-destructive-foreground"
        }`}>
          {toast.type === "success" && <CheckCircle2 className="h-4 w-4 shrink-0" />}
          {toast.msg}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">
              {result.summary.total} item{result.summary.total !== 1 ? "s" : ""} found
            </h2>
            {result.pipeline && (
              <p className="text-xs text-muted-foreground">
                {result.pipeline.frames_processed} frames · {result.pipeline.processing_time_sec}s
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {result.data.map((item, i) => (
              <ItemCard
                key={i}
                item={item}
                onSave={handleSaveItem}
                isSaving={savingId === item.name + (item.category ?? "")}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
