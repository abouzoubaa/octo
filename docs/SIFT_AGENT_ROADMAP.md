# Sift — Agent Layer Roadmap

> **Superseded by [`ROADMAP.md`](ROADMAP.md)** — the unified roadmap merges this
> agent feature layer (Axis B) with the production-grade checklist (Axis A) on
> one timeline. This file is kept as the detailed feature-axis source.
>
> Companion to `IMPLEMENTATION_PLAN.md` (the v1 technical plan). This document
> maps the **"Sift, as a Personal Agent" proposal (rev 2)** onto the code that
> exists today, so each feature reads as an *increment*, not a rewrite.

Sift v1 *shows* a creator what their audience wants. The agent layer *acts* on
it — advise, execute, close — always behind the approval gate. **v1 ships
unchanged.** The only thing the agent layer asks of v1 now is the cheap
groundwork in §0.

**Positioning shift:** from "Search Console for your creator business" (passive,
analytical) → **"Your AI chief of staff — Sift listens to your audience, tells
you what they want, and helps you build it."**

Status legend: ✅ built · 🟡 partial (foundation exists) · ❌ not started

---

## The agent loop

The v1 loop has three audience-facing steps; the agent adds three that turn
insight into action:

```
1 LISTEN   search + comments          ← v1 ✅
2 SIFT     intent, filter, trends      ← v1 ✅ (+ §0 foundations)
3 SERVE    grounded answer to fan      ← v1 ✅
4 ADVISE   actionable insight          ← agent (v1.5)
5 EXECUTE  draft + links               ← agent (v1.5–v2)
6 CLOSE    notify asker + measure      ← agent (v2)
```

The loop closes when the original asker hears back — which seeds the next
question.

---

## §0 — Foundations (the ONLY thing that touches v1)

Build these into the v1 schema now. They cost almost nothing and are the
difference between the agent layer being a feature set and being a rebuild.

| Foundation | What it does | Release | Status in code today |
|---|---|---|---|
| **Demand clustering & dedup** | Merge semantically similar questions into one cluster ("142 people asked this"). Underpins every radar view. | v1 | ✅ `workers/radar.py` greedy centroid clustering |
| **Intent / outcome event log** | Log who asked what, what was served, what the creator did, and what happened next — the *outcome edge*. | v1 | 🟡 `events` table logs isolated events; not yet linked into question → served → action → result chains |
| **Demand-item state machine** | Each "useful" Radar card moves Idea → Drafting → Published → Loop-closed. | v1 | 🟡 `DemandTopic.creator_marked` (useful/not/made) only; no lifecycle states |
| **Voice memory** | Store approved replies/hooks and the creator's edits to drafts, so generated content stays on-voice. | v1 capture | ❌ not started |
| **Offer-awareness** | Creator tags current products/offers/campaigns; Sift routes every CTA/affiliate to the right one. | v1.5 | 🟡 `products` table + approval exist; no "current offer/campaign" concept |
| **Rules & preferences** | Tone, taboo topics, escalation triggers, monetization priorities — the business rules the agent runs under. | v1.5 | ❌ not started |

**Concrete v1 work (small, additive):**
1. Add a `status` lifecycle to `DemandTopic` (`idea → drafting → published → loop_closed`) alongside the existing `creator_marked`.
2. Extend the event log into linked **outcome records** (query/comment → answer served → creator action → measured result), so "did it work?" is answerable.
3. New **voice-memory** table capturing approved reply/hook text and draft edits.

Everything below waits for v1.5+.

---

## §1 — Audience & Demand Intelligence  *("What does my audience want?")*

Demand Radar grows from a weekly list into a segmenting, emotion-reading chief of staff.

| Feature | Release | Builds on |
|---|---|---|
| **The Briefing** — pushed daily/weekly digest with ready hooks, a re-promotion pick, open gaps, trend alerts, urgent replies, one fully drafted post | v1.5 | 🟡 `workers/digest.py` (currently a plain weekly digest) |
| **Content gap map** — answered well / partially / contradicted / never addressed | v1.5 | 🟡 radar coverage check already flags gaps |
| **Persona segmentation** — cluster audience by behaviour, per-segment feeds | v2 | 🟡 clustering infra |
| **Sentiment & emotion** — anxiety / confusion / excitement / frustration | v2 | ❌ |
| **Trend detection** — rising themes + resurfacing old posts; weekly default, spike alerts only above a volume threshold | v2 | 🟡 WoW deltas in radar |
| **Cross-platform demand synthesis** — newsletter BCC, forwarded DMs, podcast comments → "what's asked everywhere?" | v2 | 🟡 YouTube ingestion exists; multi-source intake new |
| **Competitor demand radar** — opt-in, aggregate, topic-level only | v3 | ❌ |

