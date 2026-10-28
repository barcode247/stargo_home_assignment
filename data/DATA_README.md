# Data pack (v2)

All people, companies, domains, engine answers and figures are synthetic. Any resemblance to real organizations is coincidental.

| File | What it is |
|---|---|
| `crm_export.csv` | HubSpot-style contact export, 19 rows. Expect messy values (casing, domain variants, duplicate company names, stale statuses). |
| `gtm_events.json` | `inbound` (21 replies, forms and LinkedIn DMs), `sales_decisions` (11), `pipeline_events` (12 meetings and opportunities), `feed_status` per source, and `meta`. Timestamps carry their own offsets (some `Z`, some `+03:00`). |
| `ai_answers.json` | 24 synthetic answer-engine captures: 8 buyer prompts x 3 engines, with priority, cluster and cited URLs. `meta.own_domains` lists Stargo's domain. |
| `ql_standard.md` | QL definition, exclusions, statuses, hygiene, routing and KPI counting rules. This is your spec for parts 1 to 3. |
| `brand_context.md` | The only approved source of claims about Stargo. Your content brief in part 4 must be grounded in it. |

Some records are deliberately tricky. Handling them sensibly is part of the exercise. During review we will also paste a few new messages you have not seen, so build for the rules, not for these records. Document every assumption you make.
