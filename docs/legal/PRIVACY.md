# Privacy Policy

_Last updated: 2026-06-24 · Template — review with counsel before public launch._

Sift ("we") turns a creator's public content history into a searchable archive
and assistant, and helps the creator understand audience demand. This policy
explains what we process and the rights you have.

## Who the data is about

- **Creators** (account holders) who connect their Instagram/YouTube accounts.
- **Audience members** who search a creator's page or comment on their posts.

## What we process

| Data | Source | Why |
|---|---|---|
| Creator account info, OAuth tokens | Instagram/YouTube OAuth | Access the creator's own content; tokens are **encrypted at rest** |
| Posts, captions, transcripts, on-screen text | The creator's own accounts (official APIs only — we never scrape) | Build the searchable archive |
| Audience searches & questions | The public search page / comments | Answer questions and produce demand insights |
| Comments | Instagram (official API) | Demand signal and comment-to-DM |

## Audience privacy (important)

- Audience identities are **pseudonymised**: we store a salted, per-creator hash,
  never raw handles or profile identifiers.
- Audience text is **PII-redacted** before storage (emails, phone numbers, and
  long digit sequences are stripped).
- Demand insights are **aggregate** — clusters of questions, not individual profiles.
- We do **not** match the same person across platforms.

## Legal bases (GDPR)

Legitimate interest (operating the creator's archive and analytics) and contract
(providing the subscribed service). Where required, we rely on the creator's
relationship with their audience; creators are responsible for their own
audience disclosures.

## Your rights

- **Access / portability** — request a copy of your data
  (`/admin/creators/{id}/export` for creators; audience members contact the creator/us).
- **Erasure** — creators can be fully deleted (`DELETE /admin/creators/{id}`);
  audience members can be erased by pseudonym/email (`/admin/creators/{id}/erase-audience`).
- **Objection / restriction** — contact us to limit processing.

## Retention

Data is retained while the creator's account is active. On account deletion, all
dependent data is erased (cascade). Captured email leads are deleted on request.

## Sub-processors

AI providers (LLM, embeddings, transcription, OCR), cloud hosting, and object
storage. Each is accessed via a thin provider interface and bound by a data
processing agreement before production use.

## Contact

privacy@yourapp.example · a deletion/export request path is available before
public launch.
