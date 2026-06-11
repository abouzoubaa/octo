import { component$ } from "@builder.io/qwik";
import { routeLoader$, Form, type DocumentHead } from "@builder.io/qwik-city";
import { ThemeToggle } from "~/components/theme-toggle";
import { API_BASE, searchArchive, type SearchResponse } from "~/lib/api";

// The search-first landing page (plan §3): the link opens directly on the
// search bar; ?q= runs the search server-side so shared deep links and DM
// links land with results (and the answer card) already rendered.
export const useSearch = routeLoader$<{ handle: string; data: SearchResponse | null; q: string }>(
  async ({ params, query }) => {
    const q = query.get("q")?.trim() ?? "";
    const handle = params.handle;
    if (!q) return { handle, data: null, q };
    const data = await searchArchive(handle, q);
    return { handle, data, q };
  }
);

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

export default component$(() => {
  const search = useSearch();
  const { handle, data, q } = search.value;

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
            <span class="date">{fmtDate(r.posted_at)}</span>
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
