import { component$ } from "@builder.io/qwik";
import {
  routeLoader$,
  routeAction$,
  Form,
  Link,
  type DocumentHead,
} from "@builder.io/qwik-city";
import { adminGet, adminPost, type DmQueueItem, type InboxItem } from "~/lib/admin-api";

export const useInbox = routeLoader$(async ({ params }) => {
  const cid = params.creatorId;
  const [queue, inbox] = await Promise.all([
    adminGet<DmQueueItem[]>(`/admin/creators/${cid}/dm-queue`),
    adminGet<InboxItem[]>(`/agent/creators/${cid}/inbox`),
  ]);
  return { cid, queue: queue ?? [], inbox: inbox ?? [] };
});

// Approve or reject a queued DM — the guardrail: nothing sends without this.
export const useDecide = routeAction$(async (data) => {
  const res = await adminPost(`/admin/dm-jobs/${data.jobId}/decide`, {
    approve: data.decision === "approve",
  });
  return { ok: res !== null };
});

const LABEL_EMOJI: Record<string, string> = {
  purchase_intent: "💰",
  collab_lead: "🤝",
  content_request: "📥",
  support: "🛠️",
  other: "💬",
};

export default component$(() => {
  const data = useInbox();
  const decide = useDecide();

  return (
    <>
      <header class="topbar">
        <div class="identity">
          <Link class="theme-toggle glass" href={`/studio/${data.value.cid}`} aria-label="Back">
            ←
          </Link>
          <div>
            <h1>Approval inbox</h1>
            <p>Nothing sends until you approve it</p>
          </div>
        </div>
      </header>

      <p class="results-label">Pending DMs ({data.value.queue.length})</p>
      {data.value.queue.length === 0 && (
        <div class="empty-state glass">Queue is clear — no DMs awaiting approval.</div>
      )}
      {data.value.queue.map((j) => (
        <div class="result glass" key={j.job_id}>
          <div class="meta">
            <span class="type">DM</span>
            {j.confidence != null && (
              <span class="date">conf {(j.confidence * 100).toFixed(0)}%</span>
            )}
          </div>
          {j.comment && <p class="caption">“{j.comment}”</p>}
          <p class="evidence">{j.dm_text}</p>
          <div class="actions">
            <Form action={decide}>
              <input type="hidden" name="jobId" value={j.job_id} />
              <input type="hidden" name="decision" value="approve" />
              <button class="pill-btn" type="submit">
                ✓ Approve
              </button>
            </Form>
            <Form action={decide}>
              <input type="hidden" name="jobId" value={j.job_id} />
              <input type="hidden" name="decision" value="reject" />
              <button class="pill-btn ghost" type="submit">
                ✕ Reject
              </button>
            </Form>
          </div>
        </div>
      ))}

      <p class="results-label">Triage — all questions</p>
      {data.value.inbox.map((i) => (
        <div class="result glass" key={`${i.kind}-${i.id}`}>
          <div class="meta">
            <span class="type">
              {LABEL_EMOJI[i.label] ?? "💬"} {i.label.replace("_", " ")}
            </span>
            <span class="date">{i.kind}</span>
          </div>
          {i.text && <p class="evidence">{i.text}</p>}
        </div>
      ))}
    </>
  );
});

export const head: DocumentHead = { title: "Approval inbox — Sift Studio" };
