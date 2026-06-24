import { component$ } from "@builder.io/qwik";
import { routeLoader$, routeAction$, Form, Link, type DocumentHead } from "@builder.io/qwik-city";
import {
  adminGet,
  adminPost,
  type CanonicalRow,
  type ConnectorRow,
  type ShiftOpportunity,
} from "~/lib/admin-api";

export const useCrossPlatform = routeLoader$(async ({ params }) => {
  const cid = params.creatorId;
  const [allPlatforms, connected, canonical, shift] = await Promise.all([
    adminGet<ConnectorRow[]>("/admin/platforms"),
    adminGet<ConnectorRow[]>(`/admin/creators/${cid}/connectors`),
    adminGet<CanonicalRow[]>(`/agent/creators/${cid}/canonical`),
    adminGet<ShiftOpportunity[]>(`/agent/creators/${cid}/sift-and-shift?target_platform=tiktok`),
  ]);
  return {
    cid,
    allPlatforms: allPlatforms ?? [],
    connected: new Set((connected ?? []).map((c) => c.platform)),
    canonical: canonical ?? [],
    shift: shift ?? [],
  };
});

// (Re)group repurposed posts into canonical answers.
export const useGroup = routeAction$(async (data) => {
  const res = await adminPost<{ canonical_objects: number }>(
    `/agent/creators/${data.cid}/canonical/group`,
  );
  return { ok: res !== null, n: res?.canonical_objects };
});

const ICON: Record<string, string> = {
  instagram: "📸",
  youtube: "▶️",
  tiktok: "🎵",
  newsletter: "✉️",
  podcast: "🎙️",
  discord: "💬",
};

export default component$(() => {
  const data = useCrossPlatform();
  const group = useGroup();

  return (
    <>
      <header class="topbar">
        <div class="identity">
          <Link class="theme-toggle glass" href={`/studio/${data.value.cid}`} aria-label="Back">
            ←
          </Link>
          <div>
            <h1>Platforms</h1>
            <p>Sift sits above every platform</p>
          </div>
        </div>
      </header>

      <p class="results-label">Connectors</p>
      {data.value.allPlatforms.map((p) => (
        <div class="result glass" key={p.platform}>
          <div class="meta">
            <span class="type">
              {ICON[p.platform] ?? "🔌"} {p.platform}
            </span>
            {data.value.connected.has(p.platform) ? (
              <span class="open">connected</span>
            ) : (
              <span class="date">available</span>
            )}
          </div>
          <p class="evidence">
            {p.capabilities.map((c) => c.replace(".", " ")).join(" · ")}
          </p>
        </div>
      ))}

      <p class="results-label" style="margin-top:18px;">
        Canonical answers
        <Form action={group} style="display:inline; margin-left:8px;">
          <input type="hidden" name="cid" value={data.value.cid} />
          <button class="pill-btn ghost" type="submit">
            ⟳ Group
          </button>
        </Form>
      </p>
      {data.value.canonical.length === 0 && (
        <div class="empty-state glass">
          No grouped answers yet — Group clusters repurposed posts into one idea.
        </div>
      )}
      {data.value.canonical.map((c) => (
        <div class="result glass" key={c.id}>
          <div class="meta">
            <span class="score">{c.variant_count}×</span>
            <span class="date">{c.platforms.map((p) => ICON[p] ?? p).join(" ")}</span>
          </div>
          <p class="caption">{c.title}</p>
        </div>
      ))}

      <p class="results-label" style="margin-top:18px;">
        Sift &amp; Shift → TikTok
      </p>
      {data.value.shift.length === 0 && (
        <div class="empty-state glass">
          No migration opportunities — answers are already on TikTok, or none grouped yet.
        </div>
      )}
      {data.value.shift.map((o) => (
        <div class="result glass" key={o.canonical_id}>
          <div class="meta">
            <span class="type">
              {ICON[o.source_platform]} → {ICON[o.target_platform]}
            </span>
            {o.has_demand && <span class="open">in demand</span>}
          </div>
          <p class="caption">{o.title}</p>
          <p class="evidence">
            Answered on {o.covered_on.join(", ")} — not yet on {o.target_platform}. Draft a
            {" "}
            {o.target_platform}-native version from the source.
          </p>
        </div>
      ))}
    </>
  );
});

export const head: DocumentHead = { title: "Platforms — Sift Studio" };
