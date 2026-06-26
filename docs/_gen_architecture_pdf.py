#!/usr/bin/env python3
"""Generate docs/ARCHITECTURE.pdf — Sift architecture + workflow pipeline, diagram-rich."""
from weasyprint import HTML

CSS = """
@page { size: A4; margin: 14mm 12mm 16mm; @bottom-right {
  content: "Sift — Architecture & Workflow · " counter(page); font-size: 7.5pt; color: #8a9299; } }
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #16242a; font-size: 9.5pt; line-height: 1.45; }
h1 { font-size: 22pt; color: #0a4a57; margin: 0 0 2px; }
.sub { color: #5b6a70; font-size: 10pt; margin: 0 0 14px; }
h2 { font-size: 13.5pt; color: #0a4a57; border-bottom: 2px solid #0a84a6; padding-bottom: 3px; margin: 22px 0 12px; }
h3 { font-size: 10.5pt; color: #145a67; margin: 14px 0 6px; }
.section { page-break-inside: avoid; }
.pagebreak { page-break-before: always; }
.legend { font-size: 8pt; color: #5b6a70; margin: 6px 0 14px; }
.legend span { display: inline-block; padding: 1px 7px; border-radius: 3px; margin-right: 6px; font-weight: 600; }

/* layered stack */
.band { display: flex; align-items: stretch; margin: 5px 0; border-radius: 7px; overflow: hidden; }
.band-label { flex: 0 0 86px; padding: 8px 8px; color: #fff; font-weight: 700; font-size: 8pt;
  display: flex; align-items: center; text-transform: uppercase; letter-spacing: .04em; }
.band-body { flex: 1; display: flex; flex-wrap: wrap; gap: 5px; padding: 7px; background: #f6fafb; align-items: center; }
.box { border-radius: 5px; padding: 5px 8px; font-size: 8pt; font-weight: 600; border: 1px solid; background: #fff; }
.box small { display: block; font-weight: 400; color: #5b6a70; font-size: 7pt; }

.c-surface { background: #0a84a6; } .b-surface { border-color: #0a84a6; color: #0a4a57; }
.c-api { background: #1f6f8b; } .b-api { border-color: #1f6f8b; color: #1c4a5c; }
.c-app { background: #2e5e9e; } .b-app { border-color: #2e5e9e; color: #234a7c; }
.c-worker { background: #6b4ea0; } .b-worker { border-color: #6b4ea0; color: #4e3a78; }
.c-data { background: #3b4a52; } .b-data { border-color: #3b4a52; color: #2b363c; }
.c-ext { background: #8a949a; } .b-ext { border-color: #b6bfc4; color: #55606a; background: #fbfcfc; }
.c-dom { background: #6b4ea0; } .b-dom { border-color: #b9a9da; color: #4e3a78; background: #fbfaff; }
.dband-label { flex: 0 0 118px; }
.chip { border:1px solid #c9bce6; background:#fff; border-radius: 4px; padding: 3px 6px; font-size: 7.6pt; font-weight:600; color:#3f3168; }

/* horizontal flow with arrows */
.flow { display: flex; align-items: stretch; flex-wrap: wrap; gap: 0; margin: 8px 0; }
.step { flex: 1; min-width: 78px; border: 1px solid #c9d6da; border-radius: 6px; background: #fff;
  padding: 6px 7px; position: relative; }
.step .n { display: inline-block; background: #0a84a6; color: #fff; border-radius: 50%; width: 15px; height: 15px;
  text-align: center; font-size: 7.5pt; line-height: 15px; font-weight: 700; margin-bottom: 3px; }
.step .t { font-weight: 700; font-size: 8.3pt; color: #0a4a57; }
.step .d { font-size: 7pt; color: #5b6a70; line-height: 1.25; margin-top: 2px; }
.arrow { flex: 0 0 14px; align-self: center; text-align: center; color: #0a84a6; font-weight: 700; font-size: 11pt; }

/* vertical numbered pipeline */
.vstage { display: flex; gap: 9px; margin: 0; padding: 7px 0; border-bottom: 1px dashed #d8e2e5; page-break-inside: avoid; }
.vstage:last-child { border-bottom: none; }
.vn { flex: 0 0 22px; height: 22px; background: linear-gradient(135deg,#0a84a6,#2e5e9e); color: #fff;
  border-radius: 50%; text-align: center; line-height: 22px; font-weight: 700; font-size: 9pt; }
.vbody { flex: 1; }
.vbody .vt { font-weight: 700; color: #0a4a57; font-size: 9.3pt; }
.vbody .vt .tag { float: right; font-size: 7pt; color: #6b4ea0; background: #efeaf7; border-radius: 3px; padding: 1px 6px; font-weight: 600; }
.vbody .vd { color: #44525a; font-size: 8.3pt; margin-top: 1px; }
.vbody .vm { color: #1f6f8b; font-size: 7.5pt; font-family: monospace; margin-top: 2px; }

table { border-collapse: collapse; width: 100%; font-size: 8.2pt; margin: 8px 0; }
th { background: #14323a; color: #fff; text-align: left; padding: 4px 7px; }
td { border-bottom: 1px solid #e0e8ea; padding: 4px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafb; }
code { font-family: monospace; background: #eef2f3; padding: 0 3px; border-radius: 3px; font-size: 8pt; }
.note { background: #eef6f8; border-left: 4px solid #0a84a6; padding: 7px 11px; font-size: 8.4pt; margin: 10px 0; border-radius: 0 5px 5px 0; }
"""


