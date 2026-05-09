"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ScanLine, Package, DollarSign, TrendingUp, ArrowRight } from "lucide-react";
import { getItems, getEstateReport } from "@/lib/api";
import type { SavedItem, EstateReport } from "@/types";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency } from "@/lib/utils";

export default function DashboardPage() {
  const [items, setItems]           = useState<SavedItem[]>([]);
  const [report, setReport]         = useState<EstateReport | null>(null);
  const [loading, setLoading]       = useState(true);

  useEffect(() => {
    Promise.all([
      getItems().catch(() => [] as SavedItem[]),
      getEstateReport().catch(() => null),
    ]).then(([itemsData, reportData]) => {
      setItems(itemsData);
      setReport(reportData);
      setLoading(false);
    });
  }, []);

  const totalValue = report?.total_market_value ?? items.reduce((s, i) => s + (i.estimated_price_usd ?? 0), 0);
  const totalInsurance = report
    ? Object.values(report.properties).flatMap(Object.values).reduce(
        (sum, room) => sum + ((room as { total_insurance_value?: number }).total_insurance_value ?? 0),
        0
      )
    : 0;
  const recentItems = [...items].sort((a, b) =>
    new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()
  ).slice(0, 6);

  const stats = [
    { label: "Total items",     value: loading ? null : items.length,               icon: Package,    fmt: (v: number) => v.toString() },
    { label: "Inventory value", value: loading ? null : totalValue,                 icon: DollarSign, fmt: formatCurrency },
    { label: "Insurance value", value: loading ? null : totalInsurance, icon: TrendingUp, fmt: formatCurrency },
    { label: "Homes tracked",   value: loading ? null : Object.keys(report?.properties ?? {}).length, icon: Package, fmt: (v: number) => v.toString() },
  ];

  return (
    <div className="min-h-screen bg-background">
      <Header activePath="/dashboard" />
      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Dashboard</h1>
            <p className="text-sm text-muted-foreground mt-0.5">Your home inventory at a glance</p>
          </div>
          <Link href="/scan" className={buttonVariants({ className: "gap-1.5" })}>
            <ScanLine className="h-4 w-4" />
            Scan room
          </Link>
        </div>

        {/* Stats */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map(({ label, value, icon: Icon, fmt }) => (
            <Card key={label}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent>
                {loading || value == null
                  ? <Skeleton className="h-7 w-24" />
                  : <p className="text-2xl font-bold">{fmt(value)}</p>}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Quick scan CTA */}
        {!loading && items.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
              <div className="rounded-full bg-muted p-4">
                <ScanLine className="h-8 w-8 text-muted-foreground" />
              </div>
              <div>
                <p className="font-semibold">No items yet</p>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Take a photo of any room to start building your inventory
                </p>
              </div>
              <Link href="/scan" className={buttonVariants()}>
                Scan your first room
              </Link>
            </CardContent>
          </Card>
        )}

        {/* Recent items */}
        {recentItems.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Recent items</h2>
              <Link href="/items" className={buttonVariants({ variant: "ghost", size: "sm", className: "gap-1" })}>
                View all <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Item</th>
                    <th className="hidden px-4 py-2.5 text-left font-medium text-muted-foreground sm:table-cell">Room</th>
                    <th className="px-4 py-2.5 text-right font-medium text-muted-foreground">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {recentItems.map((item) => (
                    <tr key={item.id} className="hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3">
                        <p className="font-medium truncate max-w-[200px]">{item.name}</p>
                        {item.category && <p className="text-xs text-muted-foreground">{item.category}</p>}
                      </td>
                      <td className="hidden px-4 py-3 text-muted-foreground sm:table-cell">
                        {item.room_name ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-medium">
                        {formatCurrency(item.estimated_price_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
