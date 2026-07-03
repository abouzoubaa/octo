import { component$ } from "@builder.io/qwik";
import { Form, routeAction$, Link, type DocumentHead } from "@builder.io/qwik-city";

const API_BASE =
  (typeof process !== "undefined" && process.env.PUBLIC_API_BASE) || "http://localhost:8000";

// Send the operator to the Instagram consent screen for the chosen handle.
export const useConnect = routeAction$(async (data, { redirect }) => {
  const handle = String(data.handle ?? "").trim().toLowerCase();
  if (!handle) return { error: "handle required" };
  throw redirect(302, `${API_BASE}/oauth/instagram/start?handle=${encodeURIComponent(handle)}`);
});

export default component$(() => {
  const connect = useConnect();
  return (
    <>
      <header class="topbar">
        <div class="identity">
          <Link class="theme-toggle glass" href="/studio" aria-label="Back">
            ←
          </Link>
          <div>
            <h1>Connect Instagram</h1>
            <p>Authorize a Business/Creator account</p>
          </div>
        </div>
      </header>

      <Form action={connect} class="search-form glass">
        <input type="text" name="handle" placeholder="choose a handle, e.g. alex" autoFocus />
        <button type="submit">Connect →</button>
      </Form>

      {connect.value?.error && <div class="empty-state glass">{connect.value.error}</div>}

      <div class="answer-card glass">
        <div class="label">
          <span class="dot" />
          What happens next
        </div>
        <p class="evidence">
          You'll be sent to Instagram to grant access (basic profile, comments, messages).
          On approval we store an encrypted long-lived token, start importing the archive,
          and open the studio for that creator.
        </p>
      </div>
    </>
  );
});

export const head: DocumentHead = { title: "Connect Instagram — Sift Studio" };
