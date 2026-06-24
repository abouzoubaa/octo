import { component$ } from "@builder.io/qwik";
import {
  routeLoader$,
  routeAction$,
  Form,
  Link,
  type DocumentHead,
} from "@builder.io/qwik-city";
import { adminGet, adminPost, type DraftRow } from "~/lib/admin-api";

export const useDrafts = routeLoader$(async ({ params }) => {
  const cid = params.creatorId;
  return { cid, drafts: (await adminGet<DraftRow[]>(`/agent/creators/${cid}/drafts`)) ?? [] };
});

// Approve a draft — captures the creator's voice; never auto-publishes.
export const useApproveDraft = routeAction$(async (data) => {
  const res = await adminPost(`/agent/drafts/${data.draftId}/decide`, { approve: true });
  return { ok: res !== null };
});

export default component$(() => {
  const data = useDrafts();
  const approve = useApproveDraft();

  return (
    <>
      <header class="topbar">
        <div class="identity">
          <Link class="theme-toggle glass" href={`/studio/${data.value.cid}`} aria-label="Back">
            ←
          </Link>
          <div>
            <h1>Drafts</h1>
            <p>Grounded in your content — edit & approve</p>
          </div>
        </div>
      </header>

      {data.value.drafts.length === 0 && (
        <div class="empty-state glass">
          No drafts yet — generate one from a demand card in the pipeline.
        </div>
      )}

      {data.value.drafts.map((d) => (
        <div class="result glass" key={d.id}>
          <div class="meta">
            <span class="type">{d.status}</span>
          </div>
          <p class="caption">{d.title}</p>
          {d.hooks && d.hooks.length > 0 && (
            <p class="evidence">
              <strong>Hook:</strong> {d.hooks[0]}
            </p>
          )}
          {d.script && <p class="evidence">{d.script.slice(0, 220)}</p>}
          {d.cta && <p class="evidence">CTA: {d.cta}</p>}
          {d.status === "draft" && (
            <div class="actions">
              <Form action={approve}>
                <input type="hidden" name="draftId" value={d.id} />
                <button class="pill-btn" type="submit">
                  ✓ Approve
                </button>
              </Form>
            </div>
          )}
        </div>
      ))}
    </>
  );
});

export const head: DocumentHead = { title: "Drafts — Sift Studio" };