def band(label, cls, boxes):
    bx = "".join(f'<div class="box b-{cls}">{b}</div>' for b in boxes)
    return (f'<div class="band"><div class="band-label c-{cls}">{label}</div>'
            f'<div class="band-body">{bx}</div></div>')


def flow(steps):
    parts = []
    for i, (t, d) in enumerate(steps, 1):
        parts.append(f'<div class="step"><span class="n">{i}</span>'
                     f'<div class="t">{t}</div><div class="d">{d}</div></div>')
        if i < len(steps):
            parts.append('<div class="arrow">▸</div>')
    return f'<div class="flow">{"".join(parts)}</div>'


def dband(label, chips):
    cs = "".join(f'<div class="chip">{c}</div>' for c in chips)
    return (f'<div class="band"><div class="band-label dband-label c-dom">{label}</div>'
            f'<div class="band-body" style="background:#faf8ff">{cs}</div></div>')


def cat(title, rows):
    body = "".join(f'<tr><td>{f}</td><td><code>{m}</code></td><td><code>{e}</code></td></tr>' for f, m, e in rows)
    return (f'<h3>{title}</h3><table><tr><th style="width:33%">Feature</th>'
            f'<th style="width:34%">Module · function</th><th>Endpoint</th></tr>{body}</table>')


def vstage(n, title, tag, desc, mods):
    return (f'<div class="vstage"><div class="vn">{n}</div><div class="vbody">'
            f'<div class="vt">{title}<span class="tag">{tag}</span></div>'
            f'<div class="vd">{desc}</div><div class="vm">{mods}</div></div></div>')


stack = "".join([
    band("Surfaces", "surface", [
        "Fan search pages<small>Qwik · near-zero-JS</small>",
        "Creator Studio<small>Qwik City · SSR</small>",
        "Operator / Admin<small>bearer auth</small>"]),
    band("API edge", "api", [
        "public<small>search · answer</small>", "public_api<small>/v1 scoped keys</small>",
        "oauth", "webhooks", "admin", "agent", "billing"]),
    band("Application", "app", [
        "cci_retrieval<small>search · answer · chunking · indexer · intent</small>",
        "cci_agent — the agent layer<small>18 modules · ~70 endpoints · 7 domains (expanded in §4)</small>",
        "cci_providers<small>llm · embeddings · stt · ocr · rerank · billing (fakes)</small>",
        "cci_core<small>models · db · connectors · privacy · safety · cost · billing · gdpr</small>"]),
    band("Workers · RQ", "worker", [
        "ingest lane<small>backfill · media · transcribe/OCR/enrich/index</small>",
        "realtime lane<small>webhook comment → DM</small>",
        "periodic lane<small>radar · digest · native sync</small>",
        "scheduler.tick()<small>~5 min cadence</small>"]),
    band("Data plane", "data", [
        "PostgreSQL + pgvector<small>relational + vectors</small>",
        "Redis<small>queues + locks</small>", "S3 / object store<small>media</small>"]),
    band("External", "ext", [
        "Instagram", "YouTube", "TikTok", "Newsletter / Podcast / Discord",
        "LLM · Embeds · STT · OCR · Rerank", "Stripe"]),
])