---

## §2 — Content Production  *("What should I make next?")*

Close the gap between a demand signal and a finished post — creator becomes editor, not writer.

| Feature | Release | Builds on |
|---|---|---|
| **Content briefs** — one-pager from a demand cluster: phrasing, coverage gaps, hook + CTA, source links | v1.5 | 🟡 radar cards + retrieval |
| **Draft generator (script + hooks)** — reel script + hooks grounded in the creator's content and the audience's literal words | v1.5 | 🟡 LLM provider + retrieval |
| **Creator recall search** — creator-only "where did I say that?" with exact sentence + reuse ideas | v1.5 | ✅ retrieval layer (new surface, mostly reuse) |
| **Multi-format repurposing** + **Sift & Shift** (YouTube topic → IG carousel from transcript) | v2 | 🟡 transcripts + LLM |
| **Series builder** — planned arc from repeated demand | v2 | 🟡 radar |
| **Performance prediction** — score a draft vs the creator's top-10% patterns | v3 | ❌ needs performance history |
| **Content calendar / planner** — cadence-aware queue, posting windows, saturation flags | v3 | ❌ |
| **Thumbnail & visual intelligence** | v3 | ❌ |

---

## §3 — Engagement & Inbox  *("What should I reply to, right now?")*

The inbox becomes a triage layer + light CRM; comment-to-DM grows into an approval-mode assistant.

| Feature | Release | Builds on |
|---|---|---|
| **Intent-labelled queue** — DMs/comments/story replies sorted: content request, purchase intent, support, collab lead | v1.5 | 🟡 `intent.py` detection + `dm_jobs` |
| **Bounded clarifying question** — one either/or to disambiguate ("pre- or post-workout?"), not open chat | v1.5 | 🟡 retrieval confidence |
| **No-answer waitlist** — "want a heads-up when Alex covers this?" captures email, feeds gap map | v1.5 | 🟡 no-answer state already exists |
| **Saved playbooks** — "when I get this kind of question, do this" templates | v1.5 | ❌ |
| **Reply assistant** — drafts public/DM replies in approved tone, grounded in citations | v2 | 🟡 DM drafting exists |
| **Agentic DM (approval mode)** — multi-turn within Meta's one-message/7-day limit; bulk approve; "always approve this type" | v2 | 🟡 `dm.py` dispatcher + window/cap enforcement |
| **Community delegation** — like a follower's good answer instead of spending the DM quota | v2 | ❌ |
| **"Not now, but…" queue** — defer a valid question, draft when the time comes, re-contact compliantly | v2 | 🟡 state machine (§0) |
| **Loop-Closer** — notify the original asker when their request is published (opted-in channel / 7-day window) | v2 | 🟡 outcome log (§0) + state machine |

---

## §4 — Monetization & Revenue

Every question is declared intent; turn it into income.

| Feature | Release | Builds on |
|---|---|---|
| **Auto-affiliate injection** — append approved affiliate link + UTM at caption time | v1.5 | ✅ product→post mapping + tracked redirects |
| **Offer-aware CTAs** — attach the right current offer to answers/recommendations | v1.5 | 🟡 offer-awareness (§0) |
| **Affiliate optimisation** — A/B link placement, anchor text, pairings | v2 | 🟡 event tracking |
| **Sponsor matchmaker & pitch** — demand-as-proof, match brand programs, draft pitch | v2 | 🟡 radar aggregates |
| **Dynamic pricing & offer insights** — objections, bundle signals, price-sensitivity by segment | v3 | ❌ |
| **Revenue forecasting & goals** | v3 | ❌ |
| **Brand partnership portal** | v3 · scale | ❌ |

---

## §5 — Brand & Reputation

| Feature | Release | Builds on |
|---|---|---|
| **Crisis / sentiment-shift detection** — negative spikes, controversy, web mentions + response framework | v2 | ❌ |
| **Voice consistency scoring** — score contractor/ghostwriter content vs the voice model | v2 | 🟡 voice memory (§0) |
| **Plagiarism / unauthorised-use monitoring** | v3 | ❌ |

---

## §6 — Growth & Strategy

