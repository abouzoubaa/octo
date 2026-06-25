import { component$ } from "@builder.io/qwik";
import {
  routeLoader$,
  routeAction$,
  Form,
  Link,
  type DocumentHead,
} from "@builder.io/qwik-city";
import { adminGet, adminPost, type DemandCard } from "~/lib/admin-api";

interface Briefing {
  week: string;
  creator: string;
  top_demand: {
    topic_id: string;
    label: string;
    signal: { searches: number; comments: number; wow_change: number | null };
    hook: string | null;
    state: string;
  }[];
  open_gaps: { label: string; demand: number }[];
  repromote: { label: string; permalink: string | null; why: string } | null;
  drafted_post: { draft_id: string; title: string; hooks: string[] | null } | null;
}

export const useOverview = routeLoader$(async ({ params, query }) => {
  const cid = params.creatorId;
  const [creators, radar, briefing, metrics, northStar] = await Promise.all([
    adminGet<{ id: string; handle: string }[]>("/admin/creators"),
    adminGet<DemandCard[]>(`/admin/creators/${cid}/radar`),
    adminGet<Briefing>(`/agent/creators/${cid}/briefing?with_draft=false`),
    adminGet<Record<string, unknown>>(`/admin/creators/${cid}/metrics`),
    adminGet<import("~/lib/admin-api").NorthStar>(`/agent/creators/${cid}/north-star`),
  ]);
  const creator = (creators ?? []).find((c) => c.id === cid);
  const allCards = radar ?? [];
  // platform chips: every platform that contributed demand to any card (not search)
  const platforms = [
    ...new Set(
      allCards.flatMap((c) =>
        Object.keys(c.source_breakdown ?? {}).filter((k) => k !== "search" && k !== "unknown"),
      ),
    ),
  ].sort();
  const platform = query.get("platform");
  const cards =
    platform && platforms.includes(platform)
      ? allCards.filter((c) => (c.source_breakdown?.[platform] ?? 0) > 0)
      : allCards;
  return {
    cid,
    handle: creator?.handle ?? cid,
    radar: cards,
    platforms,
    platform: platform && platforms.includes(platform) ? platform : null,
    briefing,
    metrics,
    northStar,
  };
});

// Move a demand card through its lifecycle (idea → drafting → published → …)
export const useTransition = routeAction$(async (data) => {
  const res = await adminPost(`/agent/demand/${data.topicId}/transition`, { to: data.to });
  return { ok: res !== null };
});

// Generate a grounded draft from a demand card
export const useDraft = routeAction$(async (data) => {
  const res = await adminPost<{ draft_id: string }>(`/agent/demand/${data.topicId}/draft`);
  return { ok: res !== null, draftId: res?.draft_id };
});

// Close a loop by re-promoting already-made content (logs an Outcome)
export const useRepromote = routeAction$(async (data) => {
  const res = await adminPost<{ closed: boolean; state: string }>(
    `/agent/demand/${data.topicId}/repromote`,
  );
  return { ok: res !== null, closed: res?.closed ?? false, topicId: data.topicId as string };
});

// Propose a multi-part series arc for a recurring-demand topic
export const useSeries = routeAction$(async (data) => {
  const res = await adminPost<{
    topic_id: string;
    parts: string[];
    faq_post: string;
    dm_followup: string;
    offer_tie_in: string;
    draft_ids: string[];
  }>(`/agent/demand/${data.topicId}/series`);
  return res ?? null;
});

// demand↔supply reconciliation: have they already answered this, or is it a gap?
const RECONCILE: Record<string, { icon: string; text: string }> = {
  well: { icon: "✓", text: "You've already answered this" },
  partial: { icon: "◑", text: "Partly covered — go deeper or re-promote" },
  gap: { icon: "🎯", text: "Genuine gap — you haven't covered this" },
};

const PLATFORM_ICON: Record<string, string> = {
  instagram: "📸",
  youtube: "▶️",
  tiktok: "🎵",
  newsletter: "✉️",
  podcast: "🎙️",
  discord: "💬",
};