loop = flow([
    ("LISTEN", "search + comments captured"),
    ("SIFT", "cluster intent, strip noise, trends"),
    ("SERVE", "grounded cited answer to fan"),
    ("ADVISE", "demand → actionable insight"),
    ("EXECUTE", "draft + links, one-tap approve"),
    ("CLOSE", "notify asker + measure"),
])

pipeline = "".join([
    vstage(1, "Connect", "oauth · admin",
           "Creator OAuth or operator token; capability-tagged account (incl. TikTok per-account full-loop).",
           "oauth.py · admin.set_token · PlatformAccount · connectors registry"),
    vstage(2, "Sync / Ingest", "ingest lane",
           "Manual ‘Sync now’, ‘Sync all’, or hourly. Connector output → Posts + Comments, idempotent, per-item SAVEPOINT, PII-redacted + pseudonymized.",
           "connectors.backfill_content → sync_native / ingest_instagram / ingest_youtube / ingest_import"),
    vstage(3, "Enrich", "ingest lane",
           "Per new post: transcribe (Whisper), OCR on-screen text, LLM summary/topics/keywords, language detection.",
           "enrich.py · providers (stt, ocr, llm) · language.py → Transcript"),
    vstage(4, "Index", "ingest lane",
           "Chunk content + embed into pgvector beside a generated tsv full-text column. Deletion purges chunks.",
           "chunking.py · indexer.py · embeddings provider → Chunk(embedding, tsv)"),
    vstage(5, "Serve", "API · public",
           "Hybrid search: FTS + pgvector cosine → RRF fusion → optional rerank → confidence. Grounded cited answer card, or ‘no strong answer’.",
           "search.py (RRF + rerank) · answer.py (cited; voice = post-retrieval rewrite)"),
    vstage(6, "Listen", "realtime lane",
           "Comment webhook (signature-verified, idempotent) → intent detection → same retrieval layer. Query logged as demand.",
           "webhooks.py · intent.py · _claim_event (dedup)"),
    vstage(7, "Respond", "realtime lane",
           "Approval-mode DmJob → dispatcher: capability gate + per-creator advisory lock + 7-day window + hourly cap. One public reply + one private DM (answer + deep link); low-confidence → archive link.",
           "dm.dispatch_approved · _can_dm · _try_lock · deep_links.py"),
    vstage(8, "Learn", "periodic lane",
           "Cluster searches + comments + external signals → Demand Integrity (unique askers, organic/prompted, persistence, sentiment, manipulation risk, exposure-normalized) → explainable Opportunity Score.",
           "radar.build_radar · demand.compute_integrity · opportunity_score → DemandTopic"),
    vstage(9, "Reconcile", "API · admin",
           "Each card classified against the creator’s own archive: gap / partial / well, with the covering permalink — ‘make new’ vs ‘re-promote’.",
           "_reconcile_demand · coverage strength + permalinks"),
    vstage(10, "Act", "agent layer",
           "One-tap: content brief + draft (script/hooks), series builder, multi-format repurpose + Sift & Shift, reply assistant, Loop-Closer, briefing.",
           "drafting · repurposing · engagement · briefing · canonical"),
    vstage(11, "Close", "state machine",
           "Publish or re-promote → demand state → loop_closed; Outcome logged. North-star: closed loops/week, split made vs re-promoted.",
           "agent_foundations.transition_demand · repromote_topic · Outcome"),
    vstage(12, "Measure", "eval · cost",
           "Citation-correctness gate (fails closed if nothing answerable) before automation; events + per-creator AI cost metering; causal layer (holdouts, baselines, CIs) measures lift.",
           "cci_eval.harness · events.py · cost.meter_llm · causal.py"),
])

ingest_flow = flow([
    ("Connector", "backfill_content()"),
    ("sync_native", "SAVEPOINT/item · upsert"),
    ("Enrich", "STT · OCR · LLM"),
    ("Chunk", "split + metadata"),
    ("Embed", "versioned model"),
    ("Index", "Chunk(embedding,tsv)"),
])
retrieval_flow = flow([
    ("Query", "fan / comment intent"),
    ("FTS", "Postgres full-text"),
    ("Vector", "pgvector cosine"),
    ("RRF", "fuse rankings"),
    ("Rerank", "optional"),
    ("Answer", "cited card / no-answer"),
])
demand_flow = flow([
    ("Signals", "search+comment+external"),
    ("Cluster", "dedup"),
    ("Integrity", "askers · risk · norm"),
    ("Score", "explainable"),
    ("Reconcile", "gap / answered"),
    ("Act + Close", "draft → loop_closed"),
])

