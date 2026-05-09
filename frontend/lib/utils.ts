import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number | undefined | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatCondition(condition: string | undefined): string {
  if (!condition) return "Unknown";
  return condition.charAt(0).toUpperCase() + condition.slice(1).toLowerCase();
}

export function conditionColor(condition: string | undefined): string {
  switch (condition?.toLowerCase()) {
    case "excellent": return "text-emerald-600 bg-emerald-50";
    case "good":      return "text-blue-600 bg-blue-50";
    case "fair":      return "text-amber-600 bg-amber-50";
    case "poor":      return "text-orange-600 bg-orange-50";
    case "damaged":   return "text-red-600 bg-red-50";
    default:          return "text-slate-600 bg-slate-50";
  }
}
