# `congress` app

## Purpose

This app is the **people and votes** layer: members of Congress (**Representatives**), **roll-call votes** on bills, and each member’s **position** (yea/nay/etc.). It supports the sponsor line on a bill and any vote breakdowns you show in the UI or analytics.

## How it works (plain English + tech)

- Data lives in **PostgreSQL** and is defined with **Django ORM**.
- **Representative** is keyed by **bioguide ID** (the standard Congress identifier from Congress.gov), plus name, chamber, party, state, and district.
- **Vote** is one roll call on a **Bill** (chamber + roll number + date + result + tallies).
- **VoteRecord** is one row per member per vote (representative + position).

Ingestion fills these from the **Congress.gov API v3** (JSON) when processing bills and vote endpoints. The **DRF** read-only API (`/api/representatives/`) lets the **Next.js** app list representatives with optional filters (e.g. by state).

## What you’ll find here

| Model | Role |
|--------|------|
| `Representative` | Member of Congress. |
| `Vote` | A roll-call vote on a bill. |
| `VoteRecord` | How one member voted on that roll call. |

## Who should read this

Anyone working on **sponsors**, **vote displays**, or **member filters** in the UI.
