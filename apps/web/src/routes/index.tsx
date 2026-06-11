import { component$ } from "@builder.io/qwik";

// No fancy homepage (plan phase 2): the product front door is /{creator}.
export default component$(() => {
  return (
    <div class="header">
      <h1>Creator Content Intelligence</h1>
      <p>
        Each creator has a search-first archive at <code>/&lt;handle&gt;</code> — ask in normal
        words, get the right post back with receipts.
      </p>
    </div>
  );
});