agent_domains = "".join([
    dband("Foundations §02", ["Demand clustering", "Voice memory", "Offer-awareness",
        "Rules & preferences", "Permission ladder", "State machine", "Outcome event log"]),
    dband("Audience & Demand §03", ["The Briefing", "Content gap map", "Persona segmentation",
        "Sentiment & emotion", "Trend detection", "Cross-platform synthesis", "Competitor radar*",
        "Opportunity Score", "Demand Certificate"]),
    dband("Content Production §04", ["Content briefs", "Draft generator", "Creator recall",
        "Repurposing", "Sift & Shift", "Series builder", "Performance prediction", "Content calendar",
        "Thumbnails", "Canonical answers", "Claim layer"]),
    dband("Engagement & Inbox §05", ["Intent-labelled queue", "Bounded clarifying", "No-answer waitlist",
        "Saved playbooks", "Reply assistant", "Agentic DM", "Community delegation", "‘Not now’ queue",
        "Loop-Closer"]),
    dband("Monetization §06", ["Auto-affiliate injection", "Offer-aware CTAs", "Affiliate optimisation",
        "Sponsor matchmaker + pitch", "Dynamic pricing", "Revenue forecasting"]),
    dband("Brand & Reputation §07", ["Crisis / sentiment-shift", "Voice consistency scoring",
        "Plagiarism monitoring*"]),
    dband("Growth & Strategy §08", ["Content strategy advisor", "Peer benchmarking*", "Education & skill plan"]),
    dband("Operations §09", ["Task / PM export", "Customer CRM", "Team & roles", "Public API + keys"]),
    dband("Causal (measurement)", ["Interventions", "Holdouts", "Matched baseline", "Holdout lift", "Confidence intervals"]),
])

