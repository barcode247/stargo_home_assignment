# Stargo RevOps: GTM signal pipeline

Turns raw GTM signals into qualified, routed leads and an honest weekly KPI pack.

Parts 1 to 6 are built: ingest and hygiene, the two chained agents, the weekly KPI pack, the
AI-visibility snapshot with a grounded content brief, SQLite storage, and a React UI.

## Run it

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync
uv run uvicorn stargo.api:build_default_app --factory --port 8000
```

Open http://localhost:8000. The first run seeds `backend/stargo.db` from `data/`.

**No key needed.** Without `.env` the header shows "rules-only (no LLM key)": Agent A is a
keyword extractor (English, Dutch, German, Hebrew; other languages go to `needs review`),
reply drafts and content briefs come from fixed templates. To use a free-tier model, copy
`.env.example` to `.env` and set `LLM_PROVIDER` (`groq`, `gemini` or `ollama`) and
`LLM_API_KEY`. The only network calls the backend makes are to that one endpoint.

Tested live with Gemini (`gemini-flash-lite-latest`, the default for `gemini`). Two things to
know: set `LLM_MIN_INTERVAL_SECONDS=6.5` to stay under the free tier's limit of about 10
requests a minute, and the first start on an empty database sends all 21 seed messages through
the model, so it takes about 2½ minutes before the server answers. `gemini-2.5-flash` is
no longer offered to new keys, which is why the default is the `-latest` alias.

Other commands (from `backend/`):

```bash
uv run pytest -q                                           # offline; models are faked
uv run ruff check src tests
uv run python -m stargo.cli eval                           # score on the labelled messages
uv run python -m stargo.cli kpi --week 2026-10-04 --note ../docs/cro_note.md --out ../KPI_PACK.md
uv run python -m stargo.cli reset                          # wipe the local database
```

For UI development, run `npm run dev` in `frontend/` (port 5173, proxies `/api` to 8000).

## Layout

```
backend/src/stargo/
  domain/      normalize.py (email, LinkedIn, domain, country), identity.py (person merge),
               accounts.py (company roll-up), models.py, qualification.py (Agent B schema)
  ingest/      validation.py: every record is validated; bad input becomes readable reasons
  agents/      schemas.py (Agent A contract + validator), rules_extractor.py (no-key Agent A),
               llm_extractor.py (LLM Agent A), injection.py (deterministic injection check),
               reply_drafter.py (Agent B reply draft, template or LLM, validated)
  rules/       qualify.py (QL gate, exclusions, status), buyer.py, routing.py, scoring.py
  kpi/         window.py (Asia/Jerusalem week), pack.py (counting + drill-down), render.py
  visibility/  analysis.py (mentions, citations, look-alikes, gap score), brief.py (GEO brief)
  llm/         client.py (OpenAI-compatible client: Groq, Gemini, Ollama)
  storage/     db.py (SQLite, JSON columns)
  pipeline.py  one path for seed and pasted messages
  api.py       FastAPI, thin
frontend/src/  App.tsx (hash routes), api.ts (typed client), views/ (queue, detail, paste,
               KPI, visibility), styles.css