| Feature | Release | Builds on |
|---|---|---|
| **Content strategy advisor** — expand vs double-down, segment growth, evergreen/trend balance | v2 | 🟡 accumulated Sift data |
| **Peer benchmarking** — opt-in / anonymised aggregate | v3 | ❌ |
| **Education & skill planning** — 1/3/5-year development plan from performance patterns | v3 | ❌ |

---

## §7 — Operations & Ecosystem

| Feature | Release | Builds on |
|---|---|---|
| **Task / project integration** — Radar card → tracked task (Notion/Asana/Linear) | v3 | 🟡 state machine (§0) |
| **Customer CRM** — unified profiles, lifecycle marketing | v3 | ❌ |
| **Team & role-based access** — owner/creator/VA/contractor + approval workflows + audit trail | v3 | 🟡 ties to the auth work in ROADMAP_TO_FULL_APP §1 |
| **Creator marketplace** | v3 · scale | ❌ |
| **Public API & dev ecosystem** | v3 · scale | 🟡 FastAPI foundation |

*Gated on scale, not the calendar:* the brand portal, marketplace, and public
API only matter at multi-creator scale — pursue only once the single-creator
loop is proven and repeatable.

---

## §8 — What to deliberately AVOID

Stated to keep the roadmap honest.

| Excluded | Why |
|---|---|
| **Open-ended chat** | Hallucination/brand risk. The bounded answer card captures most of the value safely. |
| **Auto-posting without approval** | Too much trust too early. Approval mode stays the default through v3. |
| **Real-time trend alerts** (single creator) | Low signal-to-noise. Revisit only above a query-volume threshold. |
| **Native video editing** | Scope creep. Production stays at scripts/hooks/clip references, never an editor. |
| **Cross-platform identity resolution** | Privacy-radioactive under GDPR. Do topic-level demand synthesis, never individual identity matching. |

---

## §9 — Guardrails that carry over (unchanged from v1)

Already enforced in the codebase; none relax because the system became proactive:

- **Retrieval correctness is the gate** — citation correctness must pass on a held-out set before any automation goes live (`eval/` harness, `--gate`).
- **Voice is a post-retrieval rewrite** — the agent rewrites a correct, cited answer into the creator's tone; it never generates novel claims. *Correctness first, style second.*
- **Approval mode by default** — `dm_jobs` start `pending_approval`; bulk approval and "always approve this type" come later as trust is earned.
- **DM limits shape Close** — one creator-initiated message per comment within 7 days; re-contact only via opted-in channels or inside that window (`dm.py`).
- **Privacy stays aggregate and opt-in** — demand is pseudonymized and clustered (`privacy.py`); cross-platform/competitor features are opt-in; deletion path + policy before public launch.

---

## §10 — Sequencing

| Phase | What lands |
|---|---|
| **v1 · unchanged** *(ship)* | Search-first archive, Demand Radar, comment-to-DM. **Groundwork only:** state machine, intent/outcome event log, demand clustering, voice-memory capture. |
| **v1.5 · assist** *(next)* | The Briefing, content gap map, content briefs, draft + hook generator, creator recall search, bounded clarifying, no-answer waitlist, intent-labelled inbox, saved playbooks, auto-affiliate injection, offer-aware CTAs, offer/rules tagging. |
| **v2 · agent** *(then)* | Reply assistant, agentic DM, community delegation, Loop-Closer, "not now" queue, persona segmentation, sentiment, trend detection, cross-platform synthesis, multi-format repurposing + Sift & Shift, series builder, sponsor matchmaker + pitch, affiliate optimisation, performance-loop closure, strategy advisor, crisis detection, voice scoring. |
| **v3 · scale** *(later)* | Performance prediction, content calendar, thumbnail intelligence, dynamic pricing, revenue forecasting, customer CRM, task/PM integration, team/roles, peer benchmarking, education/skill planning, competitor radar, plagiarism monitoring, brand portal, marketplace, public API. |

---

## Recommended immediate action

Per the proposal's own emphasis, the single highest-leverage move is to land the
**§0 v1 groundwork** now, while the schema is young:

1. **Demand-item state machine** on `DemandTopic` (`idea → drafting → published → loop_closed`).
2. **Outcome-linked event log** — extend `events` so a question can be traced to what was served, what the creator did, and the measured result.
3. **Voice-memory capture** — a table for approved replies/hooks and draft edits.

These three are cheap, additive, don't change v1 behaviour, and are what make the
entire v1.5–v3 agent layer an increment rather than a rebuild. The rest is
correctly deferred and gated behind the same v1 validation guardrails.

*Release tags are a sequencing hypothesis, not commitments — each feature
should pass the v1 validation gates before it ships.*
