import { component$ } from "@builder.io/qwik";
import { routeLoader$, Form, Link, type DocumentHead } from "@builder.io/qwik-city";
import { ThemeToggle } from "~/components/theme-toggle";
import { API_BASE, searchArchive, startHere, type SearchResponse, type StartPath } from "~/lib/api";

// The search-first landing page (plan §3): the link opens directly on the
// search bar; ?q= runs the search server-side so shared deep links and DM
// links land with results (and the answer card) already rendered. With no
// query we show "start here" entry paths so a fan who doesn't know what to
// type isn't faced with a blank box.
export const useSearch = routeLoader$<{
  handle: string;
  data: SearchResponse | null;
  q: string;
  start: StartPath[];
}>(async ({ params, query }) => {
  const q = query.get("q")?.trim() ?? "";
  const handle = params.handle;
  if (!q) {
    const sh = await startHere(handle);
    return { handle, data: null, q, start: sh?.paths ?? [] };
  }
  const data = await searchArchive(handle, q);
  return { handle, data, q, start: [] };
});

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
  } catch {
    return "";
  }
}

function fmtTs(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Outcome Memory: tell the server whether the answer helped.
function sendFeedback(handle: string, answerId: string, helpful: boolean): void {
  fetch(`${API_BASE}/api/${handle}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify({ answer_id: answerId, helpful }),
  }).catch(() => {});
}

// Explicit save for anonymous fans — client-side (localStorage), per creator.
function saveResult(handle: string, postId: string, caption: string, url: string): void {
  try {
    const key = `sift_saved_${handle}`;
    const saved = JSON.parse(localStorage.getItem(key) ?? "[]");
    if (!saved.some((s: { post_id: string }) => s.post_id === postId)) {
      saved.unshift({ post_id: postId, caption: caption.slice(0, 120), url });
      localStorage.setItem(key, JSON.stringify(saved.slice(0, 50)));
    }
  } catch {
    /* private mode */
  }
}

export default component$(() => {
  const search = useSearch();
  const { handle, data, q, start } = search.value;

  return (
    <>
      <header class="topbar">
        <div class="identity">
          <div class="avatar">{handle.charAt(0).toUpperCase()}</div>
          <div>
            <h1>@{handle}'s archive</h1>
            <p>Ask in normal words — I'll find the post.</p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <Form class="search-form glass">
        <input
          type="search"
          name="q"
          value={q}
          placeholder="e.g. the reel about price objections…"
          autoFocus
          autoComplete="off"
        />
        <button type="submit">Search</button>
      </Form>

      {!q && start.length > 0 && (
        <section class="start-here">
          <p class="results-label">Start here</p>
          <div class="chips">
            {start.map((p) => (
              <Link key={p.query} class="chip glass" href={`/${handle}?q=${encodeURIComponent(p.query)}`}>
                {p.label}
              </Link>
            ))}
          </div>
        </section>
      )}

      {data?.answer && data.answer.state === "answered" && (
        <section class="answer-card glass">
          <div class="label">
            <span class="dot" />
            From @{handle}'s content
          </div>
          <p class="answer-text">{data.answer.text}</p>
          <div class="citations">
            {data.answer.citations.map((c) => (
              <a
                class="citation"
                key={c.n}
                href={c.permalink ?? "#"}
                target="_blank"
                rel="noopener"
              >
                <span class="n">[{c.n}]</span>
                <span class="quote">{c.quote}</span>
              </a>
            ))}
          </div>
          {data.answer.answer_id && (
            <div class="feedback">
              <span>Did this help?</span>
              <button
                class="fb-btn"
                type="button"
                onClick$={() =>
                  sendFeedback(handle, data.answer!.answer_id!, true)
                }
              >
                👍 Yes
              </button>
              <button
                class="fb-btn"
                type="button"
                onClick$={() =>
                  sendFeedback(handle, data.answer!.answer_id!, false)
                }
              >
                👎 No
              </button>
            </div>
          )}
        </section>
      )}

      {data?.answer && data.answer.state === "no_strong_answer" && (
        <section class="answer-card glass">
          <div class="label">
            <span class="dot" />
            No strong answer yet
          </div>
          <p class="no-answer">
            Nothing in the archive answers that directly — try different words, or browse the
            closest posts below.
          </p>
        </section>
      )}

      {data && data.results.length > 0 && <p class="results-label">Posts</p>}

      {data?.results.map((r) => (
        <a
          class="result glass"
          key={r.post_id}
          href={r.permalink ?? "#"}
          target="_blank"
          rel="noopener"
          // fire-and-forget click signal — feeds Demand Radar + metrics
          onClick$={() => {
            fetch(`${API_BASE}/api/${handle}/events/click?post_id=${r.post_id}`, {
              method: "POST",
              keepalive: true,
            }).catch(() => {});
          }}
        >
          <div class="meta">
            <span class="type">{r.post_type}</span>
            {r.language && r.language !== "en" && <span class="lang">{r.language}</span>}
            <span class="date">{fmtDate(r.posted_at)}</span>
            <button
              class="save-btn"
              type="button"
              preventdefault:click
              onClick$={(e) => {
                e.stopPropagation();
                saveResult(handle, r.post_id, r.caption ?? "", r.permalink ?? "");
              }}
            >
              ☆ Save
            </button>
            <span class="open">Open ↗</span>
          </div>
          {r.caption && <p class="caption">{r.caption}</p>}
          {r.evidence[0] && (
            <p class="evidence">
              {r.evidence[0].start_ts != null && (
                <span class="ts">{fmtTs(r.evidence[0].start_ts)} · </span>
              )}
              {r.evidence[0].text}
            </p>
          )}
          {r.products.length > 0 && (
            <div class="products">
              {r.products.map((p) => (
                <a key={p.id} href={`${API_BASE}/api/${handle}/buy/${p.id}`}>
                  🛒 {p.name}
                </a>
              ))}
            </div>
          )}
        </a>
      ))}

      {data && data.results.length === 0 && (
        <div class="empty-state glass">
          Nothing found for “{q}” — try different words.
        </div>
      )}

      <footer class="footer">
        Powered by <a href="/">Creator Content Intelligence</a>
      </footer>
    </>
  );
});

export const head: DocumentHead = ({ resolveValue }) => {
  const { handle, q } = resolveValue(useSearch);
  return {
    title: q ? `“${q}” — @${handle}'s archive` : `Search @${handle}'s archive`,
    meta: [
      {
        name: "description",
        content: `Search everything @${handle} has ever posted — reels, captions, spoken words.`,
      },
    ],
  };
};