// the next lifecycle step + the action verb a creator actually thinks in
const NEXT_STATE: Record<string, { to: string; verb: string } | null> = {
  new: { to: "idea", verb: "✓ Make this" },
  idea: { to: "drafting", verb: "✍️ Draft it" },
  drafting: { to: "published", verb: "📤 Mark published" },
  published: { to: "loop_closed", verb: "🔁 Close the loop" },
  loop_closed: null,
  dismissed: { to: "idea", verb: "↩ Revisit" },
};

export default component$(() => {
  const o = useOverview();
  const transition = useTransition();
  const draft = useDraft();
  const series = useSeries();
  const repromote = useRepromote();
  const m = (o.value.metrics ?? {}) as any;

  return (
    <>
      <header class="topbar">
        <div class="identity">
          <div class="avatar">{o.value.handle.charAt(0).toUpperCase()}</div>
          <div>
            <h1>@{o.value.handle}</h1>
            <p>Sift Studio</p>
          </div>
        </div>
        <Link class="theme-toggle glass" href="/studio" aria-label="Back">
          ←
        </Link>
      </header>

      <nav class="studio-nav">
        <Link href={`/studio/${o.value.cid}/inbox`} class="studio-nav-item glass">
          📨 Inbox
        </Link>
        <Link href={`/studio/${o.value.cid}/drafts`} class="studio-nav-item glass">
          ✍️ Drafts
        </Link>
        <Link href={`/studio/${o.value.cid}/platforms`} class="studio-nav-item glass">
          🔌 Platforms
        </Link>
      </nav>

      <section class="stat-row">
        <div class="stat glass">
          <span class="stat-n">{o.value.northStar?.closed_loops_per_week ?? 0}</span>
          <span class="stat-l">loops closed/wk</span>
        </div>
        <div class="stat glass">
          <span class="stat-n">{o.value.northStar?.in_flight_loops ?? 0}</span>
          <span class="stat-l">in flight</span>
        </div>
        <div class="stat glass">
          <span class="stat-n">{(m?.audience as any)?.searches ?? 0}</span>
          <span class="stat-l">searches</span>
        </div>
      </section>

      {o.value.briefing && (
        <section class="answer-card glass">
          <div class="label">
            <span class="dot" />
            This week's briefing
          </div>
          {o.value.briefing.open_gaps.length > 0 && (
            <p class="answer-text">
              Top open gap: <strong>{o.value.briefing.open_gaps[0].label}</strong> (
              {o.value.briefing.open_gaps[0].demand} asking)
            </p>
          )}
          {o.value.briefing.repromote && (
            <p class="evidence">♻️ Re-promote: {o.value.briefing.repromote.label}</p>
          )}
        </section>
      )}

      <p class="results-label">Opportunity queue</p>
      {o.value.platforms.length > 1 && (
        <div class="actions" style="margin-bottom:10px;">
          <Link href={`/studio/${o.value.cid}`} class={`pill-btn ${o.value.platform ? "ghost" : ""}`}>
            All
          </Link>
          {o.value.platforms.map((p) => (
            <Link
              key={p}
              href={`?platform=${p}`}
              class={`pill-btn ${o.value.platform === p ? "" : "ghost"}`}
            >
              {PLATFORM_ICON[p] ?? "🔌"} {p}
            </Link>
          ))}
        </div>
      )}
      {o.value.radar.length === 0 && (
        <div class="empty-state glass">
          {o.value.platform
            ? `No ${o.value.platform} demand this cycle.`
            : "No opportunities yet — run Radar to populate."}
        </div>
      )}
      {o.value.radar.map((c) => (
        <div class="result glass" key={c.id}>
          <div class="meta">
            {c.opportunity_score != null && (
              <span class="score">{Math.round(c.opportunity_score)}</span>
            )}
            <span class="type">{c.state}</span>
            <span class="date">
              {c.integrity?.unique_askers ?? c.search_count + c.comment_count} asking
              {c.coverage?.gap ? " · gap" : ""}
              {c.integrity?.manipulation_risk && c.integrity.manipulation_risk > 0.5
                ? " · ⚠ inflatable"
                : ""}
            </span>
            {c.source_breakdown && (
              <span class="date">
                {Object.keys(c.source_breakdown)
                  .filter((k) => k !== "search" && k !== "unknown")
                  .map((k) => PLATFORM_ICON[k] ?? "🔌")
                  .join(" ")}
                {c.demand_segment === "everywhere" ? " · everywhere" : ""}
              </span>
            )}
          </div>
          <p class="caption">{c.label}</p>
          {c.reconciliation && (
            <p class="evidence">
              {RECONCILE[c.reconciliation.label].icon} {RECONCILE[c.reconciliation.label].text}
              {c.reconciliation.covered_permalink && (
                <>
                  {" — "}
                  <a href={c.reconciliation.covered_permalink} target="_blank" rel="noreferrer">
                    open it →
                  </a>
                  {repromote.value?.ok &&
                  repromote.value.topicId === c.id &&
                  repromote.value.closed ? (
                    <span class="open" style="margin-left:8px;">
                      ✓ loop closed
                    </span>
                  ) : (
                    <Form action={repromote} style="display:inline; margin-left:8px;">
                      <input type="hidden" name="topicId" value={c.id} />
                      <button class="pill-btn ghost" type="submit">
                        ♻️ Close via re-promote
                      </button>
                    </Form>
                  )}
                </>
              )}
            </p>
          )}
          {c.recommendation && <p class="evidence">{c.recommendation}</p>}
          <div class="actions">
            {NEXT_STATE[c.state] && (
              <Form action={transition}>
                <input type="hidden" name="topicId" value={c.id} />
                <input type="hidden" name="to" value={NEXT_STATE[c.state]!.to} />
                <button class="pill-btn" type="submit">
                  {NEXT_STATE[c.state]!.verb}
                </button>
              </Form>
            )}
            <Form action={draft}>
              <input type="hidden" name="topicId" value={c.id} />
              <button class="pill-btn ghost" type="submit">
                ✍️ Draft
              </button>
            </Form>
            <Form action={series}>
              <input type="hidden" name="topicId" value={c.id} />
              <button class="pill-btn ghost" type="submit">
                🎬 Series
              </button>
            </Form>
            {c.state !== "dismissed" && (
              <Form action={transition}>
                <input type="hidden" name="topicId" value={c.id} />
                <input type="hidden" name="to" value="dismissed" />
                <button class="pill-btn ghost" type="submit">
                  Ignore — weak
                </button>
              </Form>
            )}
          </div>
          {series.value?.topic_id === c.id && (
            <div class="series-arc">
              <div class="label">
                <span class="dot" />
                Series arc
              </div>
              <ol class="series-parts">
                {series.value.parts.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ol>
              {series.value.faq_post && (
                <p class="evidence">❓ FAQ post: {series.value.faq_post}</p>
              )}
              {series.value.dm_followup && (
                <p class="evidence">📨 DM follow-up: {series.value.dm_followup}</p>
              )}
              {series.value.offer_tie_in && (
                <p class="evidence">🎯 Offer tie-in: {series.value.offer_tie_in}</p>
              )}
              {series.value.draft_ids && series.value.draft_ids.length > 0 && (
                <Link
                  class="pill-btn ghost"
                  href={`/studio/${o.value.cid}/drafts#draft-${series.value.draft_ids[0]}`}
                >
                  💾 Saved to Drafts → open
                </Link>
              )}
            </div>
          )}
        </div>
      ))}
    </>
  );
});

export const head: DocumentHead = ({ resolveValue }) => {
  const o = resolveValue(useOverview);
  return { title: `@${o.handle} — Sift Studio` };
};