cat_foundations = cat("Foundations §02 — the data & memory the agent rides on", [
    ("Demand clustering & dedup", "radar.build_radar", "admin .../radar/build"),
    ("Voice memory", "agent_foundations.capture_voice", "POST/GET /creators/{id}/voice"),
    ("Offer-awareness", "monetization.offer_cta + offers", "POST/GET /creators/{id}/offers"),
    ("Rules & preferences", "agent_foundations.get_rules", "GET/PUT /creators/{id}/rules"),
    ("Permission ladder", "permissions.permission_for/can_auto_execute", "GET/PUT /permissions · /automation/pause"),
    ("Demand-item state machine", "agent_foundations.transition_demand", "POST /demand/{id}/transition"),
    ("Intent / outcome event log", "Outcome · events", "GET /creators/{id}/outcomes"),
])
cat_audience = cat("§03 Audience & demand intelligence", [
    ("The Briefing", "briefing.build_briefing", "GET /creators/{id}/briefing"),
    ("Content gap map", "briefing.content_gap_map", "GET /creators/{id}/gap-map"),
    ("Persona segmentation", "intelligence.segment_personas", "GET /creators/{id}/personas"),
    ("Sentiment & emotion", "intelligence.score_sentiment", "GET /creators/{id}/sentiment"),
    ("Trend detection", "intelligence.detect_trends", "GET /creators/{id}/trends"),
    ("Cross-platform demand synthesis", "radar + demand sources", "POST /creators/{id}/external-signal"),
    ("Competitor demand radar (opt-in)", "growth.competitor_radar", "GET /creators/{id}/competitor-radar"),
    ("Opportunity Score (explainable)", "demand.opportunity_score", "GET /demand/{id}/opportunity"),
    ("Demand Certificate", "demand.demand_certificate", "GET /demand/{id}/certificate"),
    ("Pipeline + north-star", "demand.closed_loops", "GET /demand/pipeline · /north-star"),
])
cat_content = cat("§04 Content production", [
    ("Content briefs", "drafting.generate_brief", "(via draft)"),
    ("Draft generator (script + hooks)", "drafting.generate_draft", "POST /demand/{id}/draft · /drafts"),
    ("Creator recall search", "drafting.creator_recall", "GET /creators/{id}/recall"),
    ("Multi-format repurposing", "repurposing.repurpose", "POST /posts/{id}/repurpose"),
    ("Sift & Shift", "repurposing.sift_and_shift / draft_shift", "GET /sift-and-shift · POST /posts/{id}/shift"),
    ("Series builder", "repurposing.build_series", "POST /demand/{id}/series"),
    ("Performance prediction", "scale.predict_performance", "GET /drafts/{id}/predict"),
    ("Content calendar / planner", "scale.content_calendar", "GET /creators/{id}/calendar"),
    ("Thumbnail & visual intelligence", "scale.thumbnail_concepts", "(via scale)"),
    ("Canonical answers (cross-platform)", "canonical.group_variants", "POST/GET /creators/{id}/canonical"),
    ("Versioned claim layer", "claims.extract_claims / detect_contradictions", "GET /claims · /claims/{id}/approve"),
])
cat_engage = cat("§05 Engagement & inbox", [
    ("Intent-labelled queue", "inbox.labelled_inbox", "GET /creators/{id}/inbox"),
    ("Bounded clarifying question", "inbox.bounded_clarify", "(retrieval-side)"),
    ("No-answer waitlist", "inbox.add_to_waitlist", "(fan-side)"),
    ("Saved playbooks", "inbox.match_playbook", "POST/GET /creators/{id}/playbooks"),
    ("Reply assistant", "engagement.draft_reply", "(DM job draft)"),
    ("Agentic DM (approval mode)", "engagement.handle_dm_followup / bulk_approve", "POST /creators/{id}/dm/bulk-approve"),
    ("Community delegation", "engagement.delegation_candidate", "(DM dispatch)"),
    ("‘Not now, but…’ queue", "engagement.defer_question / due_deferrals", "POST /defer · GET /deferrals/due"),
    ("Loop-Closer", "engagement.close_loop", "POST /demand/{id}/close-loop"),
])
cat_money = cat("§06 Monetization & revenue", [
    ("Auto-affiliate injection", "monetization.inject_affiliate / with_utm", "(caption-time)"),
    ("Offer-aware CTAs", "monetization.offer_cta", "(answers/recs)"),
    ("Affiliate optimisation", "revenue.affiliate_optimisation", "GET /creators/{id}/affiliate-optimisation"),
    ("Sponsor matchmaker & pitch", "revenue.sponsor_report", "GET /creators/{id}/sponsor-report"),
    ("Dynamic pricing & offer insights", "scale.pricing_insights", "GET /creators/{id}/pricing-insights"),
    ("Revenue forecasting & goals", "scale.revenue_forecast", "GET /creators/{id}/revenue-forecast"),
])
cat_brand = cat("§07 Brand & reputation · §08 Growth & strategy · §09 Operations", [
    ("Crisis / sentiment-shift detection", "brand.detect_crisis", "GET /creators/{id}/crisis-check"),
    ("Voice consistency scoring", "brand.voice_consistency_score", "POST /creators/{id}/voice-score"),
    ("Plagiarism monitoring (opt-in)", "growth.plagiarism_scan", "POST /creators/{id}/plagiarism-scan"),
    ("Content strategy advisor", "intelligence.strategy_advisor", "POST /creators/{id}/strategy"),
    ("Peer benchmarking (opt-in)", "growth.peer_benchmark", "GET /creators/{id}/benchmark"),
    ("Education & skill planning", "scale.education_plan", "GET /creators/{id}/education-plan"),
    ("Task / project export", "growth.export_task", "POST /demand/{id}/export-task"),
    ("Customer CRM", "crm.customer_profiles / lifecycle_segments", "GET /creators/{id}/customers · /lifecycle"),
    ("Team & role-based access", "team.add_member / has_capability / audit", "POST/GET /creators/{id}/team"),
    ("Public API & dev ecosystem", "team.mint_api_key + public_api", "POST /api-keys · GET /v1/public/*"),
    ("Causal: interventions / lift / CIs", "causal.create_intervention / holdout_lift", "GET /interventions · /lift"),
])

queues = """
<table><tr><th>Lane</th><th>What runs</th><th>Cadence</th></tr>
<tr><td><b>ingest</b></td><td>Backfills, media download, transcribe / OCR / enrich / index</td><td>On connect &amp; on demand</td></tr>
<tr><td><b>realtime</b></td><td>Webhook comment → intent → DM job; approved-DM dispatch (advisory-locked)</td><td>Webhook + every tick</td></tr>
<tr><td><b>periodic</b></td><td>Demand Radar build, weekly digest, incremental + native sync, token refresh</td><td>Scheduled</td></tr></table>
<div class="note"><b>scheduler.tick()</b> (~5 min): DM dispatch every tick · hourly incremental + native sync ·
weekly radar + digest (Mon 07:00 UTC) · daily OAuth token refresh (06:00 UTC).</div>
"""

