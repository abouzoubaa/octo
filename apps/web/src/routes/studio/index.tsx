import { component$ } from "@builder.io/qwik";
import { routeLoader$, Link, type DocumentHead } from "@builder.io/qwik-city";
import { adminGet, type CreatorRow } from "~/lib/admin-api";

export const useCreators = routeLoader$(async () => {
  return (await adminGet<CreatorRow[]>("/admin/creators")) ?? [];
});

export default component$(() => {
  const creators = useCreators();
  return (
    <>
      <header class="topbar">
        <div class="identity">
          <div class="avatar">S</div>
          <div>
            <h1>Sift Studio</h1>
            <p>Your AI chief of staff — pick a creator</p>
          </div>
        </div>
      </header>

      <a class="studio-nav-item glass" href="/studio/connect" style="display:block;margin-bottom:14px;">
        ➕ Connect an Instagram account
      </a>

      {creators.value.length === 0 && (
        <div class="empty-state glass">
          No creators yet. Connect an Instagram account above, or onboard one with
          <code> cci-ingest create-creator</code>.
        </div>
      )}

      {creators.value.map((c) => (
        <Link class="result glass" key={c.id} href={`/studio/${c.id}`}>
          <div class="meta">
            <span class="type">{c.status}</span>
            <span class="open">Open studio →</span>
          </div>
          <p class="caption">@{c.handle}</p>
          <p class="evidence">{c.display_name}</p>
        </Link>
      ))}
    </>
  );
});

export const head: DocumentHead = { title: "Sift Studio" };
