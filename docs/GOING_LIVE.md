# Going Live: What to Do to Run This App for Real

Right now the app runs on a test computer with practice data and a free offline
stand-in for the "AI brains." This document is the plain-language checklist for
taking it from prototype to a real creator with real fans.

Steps are in rough order. Each is tagged:
- 👤 **You** can do it yourself
- 🛠️ **Developer** needed
- ⚖️ **Legal/admin**

There's a one-paragraph **shortcut** at the bottom if you just want to see it
working for real as fast as possible.

---

## 1. Get permission from Instagram  👤 (with some developer help)

The app can only read posts and comments through Instagram's official doors.

- [ ] Create a free **Meta developer account** at developers.facebook.com.
- [ ] Register the app and set up **Instagram Login** (no Facebook Page needed).
- [ ] Connect **one Instagram account you own or control** first. This is
      "Standard Access" — it works immediately, no review required, and is enough
      to prove the whole product end to end.
- [ ] Submit **App Review (Advanced Access)** to connect *other* creators later.
      Request only the permissions the demo visibly uses (asking for extras is a
      common rejection reason). This can take days to weeks — **start it early**,
      in parallel with everything else.

> Never scrape Instagram. Meta detects and blocks it and has taken legal action.
> Official API only.

**Permissions the app uses:** `instagram_business_basic`,
`instagram_manage_comments`, `instagram_manage_messages`.

---

## 2. Turn on the real "AI brains"  🛠️ (costs money)

Today the AI is a free offline placeholder so the app runs with zero keys. For
real quality, plug in paid providers (it's just pasting keys into a settings
file — see `.env.example`):

- [ ] An **AI model** for answers, content ideas, and tagging (e.g. Anthropic or
      OpenAI). Set the latest capable model.
- [ ] An **embeddings** service that powers the search.
- [ ] **Transcription** (spoken words in videos) and **OCR** (text on screen).
      These can run locally for near-zero cost, or via a paid service.

**Rough cost:** tens of dollars to process one creator's entire back catalogue
once, then cents per search after that. All providers are swappable by changing
settings — you are never locked into one vendor.

---

## 3. Put it on the internet  🛠️

Move it off the test computer onto a real server.

- [ ] Deploy to a **cloud server** (any provider — the app ships as standard
      containers via `infra/docker-compose.yml`).
- [ ] Stand up a real **database** (PostgreSQL) and **file storage** (for
      downloaded media).
- [ ] Buy a **domain name** (your `yourapp.com`) and serve the search page over
      HTTPS. Each creator lives at `yourapp.com/<their-handle>`.
- [ ] Point Instagram's **webhook** at the live server so comment replies work.

**Effort:** a few days for someone who has done a deployment before.

---

## 4. Cover the legal basics  ⚖️

You're storing what fans search and ask, so this is required (and Meta asks for
it during App Review).

- [ ] Publish a **privacy policy**.
- [ ] Provide a **deletion path** (a way for people to have their data removed).
- [ ] The app already helps: audience questions are stored without names
      (pseudonymous), and deleting a creator's post removes it from search.
- [ ] Consider basic **terms of service** for creators.

---

## 5. Fill the two small product gaps  🛠️ (small jobs, don't block a pilot)

- [ ] **One-click creator sign-up.** Today an operator connects each account by
      hand via a command-line tool. Fine for the first creator; needed before
      scaling.
- [ ] **Email the weekly report.** Today the "what to post next" digest prints to
      a log instead of being emailed. Easy to add.

Neither blocks a first pilot — you can onboard one creator manually and read
their report yourself.

---

## 6. Run a real pilot  👤

- [ ] Pick **one creator** who fits: 100+ evergreen posts, an audience that asks
      lots of repeat questions, and at least one thing to sell (course, product,
      affiliate).
- [ ] Load their content, then have them spend **~2 hours labelling 40–60 real
      questions** (pulled from their existing comments) so the app's built-in
      "exam" can confirm it finds the right posts.
- [ ] **Keep auto-DM in approve-first mode** — every reply gets a human OK —
      until the exam passes its accuracy and citation checks.
- [ ] Have the creator put the **search link in their bio**, add a permanent
      "Search" Highlight, and actually tell their audience to use it.

**The two questions the pilot answers:**
1. Can a real fan find the right old post **faster than through Instagram**?
2. Does the creator **act on the weekly report** without being talked into it?

---

## The shortcut (fastest path to "it works for real")

To see a real fan searching a real creator's archive, you mainly need
**steps 1, 2, and 3**: your own Instagram account connected, paid AI keys pasted
in, and the app running on a cloud server with a domain. Everything else —
App Review for other creators, one-click sign-up, email, billing — is about
*scaling* afterward, not proving it works.

---

## What's already done (so you know what you're NOT paying to build)

- Search over captions, spoken words, and on-screen text, with cited answers
- The fan-facing search page (light/dark, mobile-first)
- Comment → drafted reply + DM, with human approval and Instagram's safety limits
- The weekly "what to post next" report (Demand Radar)
- Affiliate "buy" buttons with click tracking
- The built-in accuracy "exam" that gates the auto-DM feature
- Swappable AI providers, privacy-safe storage, and a full test suite

See `README.md` for how to run it locally and `docs/IMPLEMENTATION_PLAN.md` for
the full technical plan.
