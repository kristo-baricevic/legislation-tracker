import type { ReactNode } from "react";
import styles from "./reader-guide.module.css";

type PolicyCard = {
  number: string;
  title: string;
  summary: string;
  money: string;
  source: string;
};

type FundingItem = {
  program: string;
  amount: string;
  description: string;
  period: string;
  source: string;
};

const policyCards: PolicyCard[] = [
  {
    number: "01",
    title: "Taxes and family benefits",
    summary:
      "Extends and changes individual, family, and business tax rules. Some households keep lower tax rates; several deductions and credits change.",
    money: "82 related tax and funding items",
    source: "Titles VII–X",
  },
  {
    number: "02",
    title: "Health coverage and food assistance",
    summary:
      "Changes eligibility, work rules, and state financing for Medicaid and SNAP. The practical effect can vary by state and household.",
    money: "61 related funding items",
    source: "Titles I–II",
  },
  {
    number: "03",
    title: "Border and immigration enforcement",
    summary:
      "Adds funding for border barriers, detention capacity, personnel, and immigration enforcement operations.",
    money: "94 related funding items",
    source: "Title X",
  },
  {
    number: "04",
    title: "Energy and transportation",
    summary:
      "Narrows or ends selected clean-energy incentives and changes rules that affect energy projects, vehicles, and fuel production.",
    money: "37 related tax and funding items",
    source: "Title VII",
  },
];

const fundingItems: FundingItem[] = [
  {
    program: "Border barriers and access roads",
    amount: "$46.5B",
    description: "New funding to build and improve physical barriers, roads, and related border infrastructure.",
    period: "Available through FY 2029",
    source: "Title X · § 100013",
  },
  {
    program: "Immigration detention capacity",
    amount: "$45B",
    description: "New funding for detention facilities, staffing, transport, and related operations.",
    period: "Available through FY 2029",
    source: "Title X · § 100012",
  },
  {
    program: "Rural health transformation fund",
    amount: "$50B",
    description: "Funding for state programs intended to support rural hospitals and health-care access.",
    period: "FY 2026–2030",
    source: "Title I · § 71401",
  },
  {
    program: "Defense readiness",
    amount: "$25B",
    description: "Additional funding for military readiness, equipment, and selected defense programs.",
    period: "As specified by program",
    source: "Title V · sample provision",
  },
];

function Arrow() {
  return <span aria-hidden="true" className={styles.arrow}>→</span>;
}

function SectionHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className={styles.sectionHeading}>
      <div>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      {children}
    </div>
  );
}

