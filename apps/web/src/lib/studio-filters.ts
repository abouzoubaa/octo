// Pure helpers behind the Studio loaders — extracted so they can be unit-tested
// (Vitest) independently of Qwik's routeLoader wiring.
import type { DemandCard } from "./admin-api";

const RESOLVED = new Set(["loop_closed", "dismissed"]);

// every platform that contributed demand to any card (search/unknown are not platforms)
export function derivePlatforms(cards: DemandCard[]): string[] {
  return [
    ...new Set(
      cards.flatMap((c) =>
        Object.keys(c.source_breakdown ?? {}).filter((k) => k !== "search" && k !== "unknown"),
      ),
    ),
  ].sort();
}

// the opportunity queue: open topics only, optionally narrowed by platform and/or
// reconciliation view (gap vs answered). AND semantics.
export function filterQueue(
  cards: DemandCard[],
  opts: { platform?: string | null; view?: string | null },
): DemandCard[] {
  let out = cards.filter((c) => !RESOLVED.has(c.state));
  if (opts.platform) out = out.filter((c) => (c.source_breakdown?.[opts.platform!] ?? 0) > 0);
  if (opts.view === "gap") out = out.filter((c) => c.reconciliation?.label === "gap");
  else if (opts.view === "answered")
    out = out.filter((c) => c.reconciliation && c.reconciliation.label !== "gap");
  return out;
}

// build a query string preserving whichever radar filters are set, so the platform
// and gap/answered filters compose instead of clobbering each other.
export function filterHref(platform: string | null, view: string | null): string {
  const p = new URLSearchParams();
  if (platform) p.set("platform", platform);
  if (view) p.set("view", view);
  return p.toString() ? `?${p.toString()}` : "";
}

// per-platform top demand: the N highest-ask topics each platform contributed to.
export function topDemandByPlatform(
  cards: DemandCard[],
  top = 3,
): Record<string, { label: string; n: number }[]> {
  const by: Record<string, { label: string; n: number }[]> = {};
  for (const c of cards) {
    for (const [plat, n] of Object.entries(c.source_breakdown ?? {})) {
      if (plat === "search" || plat === "unknown" || n <= 0) continue;
      (by[plat] ??= []).push({ label: c.label, n });
    }
  }
  for (const plat of Object.keys(by)) by[plat] = by[plat].sort((a, b) => b.n - a.n).slice(0, top);
  return by;
}

// coarse "synced 3h ago" / "never synced" relative label (now injectable for tests).
export function syncedLabel(iso: string | null | undefined, now: number = Date.now()): string {
  if (iso === undefined) return "";
  if (iso === null) return "never synced";
  const secs = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (secs < 90) return "synced just now";
  const mins = secs / 60;
  if (mins < 90) return `synced ${Math.round(mins)}m ago`;
  const hrs = mins / 60;
  if (hrs < 36) return `synced ${Math.round(hrs)}h ago`;
  return `synced ${Math.round(hrs / 24)}d ago`;
}
