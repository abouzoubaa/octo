import { component$ } from "@builder.io/qwik";
import { routeLoader$, Form, type DocumentHead } from "@builder.io/qwik-city";
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

export default component$(() => {
  const search = useSearch();
  const { handle, data, q } = search.value;

  return (
    <>
      <div class="header">
        <h1>@{handle}'s archive</h1>
        <p>Ask in normal words — I'll find the post.</p>
      </div>

      <Form class="search-form">
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
        <div class="answer-card">
          <div class="label">From @{handle}'s content</div>
          <p>{data.answer.text}</p>
          {data.answer.citations.map((c) => (
            <div class="citation" key={c.n}>
              [{c.n}]{" "}
              {c.permalink ? (
                <a href={c.permalink} target="_blank" rel="noopener">
                  original post ↗
                </a>
              ) : (
                "source"
              )}{" "}
              — “{c.quote.slice(0, 120)}…”
            </div>
          ))}
        </div>
      )}

      {data?.answer && data.answer.state === "no_strong_answer" && (
        <div class="answer-card">
          <p class="no-answer">
            No strong answer for that in the archive yet — try different words, or browse the
            results below.
          </p>
        </div>
      )}

      {data?.results.map((r) => (
        <a
          class="result"
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
          <span class="type">{r.post_type}</span>
          {r.caption && <p class="caption">{r.caption.slice(0, 140)}</p>}
          {r.evidence[0] && <p class="evidence">…{r.evidence[0].text.slice(0, 180)}…</p>}
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

      <div class="footer">
        Powered by <a href="/">Creator Content Intelligence</a>
      </div>
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
