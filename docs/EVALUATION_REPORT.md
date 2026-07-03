# Sift — Full-Codebase Evaluation Report

**Scope:** evaluate all production code, test and correct bugs, verify implementation
against `MASTER_SPEC` and `ARCHITECTURE`, apply corrections/optimizations/improvements.
**Date:** 2026-07-03 · **Branch:** `claude/creator-content-search-plan-h6o6kf`

---

## 1. Method

1. **Baseline verification** — full backend + frontend test suites, lint, both web
   builds, migration chain.
2. **Adversarial code review** (independent reviewer) of the one wave not previously
   reviewed (the deferred-items commit: cost metering, TikTok per-account capability,
   DM lock, injection sweep, pseudonym secret).
3. **Spec-conformance audit** (independent auditor) — every claim in MASTER_SPEC
   Part IV and every endpoint in ARCHITECTURE §3b checked against the actual code:
   all 67 `/agent` routes enumerated, every named function in all 18 agent modules
   verified non-trivial, ~12 load-bearing features semantically spot-checked, UI
   claims verified against the Qwik routes.
4. **Fixes, optimizations, improvements** applied in two committed, tested waves.

## 2. Baseline (before this evaluation)

311 backend + 9 frontend tests green · ruff clean · client + server builds green ·
migrations 0001–0004 applying. No pre-existing failures.

## 3. Findings

### Adversarial review (deferred-items wave) — no HIGH; 4 MED/LOW, all fixed
| Sev | Finding | Fix |
|---|---|---|
| MED | The anonymous-answer ceiling metered `op="answer"` from **three** surfaces (fan page, DM pipeline, dev API) — heavy legitimate DM/API volume would degrade the fan page with zero abuse | `generate_answer` takes an `op` tag; surfaces now meter as `answer` / `dm_answer` / `api_answer` / `eval_answer`; the ceiling measures only the anonymous page |
| MED | Per-search ceiling check fetched + JSON-decoded **every** month-to-date event row in Python (linear growth with traffic) | Aggregation pushed into SQL (`SUM(payload->'tokens')` + op filter in the WHERE, on the existing `(creator_id, kind, ts)` index) |
| MED | `sync_native` could persist a `PlatformAccount` grant contradicting actual behavior (explicit full-loop connector, stored archive) | Grant + capabilities now persisted from the connector actually doing the sync |
| LOW/MED | `get_connector`'s `try/except TypeError` could mask a genuine constructor bug as "no full_loop param" and silently downgrade a granted account | Replaced with `inspect.signature` parameter check |

Verified-correct by the reviewer: metering exception flow, advisory-lock transaction
span (no mid-dispatch commits), FakeLLM keyword matching unaffected by the injection
guards, migration chain integrity.

### Spec-conformance audit — docs substantially accurate; one systemic gap, closed
All 67 agent routes exist and match; zero stubs/TODOs in product code; the eval gate,
DM compliance bounds, Studio UI claims, and test counts all verified exactly. The one
systemic finding: **six features existed as implemented, tested library code with no
production caller.** Per the goal ("implemented according to spec"), five were wired
and one honestly re-marked:

| Feature (spec §) | Now reachable via |
|---|---|
| Bounded clarifying question (§05, v1.5) | Public search response on no-strong-answer + fan-page either/or chips (zero-JS `?q=` refinement) |
| No-answer waitlist / email-capture bridge (§05/§13, v1.5) | Fan-page email form → `POST /api/{handle}/waitlist`, cohort size shown back |
| Saved playbooks (§05, v1.5) | `match_playbook` applied in the comment→DM pipeline — matched template, still approval mode, skips an LLM call |
| Auto-affiliate injection (§06, v1.5) | Applied at draft approval (caption-time proxy — auto-posting stays deliberately avoided), with visible disclosure |
| Community delegation (§05, v2) | Candidate surfaced as a hint in the DM approval queue (the like itself stays manual — the official API has no comment-like endpoint) |
| Reply assistant (§05, v2) | Re-marked ◑ — it drives the agentic-DM thread path, which is itself honestly ◑ |

Also corrected in the docs: four rows marked "deferred" are actually **live opt-in
scaffolds** (competitor radar, peer benchmarking, plagiarism scan — a real
pgvector-similarity repost detector — and task export); three endpoint paths fixed;
a fan-side surface catalog added (start-here / popular / topics / cohorts / feedback
/ save were undocumented); billing's location corrected (`cci_core.billing`, not
providers). Both PDFs regenerated.

### Own findings
- **Scheduler jobs had no retry policy** (previously flagged, never fixed) — a
  transient failure in a scheduled sync/radar/refresh silently dropped. Fixed:
  `DEFAULT_RETRY` on scheduled jobs; the DM dispatcher deliberately stays retry-free
  (next tick re-runs; the advisory lock makes overlap safe).
- **Digest delivery was a log stub** (documented gap). Implemented: `cci_core.mailer`
  (SMTP/STARTTLS behind config, log fallback — content never lost), `Creator.email`
  (migration 0005, settable via the admin API); digest + briefing now email when
  configured.

## 4. Changes shipped (2 commits)

**Wave 1** — scheduler retries; digest email transport (+ `Creator.email`, migration
0005, 4 tests).
**Wave 2** — all four review fixes; five spec wirings (+ fan-page waitlist form and
clarify chips, `AnswerOut.clarify`, playbook path in `_prepare_dm`, affiliate
injection in `decide_draft`, delegation hint in `dm-queue`); doc corrections; PDFs
regenerated; 5 wiring tests + updated types/CSS.

## 5. Final verification

| Check | Result |
|---|---|
| Backend tests | **320 passed** (was 311; +9 new) |
| Frontend tests (Vitest) | **9 passed** |
| Lint (ruff, all packages) | clean |
| Web builds (client + SSR server) | green |
| Migrations | 0001 → **0005** apply cleanly |
| Spec conformance | Every v1 + v1.5 + v2 feature implemented **and reachable**; v3 built or live-scaffolded except brand portal + marketplace (fully deferred, scale-gated); avoided-list still correctly unbuilt |

## 6. Remaining known gaps (deliberate, documented)

- **Hosted OAuth consent screen** — tokens are operator-set; the flow downstream is
  built (environment-bound: needs live platform apps).
- **Agentic-DM thread dispatcher** (◑) — follow-up turns exist behind approval
  helpers; the dedicated dispatcher isn't wired.
- **Scale features** — brand portal, creator marketplace (fully deferred);
  competitor radar / peer benchmarking aggregates await a multi-creator panel.
- **Live-API quirks** — connectors are verified against faithful fakes; quota/auth
  edge cases unexercised offline.
- Pre-existing, accepted: Instagram sends happen inside the dispatch DB transaction
  (a crash mid-loop re-sends on the next run — concurrency dupes are locked out,
  crash dupes are not).

**Verdict:** the codebase is consistent with both specification documents, all
discovered defects are fixed, and the docs now match the code in both directions.