export default function ReaderGuideMockupPage() {
  return (
    <main className={styles.page}>
      <div className={styles.notice}>
        <span>Prototype</span>
        Static mock data only — this page does not call the API or change stored bill data.
      </div>

      <article className={styles.sheet}>
        <header className={styles.hero}>
          <div className={styles.kickerRow}>
            <p className={styles.kicker}>Reader&apos;s guide</p>
            <p className={styles.billMeta}>H.R. 1 · 119th Congress · Public law</p>
          </div>
          <div className={styles.heroGrid}>
            <div>
              <h1>The One Big Beautiful Bill Act</h1>
              <p className={styles.deck}>
                A broad tax-and-spending law that changes taxes, health coverage and food-assistance rules,
                immigration enforcement, and energy policy.
              </p>
              <p className={styles.disclosure}>
                This is a guide to the bill&apos;s major changes. Every item below links to the relevant bill text.
              </p>
            </div>
            <aside className={styles.readingNote}>
              <span className={styles.noteLabel}>Start here</span>
              <strong>About a 5-minute read</strong>
              <span>Then explore the money, votes, or exact legal text at your own pace.</span>
            </aside>
          </div>
          <nav className={styles.jumpNav} aria-label="Guide sections">
            <a href="#changes">What changes</a>
            <a href="#money">Where the money goes</a>
            <a href="#votes">Votes</a>
            <a href="#source">Source text</a>
          </nav>
        </header>

        <section id="changes" className={styles.section}>
          <SectionHeading eyebrow="In plain English" title="What this bill changes" />
          <p className={styles.sectionIntro}>
            The law combines several large policy changes. These are the areas a reader is most likely to notice;
            each card leads to the detailed provisions underneath it.
          </p>
          <div className={styles.policyGrid}>
            {policyCards.map((card) => (
              <article key={card.number} className={styles.policyCard}>
                <div className={styles.cardTopline}>
                  <span className={styles.cardNumber}>{card.number}</span>
                  <span>{card.source}</span>
                </div>
                <h3>{card.title}</h3>
                <p>{card.summary}</p>
                <button type="button" className={styles.textButton}>
                  <span>{card.money}</span> <Arrow />
                </button>
              </article>
            ))}
          </div>
          <button type="button" className={styles.allChanges}>
            See all policy areas and provisions <Arrow />
          </button>
        </section>

        <section id="money" className={`${styles.section} ${styles.moneySection}`}>
          <SectionHeading eyebrow="Money, in context" title="Where the money goes">
            <span className={styles.itemCount}>530 budget items in this bill</span>
          </SectionHeading>
          <p className={styles.sectionIntro}>
            Each row says what the money is for, not just that it exists. Amounts stay separate when the law does
            not support one honest total.
          </p>
          <div className={styles.fundingTable} role="table" aria-label="Sample funding items">
            <div className={`${styles.fundingRow} ${styles.fundingHeader}`} role="row">
              <span role="columnheader">Program or purpose</span>
              <span role="columnheader">Amount</span>
              <span role="columnheader">When</span>
              <span role="columnheader">Bill text</span>
            </div>
            {fundingItems.map((item) => (
              <div key={item.program} className={styles.fundingRow} role="row">
                <div role="cell">
                  <strong>{item.program}</strong>
                  <p>{item.description}</p>
                </div>
                <strong role="cell" className={styles.amount}>{item.amount}</strong>
                <span role="cell" className={styles.period}>{item.period}</span>
                <button type="button" role="cell" className={styles.sourceLink}>{item.source} <Arrow /></button>
              </div>
            ))}
          </div>
          <div className={styles.moneyFooter}>
            <span>Showing 4 sample items in this mockup.</span>
            <button type="button" className={styles.primaryButton}>Browse all 530 budget items <Arrow /></button>
          </div>
        </section>

        <div className={styles.lowerGrid}>
          <section id="votes" className={`${styles.section} ${styles.compactSection}`}>
            <SectionHeading eyebrow="How Congress acted" title="Votes and path to passage" />
            <ol className={styles.timeline}>
              <li>
                <span>May 22</span>
                <div><strong>House passed the bill</strong><small>215–214</small></div>
              </li>
              <li>
                <span>July 1</span>
                <div><strong>Senate passed an amended version</strong><small>51–50 · Vice President broke the tie</small></div>
              </li>
              <li>
                <span>July 3</span>
                <div><strong>House agreed to the Senate changes</strong><small>218–214</small></div>
              </li>
            </ol>
            <button type="button" className={styles.textButton}>See every vote and who voted <Arrow /></button>
          </section>

          <section id="source" className={`${styles.section} ${styles.compactSection} ${styles.sourceSection}`}>
            <SectionHeading eyebrow="Check the source" title="Read the legal text" />
            <p>
              Every explanation and money item has a source link. Open the exact passage when you want the legal
              wording, surrounding context, or a downloadable official document.
            </p>
            <div className={styles.sourceExample}>
              <span>Example source</span>
              <strong>Title X · Section 100013</strong>
              <button type="button">Open passage <Arrow /></button>
            </div>
          </section>
        </div>

        <footer className={styles.footer}>
          <span>Legislation Tracker</span>
          <span>Plain-language guide · Exact source text one click away</span>
        </footer>
      </article>
    </main>
  );
}
