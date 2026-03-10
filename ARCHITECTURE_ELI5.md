# Legislation Tracker — Architecture Explained Simply

A short, plain-language overview of how the system works. No jargon required.

---

## What does this system do?

It **tracks bills** (laws being written in Congress), **stores the real documents**, **turns the legal text into structured “plain English” summaries**, and **records every change** so we can build things like RSS feeds and newsletters without re-reading everything every time.

---

## The big picture in one sentence

We **pull in** bills and their documents from Congress and GovInfo, **turn the text into structured data** (who gets money, what’s required, when), **write down every change as it happens**, and then **feeds and newsletters just read that list of changes** — no re-scanning or re-comparing at request time.

---

## The four layers (like a library)

Think of it like a library with a catalog, the actual books, and a summary card.

### 1. The catalog card — **Bill**

This is the **basic facts** about one bill: title, number, status (e.g. “passed the House”), who introduced it, when. Nothing fancy — just what you’d put on a card in a drawer. We don’t put our own interpretation here; we keep it as the single source of truth from the government.

**In short:** *“What bill is this, and what’s its official status?”*

---

### 2. The actual books — **BillDocument**

A bill can have **several versions** (introduced, amended, final text). Each version is a **BillDocument**: the real file (PDF/XML) we downloaded and stored. We keep them so we can **compare versions** and see what changed. One of them is marked “this is the current version” so we always know which one to show.

**In short:** *“Here’s the real document for this version of the bill.”*

---

### 3. The plain-English summary — **BillContract**

Legal text is hard to read. So we **interpret** each document and store a **structured summary**: things like “who gets funding,” “what’s required,” “what’s forbidden,” “which agencies,” “timelines,” “penalties.” That summary is a **BillContract**. It’s our **interpretation** of the bill, not the law itself.

**In short:** *“In plain terms, what does this version of the bill do?”*

---

### 4. The receipt — **EvidenceSpan**

If someone asks “where did that number come from?”, we have to be able to point back to the **exact place in the document**. For every piece of information we put in a BillContract, we store an **EvidenceSpan**: which document, which field, and the **exact slice of text** (start/end character, or page). So the system is **auditable**.

**In short:** *“This fact in the contract comes from this exact sentence in the document.”*

---

## The diary — **ChangeLog**

Instead of re-checking every bill every time someone wants “what changed?”, we **write down every important change as it happens** in one place: **ChangeLog**. Each row is one event: “status changed,” “new version,” “contract updated,” “topics updated,” “vote recorded.”

- **RSS feeds** = “Show me recent rows from this diary for bills I care about.”
- **Newsletters** = “Show me rows since I last got an email, for my topics/state.”

We **never** re-scan all bills to build a feed. We **only read the diary**. That’s why feeds stay fast and simple.

**In short:** *“Something changed; here’s what and when.”*

---

## Why we only work when something actually changed — **hashing**

We don’t want to re-download, re-parse, or re-summarize the same thing over and over. So we use **hashes**: short fingerprints of the content.

- If the **bill metadata** (title, status, etc.) hasn’t changed → we don’t re-process the bill.
- If the **document content** hasn’t changed → we don’t re-run the “plain English” step.
- If the **contract** (our summary) hasn’t changed → we don’t write a “contract updated” line in the diary.
- If the **topic tags** haven’t changed → we don’t write a “topic updated” line.

So we only do **real work** when something **meaningfully** changed. That keeps the system from being noisy and keeps newsletters from spamming people.

**In short:** *“Same fingerprint = skip the heavy work and don’t add a diary entry.”*

---

## How new bills get into the system — **the pipeline**

1. **Check the mailbox** (every few minutes)  
   We ask Congress’s API: “Any bills updated since last time?” We only get a list of bill IDs. No heavy work here.

2. **For each bill that might have changed**  
   We fetch the basic info and compare it to what we have (using the metadata hash). If nothing changed, we stop. If something changed, we update the Bill and write a line in the ChangeLog, then we:
   - **Fetch document versions** — see if there’s a new PDF/XML version.
   - **Fetch votes** — see if there’s a new roll-call vote.

3. **For each new or changed document**  
   We download it, store it (e.g. in S3), and extract text. We compare the content hash to what we had. If it’s the same, we stop. If it’s new or changed, we:
   - **Build the “plain English” contract** — our structured summary.
   - **Record where each fact came from** — EvidenceSpans.
   - **Update topic tags** and **add the bill to the “similarity” queue** for “bills like this one” later.
   - **Write a line in the ChangeLog** (e.g. “contract updated”) and mark this as the “current” version where it applies.

4. **Similarity** (in batches, not per bill)  
   We don’t compute “similar bills” immediately for every bill. We add bill IDs to a queue and process them in batches so we don’t overload the system.

**In short:** *Light check often → only heavy work when something actually changed → write changes in the diary.*

---

## Who and what we track — **Representatives, Votes, Topics**

- **Representatives** — Members of Congress (name, party, state, chamber). We use them for “who sponsored this” and “how did my rep vote?”
- **Votes** — Roll-call votes on a bill (passed/failed, yeas/nays). **VoteRecords** are each rep’s yes/no/abstain. When a new vote is stored, we write a “vote” line in the ChangeLog.
- **Topics** — Labels like “climate,” “health care.” Bills get tagged with topics (sometimes with a confidence score). Users can follow topics; feeds and newsletters filter by them.

**In short:** *We track people, their votes, and topic tags so we can filter and explain bills.*

---

## Where the data comes from — **Congress vs GovInfo**

- **Congress API** — Official **metadata**: bill list, titles, status, actions, text version list, vote references, members. We use it to know *what exists* and *what changed*.
- **GovInfo** — Official **documents**: the real PDFs and XML of the bills. We download and store these (e.g. in S3) and use them as the source for our “plain English” contracts and evidence spans.

So: **Congress** = structure and updates; **GovInfo** = the actual document files.

---

## Users and preferences

- **Users** — People who sign in (e.g. with email).
- **UserPreference** — What they care about: topics, state, chamber. We use this to build “your” RSS feed and “your” newsletter (e.g. “changes since last time we emailed you”).

---

## Why this design works

| Goal | How we get it |
|------|----------------|
| **Feeds and newsletters stay fast** | They read the ChangeLog (the diary), not every bill. |
| **No spam** | We only write a change when content actually changed (hashes). |
| **Trust and auditability** | Every fact in a contract points back to the document (EvidenceSpans). |
| **Clear roles** | Bill = official facts; BillDocument = real documents; BillContract = our summary; ChangeLog = what happened. |
| **Scaling** | Polling is cheap; heavy work is queued and only runs when needed. |

---

## One-paragraph summary

We keep **bills** (official facts), **documents** (real PDF/XML versions), and **contracts** (our plain-English summaries with **evidence** back to the text). Every time something important changes, we **append a line to the ChangeLog**. Feeds and newsletters **read that log** instead of re-scanning bills. We use **hashes** so we only do heavy work when something really changed, and we **queue** that work so the system stays responsive. That’s the architecture in plain terms.
