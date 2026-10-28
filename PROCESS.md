# PROCESS: AI workflow

> **What this document is.** The brief allows PROCESS.md to be "an exported Cursor or agent
> plan". This is that: an exported record of the build session, written by the coding agent
> (Claude Code, model Claude Opus 5.5) at the end of the session. It is not a first-person
> account. Quoted prompts are the candidate's own words, verbatim, and every decision listed
> under "Human decisions" was made by the candidate.
>
> **Tools:** Claude Code in the Claude desktop app for planning, coding and testing; Gemini
> `gemini-flash-lite-latest` as the app's runtime LLM.
>
> **Time spent:** 2 hours of the candidate's time (reported by the candidate). The agent's
> build, test and browser-check time is not included.

## 1. Reading the brief

**Prompt:** "what do you think?" (with the take-home pack folder open)

- The agent read the brief, `ql_standard.md`, the CRM export, the events file and the answer
  captures before writing any code.
- It listed the planted traps it found: email casing, LinkedIn URL variants, a duplicate
  acceptance, a subdomain email, a shared company domain that must not merge two people, the
  injection message IN-010, a customer, a pre-existing deal, a competitor, an investor, a
  student, an auto-reply, an unsubscribe, an invalid record, `Z` vs `+03:00` timestamps around
  the Thursday cut-off, and an unreceived feed.
- **It computed the KPI pack by hand first:** 6 QLs, 4 meetings booked (+1 expansion), 3 held,
  2 opportunities, with a source breakdown. These numbers were the acceptance test for the code
  written later.
- It recommended building the deterministic core first, keeping the LLM to extraction and
  wording, and warned that PROCESS.md and the live session need the candidate's own
  understanding.

## 2. Deterministic core

**Prompt:** "Yes, scaffold the repo and build the deterministic core first (ingest, identity
matching, QL gate, KPI pack, with tests). Pick the stack you recommended. important: - No auth,
no real CRM, email or social accounts. Do not send anything anywhere."

- **Repo choice.** The agent created a new repo (`stargo-revops`) rather than using the
  existing one. The candidate's whole Downloads folder was already a git repo full of personal
  files. The candidate asked "what git are you putting it in?" and "its in my github?"; the
  answers were "a new local repo" and "no, nothing is pushed".
- **Stack:** Python 3.11, FastAPI later, Pydantic, SQLite, pytest, ruff.
- **First run crashed** (`KeyError: 'IN-004'`). The cause was a union-find bug: people with a
  single identity key were never registered. Fixed.
- **First run then matched the hand-computed KPI pack exactly.**
- **First test run: 4 failures.**
  - Two were a bug in a test helper.
  - One was a wrong test expectation about Israel's DST change: clocks change at 02:00 on
    25 Oct, so that Sunday's midnight is still +03.
  - One was a real gap: "I am the marketing manager" was not read as a role.
- 119 tests passed.

**Prompt:** "Don't commit yet. Walk me through the QL gate and KPI code first so I understand
it."

- The agent explained the code; nothing was committed.

## 3. LLM agents, API, AI visibility, UI

**Prompt:** "dont commit yet, continue building"

- **Built:**
  - an OpenAI-compatible LLM client
  - LLM Agent A with schema and verbatim-quote validation
  - a reply drafter with human approval (never sends)
  - the AI-visibility analysis with a gap score and a brief validator
  - the FastAPI layer
  - the React UI
- **Found while writing tests:** a test assumed the drafter never sees any message text, but
  Agent A's validated summary is part of its allowed input. The test was corrected to check the
  right thing.
- **Checked in the in-app browser:**
  - The seed queue matched the hand-computed numbers.
  - An Accept with a past date changed the week's pack, and the change survived a restart.
  - A pasted injection message went to `needs review` at a 390 px width.
  - The server log held ids only.
- **Found during browser testing:**
  - A blank message returned a raw Pydantic error instead of a readable reason. Fixed and
    tested.
  - "We quote rate requests by hand" was classified as document extraction. Fixed and tested.

