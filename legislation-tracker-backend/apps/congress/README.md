# `congress` app

## Purpose

This app is the **people and votes** layer: members of Congress (**Representatives**), complete Congress-scoped **roll-call votes** (including non-bill votes), each member’s position, official committee memberships, and bill sponsorship/co-sponsorship relationships.

## How it works (plain English + tech)

- Data lives in **PostgreSQL** and is defined with **Django ORM**.
- **Representative** is keyed by **bioguide ID** (the standard Congress identifier from Congress.gov), plus name, chamber, party, state, and district.
- **Vote** is one roll call on a **Bill** (chamber + roll number + date + result + tallies).
- **VoteRecord** is one row per member per vote (representative + normalized and raw position).
- **CommitteeRosterSnapshot** records the last accepted full official House or Senate roster. A roster is replaced atomically only after freshness, identity, coverage, and representative checks pass.

Ingestion pulls bill relationships and House roll calls from **Congress.gov API v3**, Senate roll calls from Senate.gov XML, and current committee assignments from the official House Clerk and Senate XML feeds. Roll calls, member details, and bill relationships use durable work items; missing exact Bioguide identities block work until the canonical member is synced. The **DRF** read-only API (`/api/representatives/`) exposes representative lists, insight summaries, sponsorship histories, committee memberships, and two-member comparisons.

## What you’ll find here

| Model | Role |
|--------|------|
| `Representative` | Member of Congress. |
| `Vote` | A Congress-scoped roll-call vote, optionally linked to a bill. |
| `VoteRecord` | How one member voted on that roll call. |
| `Committee` / `CommitteeMembership` | Canonical committee identities and current-Congress assignments. |
| `CommitteeRosterSnapshot` | The accepted source version used for one chamber's roster replacement. |
| `BillCommittee` / `BillCosponsor` | Official bill relationship history. |

## Who should read this

Anyone working on **sponsors**, **vote displays**, or **member filters** in the UI.