```

## Styling

Plain CSS with custom properties in one file. The UI is five small views; a component
library or Tailwind would add a build dependency for little gain. Tables turn into cards
under 640 px, which keeps the app readable at 390 px.

## Deterministic vs LLM

| Step | Who | Why |
|---|---|---|
| Validation, normalization, identity | code | must be exact and repeatable |
| Agent A: language, intent, role, problem, stated facts, quotes | LLM (rules fallback) | reading free text in any language is what models are good at |
| Agent A output validation | code | schema + every evidence quote must appear verbatim in the message |
| Injection detection | code | a fooled model must not be able to clear its own flag |
| Agent B: conditions 1-5, exclusions, status, owner, score | code | the QL gate must be auditable; message text never changes rules |
| Agent B: rationale | code | the rationale is built from the same evidence the gate used |
| Agent B: first-reply draft | LLM (template fallback) | wording only; input is Agent A's validated fields, never the raw message; output validated (no links, addresses, figures or hype); a human approves and sends by hand |
| Visibility: mentions, citations, look-alikes, gap score | code | must be reproducible and explainable |
| Visibility: content brief | LLM (template fallback) | every claim must cite BC/PP ids; code blocks unsupported claims |

Any extractor failure (exception, timeout, unreachable host, bad key, bad JSON, schema miss,
invented quote, unsupported language in rules mode) stores a `failed` result and the lead
shows as `needs review`, keeping the owner its region or account would get, with the reason
on the lead ("model call failed: model endpoint returned HTTP 400"). "Retry analysis" in the
lead view reruns one lead; "Retry failed analyses" on the queue reruns all of them after the
settings are fixed. A failed draft or brief falls back to the template with a visible note.

A circuit breaker stops a dead or hanging model from stalling the app: after 3 failures in a
row the client stops calling for 60 seconds and fails at once. QA results on an empty database
(startup time / time to analyse a pasted message, every lead ending in `needs review`):
invalid key 4 s / 0.2 s, unreachable host 7 s / 0.2 s, HTML instead of JSON 2 s / 0.2 s,
prose instead of JSON 2 s / 0.2 s, model that hangs 32 s / 0.2 s (three 10-second timeouts,
then the breaker opens).

Prompt-injection defences, in order: the detector in code flags the lead for review; the
message is passed to the model fenced as data with instructions to ignore orders in it; the
model's output must pass the schema and quote verbatim; and the output can only fill
extraction fields, never the status, owner or score.

Drafts are never sent. Approving one records who approved it and when; the API returns
`"sent": false`. Approval is refused if the lead has since become ineligible (for example,
an unsubscribe arrived after drafting).

## Status precedence

1. Any unsubscribe → `suppressed`, no owner, no outreach.
2. Any failed analysis, injection attempt or identity conflict → `needs review`.
3. Exclusions → `excluded`: existing customer (account-level, reported as expansion),
   pre-existing open deal, competitor/vendor, investor, job seeker, auto-reply only.
4. Latest sales decision is a rejection → `disqualified`.
5. Condition 1 or 2 fails → `disqualified` (accepted leads keep the decision and show the failing
   condition).
6. Condition 3 or 4 fails → `nurture`.
7. Any of conditions 1-4 unknown → `needs review` with the missing facts listed.
8. All four met → `QL` if the latest decision is an acceptance, else `QL candidate`.

## Priority score (0-100)

See `rules/scoring.py`. Intent 30, data problem 20, buyer 20, company fit 20, engagement 10.
Stated-but-unverified facts earn 75%. Bands: A ≥70, B 40-69, nurture <40. The score orders the
queue and never changes the status.

## KPI counting

- Week = Sun 00:00 to Fri 00:00 (exclusive) Asia/Jerusalem; every timestamp is converted first.
- The week is replayed: each person is re-qualified using only the messages and decisions on
  record before the week ended. A decline or unsubscribe next week changes today's status but
  not last week's count, and an acceptance dated before the person's first message cannot count.
- A QL counts in the week of its first acceptance, once per person, if the latest decision as of
  the week's end is still an acceptance and conditions 1-4 hold with no exclusion or review flag.
- Expressed interest (condition 4) stays met once expressed; a later decline is shown on the
  lead, not used to erase the earlier interest.
- Meetings and opportunities count by event date; customers go to the expansion lines,
  pre-existing deals are listed as not counted.
- Source = the person's earliest inbound. An unreceived feed is `unknown`, not 0.
- Every number lists the decision, event and message ids behind it.

## Assumptions

- A message whose email and LinkedIn URL belong to two different established people (each with
  a CRM record or a sales decision) is rejected with a reason rather than merging them. Found
  in QA: one such paste merged Anouk and Pieter and cut the week's QLs from 6 to 4. A message
  that links a LinkedIn-only lead to a known email is still merged, as the standard intends.
- Customer and competitor status are account-level (by normalized domain); open deals are
  contact-level, as in the CRM export.
- Deal dates are day-precision: a deal created the same Israel-time day as the first inbound or
  acceptance is treated as pre-existing (conservative for acquisition numbers).
- Shippers count as ICP; "material freight spend" is not in the data, so it is not checked.
- A naive pasted timestamp is read as Israel time.
- A contact with an acceptance but no inbound on record (Felix Wagner) cannot prove conditions 3-4
  and shows as `needs review`; his meetings and opportunity still count by event date.
- Routing table "Singapore and APAC → Mei" applies to APAC owners, but only Singapore is an
  ICP region, so other APAC leads fail condition 1.
- A known country outside every routing region (Brazil) fails condition 1 and routes to
  Triage. An unknown country stays unknown; the app never infers a country from a domain.
- A stated software vendor is excluded as a vendor even when not in the CRM.

## AI visibility (part 4)

Per answer: Stargo counts as mentioned only when the sentence is about the real company. An
answer about a "StarGo" travel app, or one calling Stargo a carrier (ruled out by BC-5), is
flagged and scores below an absent answer, because it misleads buyers. A citation counts as
owned only when its host is `stargo.co` or a subdomain; `stargo-shipping.com` is flagged as a
look-alike.

Gap score (0-100) = 100 x (priority / 3) x product_fit x absence x (0.5 + 0.5 x
competitor_share). Full definition in `visibility/analysis.py` and in the UI. Product fit
halves prompts that no BC-3 product answers (rate benchmarking for shippers), so we don't
write content we can't honestly back. Top gap: P6 "alternatives to Laneframe for freight
pricing": absent on all three engines while all four competitors are named.

The brief validator checks the BC-7 contract (40-60 word answer, 3-5 sections, 3-5 FAQ, a
schema.org type) and blocks claims with no or unknown source ids, figures not in the cited
source, competitor names outside the title and FAQ questions, or hype words.

## Eval set (bonus)

`data/eval/` holds hand-labelled messages that are not in the seed data: non-English (German,
Dutch, Hebrew, French, Japanese), unusual auto-replies and unsubscribes, vendors, investors,
students, injection attempts, small and out-of-region companies, junior roles, existing
customers and open deals. Each case runs as a new inbound on a fresh seeded database and is
graded as correct, a safe deferral (`needs review` where the label is something else), or an
unsafe error (any other wrong status). `uv run python -m stargo.cli eval` prints the report,
and `tests/test_eval.py` fails on any unsafe error.

How the numbers moved, rules-only mode:

| Set | Run | Status correct | Safe deferrals | Unsafe |
|---|---|---:|---:|---:|
| `labelled_messages.json` (25) | before fixes | 15 | 6 | 4 |
| `labelled_messages.json` (25) | after fixes | 25 | 0 | 0 |
| `holdout_messages.json` (12) | first run, written after tuning | 6 | 3 | 3 |
| `holdout_messages.json` (12) | after fixing 2 label errors and 5 rule gaps | 12 | 0 | 0 |

The held-out first run is the honest estimate for unseen text: about half right, with a
quarter deferred to a human, in rules-only mode. Its unsafe misses were an unsubscribe phrased
"please don't contact me again" (left as a QL), a student who never said "student", and a
label of mine that was wrong. Both sets now pass, but they are tuned against, so the next
unseen message will find new gaps. The design limits the damage: outside English, a message
where the keywords find no problem or no intent goes to `needs review` instead of `nurture`.

LLM mode, Gemini `gemini-flash-lite-latest` (`uv run python -m stargo.cli eval --llm`):

| Set | Run | Status correct | Safe deferrals | Unsafe |
|---|---|---:|---:|---:|
| `labelled_messages.json` (25) | first run, prompt untouched | 24 | 0 | 1 |
| `holdout_messages.json` (12) | first run, prompt untouched | 11 | 0 | 1 |
| both | after defining three labels in the prompt | 37 | 0 | 0 |

Untuned, the model was far ahead of the rules on unseen text (35/37 against 21/37 for the
rules' first runs). Its two misses were gaps in my prompt, not in the model: it did not know
that a company selling OCR software counts as a vendor, or that the QL standard groups students
with job seekers. Live testing also caught a bug before the eval did: the model returned the
vertical as "Spedition" (German), which no ICP check recognises, so a German forwarder would
have been disqualified. The schema now only accepts a closed list of verticals.

## What I cut, and what I'd do next

- **HubSpot dry-run sync** (bonus): not built.
- **LLM mode beyond Gemini.** Live-tested with Gemini only (extraction, reply draft and
  content brief). Groq and Ollama use the same OpenAI-compatible client but were tested only
  against fakes. The automated tests never call a real model.
- **Seeding speed in LLM mode.** The first start waits for every seed message to go through
  the model. With more time: seed in the background and show progress in the UI.
- **Rules extractor depth.** It is a fallback, not a classifier: a passing "thanks for the
  quote" would read as a quoting problem, and its city list decides region for stated
  locations.
- **Auth and multi-user locking.** Out of scope per the brief; the API serialises requests
  with one lock.
