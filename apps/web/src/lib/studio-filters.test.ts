import { describe, expect, it } from "vitest";
import type { DemandCard } from "./admin-api";
import {
  derivePlatforms,
  filterHref,
  filterQueue,
  syncedLabel,
  topDemandByPlatform,
} from "./studio-filters";

// minimal card factory — only the fields the filters read
function card(p: Partial<DemandCard>): DemandCard {
  return {
    id: p.id ?? "x",
    label: p.label ?? "topic",
    search_count: 0,
    comment_count: 0,
    wow_change: null,
    recommendation: null,
    confidence: null,
    state: p.state ?? "new",
    coverage: null,
    opportunity_score: null,
    source_breakdown: p.source_breakdown ?? null,
    reconciliation: p.reconciliation ?? null,
    ...p,
  } as DemandCard;
}

describe("derivePlatforms", () => {
  it("unions platform keys, drops search/unknown, sorts", () => {
    const cards = [
      card({ source_breakdown: { instagram: 3, search: 5 } }),
      card({ source_breakdown: { youtube: 2, unknown: 1 } }),
      card({ source_breakdown: { instagram: 1 } }),
    ];
    expect(derivePlatforms(cards)).toEqual(["instagram", "youtube"]);
  });

  it("returns [] when no platform demand", () => {
    expect(derivePlatforms([card({ source_breakdown: { search: 9 } })])).toEqual([]);
  });
});

describe("filterQueue", () => {
  const cards = [
    card({ id: "open-ig-gap", state: "new", source_breakdown: { instagram: 3 },
      reconciliation: { label: "gap", strength: 0.1, covered_permalink: null } }),
    card({ id: "open-yt-ans", state: "idea", source_breakdown: { youtube: 2 },
      reconciliation: { label: "well", strength: 0.8, covered_permalink: "u" } }),
    card({ id: "closed", state: "loop_closed", source_breakdown: { instagram: 9 } }),
    card({ id: "dismissed", state: "dismissed", source_breakdown: { instagram: 9 } }),
  ];

  it("excludes resolved (loop_closed / dismissed) states", () => {
    const ids = filterQueue(cards, {}).map((c) => c.id);
    expect(ids).toEqual(["open-ig-gap", "open-yt-ans"]);
  });

  it("filters by platform (AND)", () => {
    expect(filterQueue(cards, { platform: "youtube" }).map((c) => c.id)).toEqual(["open-yt-ans"]);
  });

  it("view=gap keeps only gaps; view=answered keeps well+partial", () => {
    expect(filterQueue(cards, { view: "gap" }).map((c) => c.id)).toEqual(["open-ig-gap"]);
    expect(filterQueue(cards, { view: "answered" }).map((c) => c.id)).toEqual(["open-yt-ans"]);
  });

  it("composes platform and view", () => {
    expect(filterQueue(cards, { platform: "instagram", view: "answered" })).toEqual([]);
    expect(filterQueue(cards, { platform: "instagram", view: "gap" }).map((c) => c.id)).toEqual([
      "open-ig-gap",
    ]);
  });
});

describe("filterHref", () => {
  it("encodes whichever filters are set, empty when none", () => {
    expect(filterHref(null, null)).toBe("");
    expect(filterHref("tiktok", null)).toBe("?platform=tiktok");
    expect(filterHref(null, "gap")).toBe("?view=gap");
    expect(filterHref("tiktok", "gap")).toBe("?platform=tiktok&view=gap");
  });
});

describe("topDemandByPlatform", () => {
  it("groups by platform, sorts desc, caps at N, ignores search/unknown/zero", () => {
    const cards = [
      card({ label: "a", source_breakdown: { instagram: 5, search: 99 } }),
      card({ label: "b", source_breakdown: { instagram: 9 } }),
      card({ label: "c", source_breakdown: { instagram: 1, youtube: 4 } }),
      card({ label: "z", source_breakdown: { instagram: 0 } }),
    ];
    const out = topDemandByPlatform(cards, 2);
    expect(out.instagram).toEqual([
      { label: "b", n: 9 },
      { label: "a", n: 5 },
    ]);
    expect(out.youtube).toEqual([{ label: "c", n: 4 }]);
    expect(out.search).toBeUndefined();
  });
});

describe("syncedLabel", () => {
  const now = new Date("2026-06-25T12:00:00Z").getTime();
  const ago = (mins: number) => new Date(now - mins * 60_000).toISOString();

  it("handles unset / never / relative buckets", () => {
    expect(syncedLabel(undefined, now)).toBe("");
    expect(syncedLabel(null, now)).toBe("never synced");
    expect(syncedLabel(ago(0.5), now)).toBe("synced just now");
    expect(syncedLabel(ago(20), now)).toBe("synced 20m ago");
    expect(syncedLabel(ago(180), now)).toBe("synced 3h ago");
    expect(syncedLabel(ago(60 * 24 * 2), now)).toBe("synced 2d ago");
  });
});
