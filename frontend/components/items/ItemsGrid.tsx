"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Search, Archive, ArchiveRestore, Package } from "lucide-react";
import { getItems, archiveItem, unarchiveItem } from "@/lib/api";
import type { SavedItem } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, conditionColor } from "@/lib/utils";

export function ItemsGrid() {
  const [items, setItems]         = useState<SavedItem[]>([]);
  const [query, setQuery]         = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading]     = useState(true);
  const [archivingId, setArchivingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const data = await getItems({ query: query || undefined, archived: showArchived });
      setItems(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [showArchived]);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    await load();
  }

  async function toggleArchive(item: SavedItem) {
    setArchivingId(item.id);
    try {
      if (item.is_archived) {
        await unarchiveItem(item.id);
      } else {
        await archiveItem(item.id);
      }
      await load();
    } finally {
      setArchivingId(null);
    }
  }

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <form onSubmit={handleSearch} className="flex flex-1 gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search items, rooms, categories…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-8"
            />
          </div>
          <Button type="submit" variant="secondary">Search</Button>
        </form>
        <Button
          variant={showArchived ? "default" : "outline"}
          size="sm"
          onClick={() => setShowArchived(!showArchived)}
          className="gap-1.5 shrink-0"
        >
          <Archive className="h-3.5 w-3.5" />
          {showArchived ? "Showing archived" : "Show archived"}
        </Button>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} className="overflow-hidden">
              <Skeleton className="h-36 w-full rounded-none" />
              <CardContent className="p-4 space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-3 w-1/3" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-16 text-center">
          <Package className="h-10 w-10 text-muted-foreground/40" />
          <div>
            <p className="text-sm font-medium">No items found</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {query ? "Try a different search term" : "Scan a room to start your inventory"}
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map((item) => (
            <Card key={item.id} className="overflow-hidden group">
              <div className="relative h-36 w-full bg-muted">
                {item.thumbnail_url ? (
                  <Image
                    src={item.thumbnail_url}
                    alt={item.name}
                    fill
                    className="object-cover"
                    unoptimized
                  />
                ) : (
                  <div className="flex h-full items-center justify-center">
                    <Package className="h-8 w-8 text-muted-foreground/30" />
                  </div>
                )}
              </div>
              <CardContent className="p-4 space-y-3">
                <div>
                  <p className="truncate font-medium text-sm">{item.name}</p>
                  <p className="text-xs text-muted-foreground truncate">
                    {[item.home_name, item.room_name].filter(Boolean).join(" · ") || "Uncategorized"}
                  </p>
                </div>

                <div className="flex flex-wrap gap-1">
                  {item.condition && (
                    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${conditionColor(item.condition)}`}>
                      {item.condition}
                    </span>
                  )}
                  {item.category && (
                    <Badge variant="secondary" className="text-xs">{item.category}</Badge>
                  )}
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold">{formatCurrency(item.estimated_price_usd)}</p>
                    {item.resale_value_usd && (
                      <p className="text-xs text-muted-foreground">Resale: {item.resale_value_usd}</p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => toggleArchive(item)}
                    disabled={archivingId === item.id}
                    title={item.is_archived ? "Unarchive" : "Archive"}
                  >
                    {item.is_archived
                      ? <ArchiveRestore className="h-3.5 w-3.5" />
                      : <Archive className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
