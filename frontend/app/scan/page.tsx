import { Header } from "@/components/layout/header";
import { ScanUpload } from "@/components/scan/ScanUpload";

export default function ScanPage() {
  return (
    <div className="min-h-screen bg-background">
      <Header activePath="/scan" />
      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Scan a room</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Upload a photo or walkthrough video — Holos identifies and values every item
          </p>
        </div>
        <ScanUpload />
      </main>
    </div>
  );
}
