import { Header } from "@/components/layout/header";
import { ItemsGrid } from "@/components/items/ItemsGrid";

export default function ItemsPage() {
  return (
    <div className="min-h-screen bg-background">
      <Header activePath="/items" />
      <main className="mx-auto max-w-6xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Inventory</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            All identified items across your homes
          </p>
        </div>
        <ItemsGrid />
      </main>
    </div>
  );
}