## 4. Repository

- **Prompts:** "i created a repository for you https://github.com/barcode247/stargo_home_assignment",
  then "they wrote they want to see the repo so i thing it should be public".
- The agent scanned the files for secrets, checked the commit author used the GitHub noreply
  address, and pointed out that the repo was public before pushing. The candidate chose public.

## 5. Eval set (bonus)

**Prompt:** "ok continue"

- The agent wrote 25 labelled messages that are not in the seed data.
- **While labelling, it found a KPI design bug.** A later decline or unsubscribe would have
  removed a QL from a past week's count. Fix: the pack now replays each week using only records
  from before it ended. Some earlier tests had accepted a lead before their first message ever
  arrived. The replay correctly refused to count that, so those tests were rewritten.

| Run | Status correct | Unsafe errors |
|---|---:|---:|
| Rules, labelled set, before fixes | 15/25 | 4 |
| Rules, labelled set, after fixes | 25/25 | 0 |
| Rules, held-out set, first run (written after tuning, not tuned on) | 6/12 | 3 |
| Rules, held-out set, after fixing 2 label errors + 5 rule gaps | 12/12 | 0 |

- **Two of the held-out "errors" were the agent's own wrong labels** (H08, H09). They were
  corrected openly, with a note in the data file.
- The agent drafted a CRO note and flagged it as a draft for the candidate to rewrite.

## 6. API-down message

- The candidate sent a screenshot showing "TypeError: Failed to fetch". The agent had stopped
  the server, and the open tab still showed an old status badge.
- **Fix:** a clear "Cannot reach the API server" message with the start command, a badge that
  re-checks on every page change, and "Loading…" states.
- **Prompt:** "Commit and push".

## 7. Live LLM mode with Gemini

**Prompt:** "i hvae the gemini kley"

- The agent asked the candidate not to paste the key into chat. It created a git-ignored
  `.env`, opened it in the editor for the candidate to fill in, and only ever checked that the
  key was present, never its value.
- **What the live key caught:**
  - **The default model was retired.** `gemini-2.5-flash` returned 404, "no longer available
    to new users". Switched to `gemini-flash-lite-latest`.
  - **An overloaded model.** `gemini-3.8-flash` returned 503. 5xx errors now get a short retry.
  - **Rate limits.** The free tier allows about 10 requests a minute, so calls are now spaced
    out, and the eval seeds the database once instead of once per case.
  - **A qualification bug.** Gemini returned the vertical as "Spedition" (German), which would
    have disqualified a German forwarder. The vertical is now limited to a closed list.

| Run | Status correct | Unsafe errors |
|---|---:|---:|
| Gemini, untuned prompt, both sets | 35/37 | 2 |
| Gemini, after defining 3 labels in the prompt | 37/37 | 0 |

- The two misses were gaps in the prompt's definitions (a software seller is a vendor;
  students count as job seekers), not misreadings by the model.
- **Live checks in the app:**
  - A Hebrew message from a Gmail address became a QL candidate routed to Noa.
  - The reply draft and the content brief both passed their validators.
  - The server log held no message text, emails or key.
- **Prompt:** "Push it".

## Human decisions in this session (all by the candidate)

- Build the deterministic core first, with the recommended stack.
- No commits until the core had been explained.
- Publish the repo as public.
- Approve each push.
- Keep the key out of the chat.
- Submit this agent export as PROCESS.md instead of a first-person account (the brief allows
  either). The agent offered a skeleton for a first-person version; the candidate declined it.
- The CRO note in `KPI_PACK.md` was drafted by the agent and flagged for the candidate to
  rewrite.

## Verification habits the agent used

- KPI numbers computed by hand before code, then matched.
- Tests written with each part; models faked so tests run offline (187 tests at the end).
- Every UI flow exercised in a real browser, including phone width and a server restart.
- Logs checked for message text, emails and keys.
- An eval set with a held-out split, and first-run numbers reported, not just the tuned ones.
