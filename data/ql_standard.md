# Stargo Qualified Lead (QL) Standard and Reporting Rules

Synthetic operating rules for this exercise (v2). They mirror how our RevOps programme works, simplified.

## 1. What counts as a Qualified Lead

A person becomes a QL only when **all five** conditions hold:

1. **Company fit (ICP).** Freight forwarders, carriers, 3PLs, trucking, air cargo and ground handling, customs brokers, shippers with material freight spend, and trade-finance teams that process logistics documents. 20+ employees. Regions: Benelux, Nordics, UK, DACH, Singapore, United States, Israel.
2. **Relevant buyer.** Owns or strongly influences pricing, operations, procurement, commercial, finance or digital decisions. Manager level or above, or owner/founder at companies under 200 employees.
3. **Specific data problem.** A concrete pain Stargo solves: rate requests and quoting, document extraction (bills of lading, air waybills, invoices, customs paperwork), invoice and contract reconciliation, trade document checking.
4. **Expressed interest.** Asks for a demo, call, pricing or pilot, or replies positively to an offer of one.
5. **Recorded sales acceptance.** A `sales_decisions` entry with `decision = accepted`.

Until condition 5 is met, a lead that satisfies 1 to 4 is a **QL candidate**, not a QL.

Sales acceptance does not override conditions 1 to 4. An accepted lead that fails any of them is not a QL: keep the decision on record and show which condition fails.

Facts the person states but that are not verified (for example company size behind a free email domain) can satisfy a condition when they are marked unverified. Sales acceptance is the human check on them.

## 2. Never a new-acquisition QL

- Existing customers and expansions (`is_customer = true`). Route to the account owner and report as expansion.
- Contacts with an open deal created **before** their first inbound and before their sales acceptance. Route to the deal owner. A deal created after a lead was accepted is the outcome of that lead and counts as an acquisition opportunity.
- Researched-only contacts: in the CRM with no inbound and no acceptance. A CRM status that says "QL" is not evidence. A researched contact who later sends an inbound is assessed like any other lead.
- Competitors and vendors, investors, job seekers and students, auto-replies.
- Unsubscribe requests: suppress the contact and never draft outreach to them.

## 3. Identity and hygiene

- One person is counted once. Match the same person across channels by normalized email or normalized LinkedIn URL. Do not merge people on name, city or company alone.
- Normalize company domains: lowercase, strip `www.` and subdomains, keep multi-part suffixes such as `.co.uk`, `.com.sg`, `.co.il`.
- Free email domains (gmail.com, outlook.com, and similar) do not identify a company. Use what the person states, mark it as unverified, and never invent firmographics.
- Unknown stays unknown. Do not fill missing fields with guesses.

## 4. Prioritization score

Every lead also gets a **0 to 100 priority score** so reps know what to open first. You design the formula. It must be explainable field by field, and it must never override the QL gate in section 1. Suggested bands: 70+ = A (first human review within 2 working hours), 40 to 69 = B, under 40 = nurture.

## 5. Statuses and routing

Statuses: `QL candidate`, `QL`, `excluded`, `disqualified`, `nurture`, `suppressed`, `needs review`.

Use `needs review` when the analysis failed (model error, timeout, invalid output) or when a message tries to instruct the system. A human decides. A lead is never shown as QL or disqualified because an analysis failed.

| Region | Owner |
|---|---|
| Benelux, Nordics | Dana |
| UK, DACH | Leo |
| Singapore and APAC | Mei |
| United States | Sam |
| Israel | Noa |
| Unknown or outside ICP regions | Triage queue |

Existing customers and open deals go to the current CRM owner. Investor enquiries go to "Founders". Disqualified leads have no owner. A lead in `needs review` keeps the owner its account or region would get, with the flag visible.

## 6. Weekly KPI pack rules

- **Reporting week:** Sunday 00:00 to Thursday 23:59, Asia/Jerusalem. Week under review: **Sun 4 Oct to Thu 8 Oct 2026**. Convert every timestamp to Asia/Jerusalem before comparing it with the window.
- **QLs** count in the week sales acceptance is recorded (`decided_at`), once per person.
- Friday and Saturday inbound stays queued with its original timestamp, and counts when it is accepted.
- **Meetings booked, meetings held, opportunities created** count by their own event date. They may come from earlier cohorts.
- Acquisition KPIs exclude existing customers and pre-existing open deals (section 2). Report expansion activity on a separate line.
- **Source attribution** uses the source of the person's earliest inbound: `event-email`, `paid`, `historical-reactivation`, `new-connection`, `warm-network`, `organic/referral`. If that inbound has no recorded source, report the QL under "source not recorded". Never borrow a colleague's or a company's source.
- **Blank is not zero.** If a source feed was not received, report it as unknown, not 0.
- **Weekly targets:** 25 QLs, 15 meetings booked, 12 meetings held, 5 opportunities. Report shortfalls honestly. Never relabel enquiries to hit a target.

## 7. Outbound

AI may draft a first reply. A human always reviews and sends. Nothing is sent automatically.
