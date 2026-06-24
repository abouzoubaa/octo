import { component$ } from "@builder.io/qwik";
import { routeLoader$, routeAction$, Form, Link, type DocumentHead } from "@builder.io/qwik-city";
import {
  adminGet,
  adminPost,
  type CanonicalRow,
  type ConnectorRow,
  type ShiftOpportunity,
} from "~/lib/admin-api";

export const useCrossPlatform = routeLoader$(async ({ params, query }) => {
  const cid = params.creatorId;
  const allPlatforms = (await adminGet<ConnectorRow[]>("/admin/platforms")) ?? [];
  // Shift targets are platforms that host publishable content (not pure demand
  // sources like a newsletter or Discord). content.read == "hosts content".
  const targets = allPlatforms
    .filter((p) => p.capabilities.includes("content.read"))
    .map((p) => p.platform);
  const target = targets.includes(query.get("to") ?? "") ? query.get("to")! : (targets[0] ?? "tiktok");
  const [connected, canonical, shift] = await Promise.all([
    adminGet<ConnectorRow[]>(`/admin/creators/${cid}/connectors`),
    adminGet<CanonicalRow[]>(`/agent/creators/${cid}/canonical`),
    adminGet<ShiftOpportunity[]>(
      `/agent/creators/${cid}/sift-and-shift?target_platform=${target}`,
    ),
  ]);
  const connectedRows = connected ?? [];
  return {
    cid,
    allPlatforms,
    targets,
    target,
    connected: new Set(connectedRows.map((c) => c.platform)),
    // platform → last_synced_at ISO string (null = connected, never synced)
    synced: Object.fromEntries(connectedRows.map((c) => [c.platform, c.last_synced_at ?? null])),
    canonical: canonical ?? [],
    shift: shift ?? [],
  };
});

// "synced 3h ago" / "never synced" — coarse relative time, computed server-side.
function syncedLabel(iso: string | null | undefined): string {
  if (iso === undefined) return "";
  if (iso === null) return "never synced";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return "synced just now";
  const mins = secs / 60;
  if (mins < 90) return `synced ${Math.round(mins)}m ago`;
  const hrs = mins / 60;
  if (hrs < 36) return `synced ${Math.round(hrs)}h ago`;
  return `synced ${Math.round(hrs / 24)}d ago`;
}

// (Re)group repurposed posts into canonical answers.
export const useGroup = routeAction$(async (data) => {
  const res = await adminPost<{ canonical_objects: number }>(
    `/agent/creators/${data.cid}/canonical/group`,
  );
  return { ok: res !== null, n: res?.canonical_objects };
});

// Backfill a connected native platform (e.g. YouTube) through its connector.
export const useSync = routeAction$(async (data) => {
  const res = await adminPost<{ job_id: string; platform: string }>(
    `/admin/creators/${data.cid}/sync-native?platform=${data.platform}`,
  );
  return { ok: res !== null, platform: data.platform as string };
});

// Draft a platform-native version of a source post → lands in Drafts.
export const useShift = routeAction$(async (data) => {
  const res = await adminPost<{ draft_id?: string }>(
    `/agent/posts/${data.postId}/shift?target_platform=${data.target}`,
  );
  return { ok: res !== null, draftId: res?.draft_id };
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
  const shift = useShift();
  const sync = useSync();

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
            {data.value.connected.has(p.platform) && (
              <span class="date">{syncedLabel(data.value.synced[p.platform])}</span>
            )}
          </div>
          <p class="evidence">
            {p.capabilities.map((c) => c.replace(".", " ")).join(" · ")}
          </p>
          {data.value.connected.has(p.platform) && p.capabilities.includes("content.read") && (
            <div class="actions">
              <Form action={sync}>
                <input type="hidden" name="cid" value={data.value.cid} />
                <input type="hidden" name="platform" value={p.platform} />
                <button class="pill-btn ghost" type="submit">
                  ⟲ Sync now
                </button>
              </Form>
              {sync.value?.ok && sync.value.platform === p.platform && (
                <span class="open">queued ✓</span>
              )}
            </div>
          )}
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
        Sift &amp; Shift → {ICON[data.value.target] ?? ""} {data.value.target}
      </p>
      <div class="actions" style="margin-bottom:10px;">
        {data.value.targets.map((t) => (
          <Link
            key={t}
            href={`?to=${t}`}
            class={`pill-btn ${t === data.value.target ? "" : "ghost"}`}
          >
            {ICON[t] ?? "🔌"} {t}
          </Link>
        ))}
      </div>
      {data.value.shift.length === 0 && (
        <div class="empty-state glass">
          No migration opportunities — answers are already on {data.value.target}, or none grouped
          yet.
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
          <div class="actions">
            <Form action={shift}>
              <input type="hidden" name="postId" value={o.source_post_id} />
              <input type="hidden" name="target" value={o.target_platform} />
              <button class="pill-btn" type="submit">
                ✍️ Draft {ICON[o.target_platform] ?? ""} version
              </button>
            </Form>
            {shift.value?.ok && shift.value.draftId && (
              <Link
                class="pill-btn ghost"
                href={`/studio/${data.value.cid}/drafts#draft-${shift.value.draftId}`}
              >
                ✓ Drafted — open Drafts
              </Link>
            )}
          </div>
        </div>
      ))}
    </>
  );
});

export const head: DocumentHead = { title: "Platforms — Sift Studio" };
