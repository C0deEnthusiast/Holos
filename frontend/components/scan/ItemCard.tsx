"use client";

import Image from "next/image";
import { Save, CheckCircle } from "lucide-react";
import type { ScannedItem } from "@/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatCurrency, conditionColor } from "@/lib/utils";

interface ItemCardProps {
  item: ScannedItem;
  onSave?: (item: ScannedItem) => void;
  isSaving?: boolean;
}

export function ItemCard({ item, onSave, isSaving }: ItemCardProps) {
  const saved = item.auto_saved;

  return (
    <Card className="overflow-hidden">
      {item.thumbnail_url && (
        <div className="relative h-40 w-full bg-muted">
          <Image
            src={item.thumbnail_url}
            alt={item.name}
            fill
            className="object-cover"
            unoptimized
          />
        </div>
      )}
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-medium text-sm">{item.name}</p>
            {item.make && (
              <p className="text-xs text-muted-foreground truncate">
                {item.make}{item.model ? ` · ${item.model}` : ""}
              </p>
            )}
          </div>
          <Badge variant="outline" className="shrink-0 text-xs">
            {item.confidence_score}%
          </Badge>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${conditionColor(item.condition)}`}>
            {item.condition}
          </span>
          {item.category && (
            <Badge variant="secondary" className="text-xs">{item.category}</Badge>
          )}
        </div>

        <div className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Resale</span>
            <span className="font-medium">{item.resale_value_usd ?? formatCurrency(item.estimated_price_usd)}</span>
          </div>
          {item.retail_replacement_usd && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Retail</span>
              <span>{item.retail_replacement_usd}</span>
            </div>
          )}
          {item.insurance_replacement_usd && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Insurance</span>
              <span>{item.insurance_replacement_usd}</span>
            </div>
          )}
        </div>

        {onSave && (
          <Button
            size="sm"
            variant={saved ? "secondary" : "default"}
            className="w-full gap-1.5"
            onClick={() => !saved && onSave(item)}
            disabled={saved || isSaving}
          >
            {saved ? (
              <><CheckCircle className="h-3.5 w-3.5" /> Saved</>
            ) : (
              <><Save className="h-3.5 w-3.5" /> {isSaving ? "Saving…" : "Save item"}</>
            )}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
