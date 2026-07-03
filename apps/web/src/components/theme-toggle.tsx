import { component$ } from "@builder.io/qwik";

// Sun/moon glass button — flips html.dark and persists the choice.
export const ThemeToggle = component$(() => {
  return (
    <button
      type="button"
      class="theme-toggle glass"
      aria-label="Toggle dark mode"
      onClick$={() => {
        const dark = document.documentElement.classList.toggle("dark");
        try {
          localStorage.setItem("theme", dark ? "dark" : "light");
        } catch {
          /* private mode */
        }
      }}
    >
      <span aria-hidden="true">◐</span>
    </button>
  );
});