crosscut = """
<table><tr><th>Concern</th><th>How it’s enforced</th></tr>
<tr><td><b>Security</b></td><td>Creator-scoped queries; OAuth tokens encrypted at rest (EncryptedString); fail-closed boot on insecure secrets; webhook signature verified (fail-closed in prod); prompt-injection hardening (wrap_untrusted + GUARD) on agent prompts; DM dispatch advisory lock.</td></tr>
<tr><td><b>Privacy / GDPR</b></td><td>Per-creator pseudonyms (dedicated secret); PII redaction before storage; export + erase (incl. erase-by-pseudonym); opt-in row-level security.</td></tr>
<tr><td><b>Cost</b></td><td>Per-creator AI metering with op tags; per-plan monthly cost cap; separate anonymous-answer abuse ceiling (free card stays free).</td></tr>
<tr><td><b>Portability</b></td><td>Every AI + platform call behind an interface (offline fakes by default); Postgres + pgvector; S3; Alembic migrations 0001–0004; k8s + Render manifests.</td></tr>
<tr><td><b>Quality</b></td><td>Citation-correctness eval gate before automation; 311 backend + 9 frontend tests; five-dimension adversarial review.</td></tr></table>
"""

html = f"""<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>
<h1>Sift — Architecture &amp; Workflow Pipeline</h1>
<div class="sub">A cross-platform demand-to-outcome platform for creators · system overview and end-to-end data flow</div>

<div class="section"><h2>1 · System architecture (layered)</h2>
<div class="legend">
<span class="c-surface" style="color:#fff">Surfaces</span>
<span class="c-api" style="color:#fff">API edge</span>
<span class="c-app" style="color:#fff">Application</span>
<span class="c-worker" style="color:#fff">Workers</span>
<span class="c-data" style="color:#fff">Data plane</span>
<span class="c-ext" style="color:#fff">External</span>
&nbsp; Every AI &amp; platform call goes through a swappable interface.
</div>
{stack}
</div>

<div class="section"><h2>2 · The product loop</h2>
<p style="font-size:8.6pt;color:#44525a;margin:0 0 4px">The company is one cycle — v1 <i>listens &amp; serves</i>; the agent layer <i>advises, executes, closes</i>. The loop closes when the original asker hears back, seeding the next question.</p>
{loop}
</div>

<div class="pagebreak"></div>
<div class="section"><h2>3 · The complete workflow pipeline (end to end)</h2>
<p style="font-size:8.6pt;color:#44525a;margin:0 0 6px">From a creator connecting an account to a closed, measured demand loop. Tags show the lane / surface each stage runs on.</p>
{pipeline}
</div>

<div class="pagebreak"></div>
<h2>4 · Agent layer — feature architecture</h2>
<p style="font-size:8.6pt;color:#44525a;margin:0 0 6px"><code>cci_agent</code> is the "chief of staff" — <b>18 modules, ~70 endpoints across seven domains</b>, all implemented and exposed via the <code>/agent</code> router. Every chip below is a working feature.</p>
<div class="legend"><span class="c-dom" style="color:#fff">Agent domains</span> &nbsp; * = scaffolded (opt-in gate + privacy guarantee + response shape; placeholder aggregates until a multi-creator panel exists).</div>
{agent_domains}

<div class="pagebreak"></div>
<h3 style="margin-top:0">Feature catalog — every agent capability → module → endpoint</h3>
{cat_foundations}{cat_audience}
<div class="pagebreak"></div>
{cat_content}{cat_engage}
<div class="pagebreak"></div>
{cat_money}{cat_brand}

<div class="pagebreak"></div>
<div class="section"><h2>5 · Key sub-pipelines</h2>
<h3>A · Ingestion — content becomes searchable</h3>
{ingest_flow}
<h3>B · Retrieval &amp; answer — one hybrid layer serves search, the answer card, and DM intent</h3>
{retrieval_flow}
<h3>C · Demand → action loop — the monetizable asset</h3>
{demand_flow}
</div>

<div class="section"><h2>6 · Jobs, queues &amp; scheduler</h2>
{queues}
</div>

<div class="section"><h2>7 · Cross-cutting concerns</h2>
{crosscut}
</div>
</body></html>"""

HTML(string=html).write_pdf("/home/user/octo/docs/ARCHITECTURE.pdf")
print("wrote docs/ARCHITECTURE.pdf")
