/**
 * Popup script: coordinates content extraction and backend matching.
 */

const API_BASE = "http://localhost:8000";

const $status = document.getElementById("status");
const $error = document.getElementById("error");
const $results = document.getElementById("results");
const $topics = document.getElementById("topics");
const $topicsSection = document.getElementById("topics-section");
const $bills = document.getElementById("bills");
const $billsSection = document.getElementById("bills-section");
const $noResults = document.getElementById("no-results");

function showError(msg) {
  $status.hidden = true;
  $error.textContent = msg;
  $error.hidden = false;
}

function showResults(data) {
  $status.hidden = true;
  $results.hidden = false;

  // Topics
  if (data.topics && data.topics.length > 0) {
    $topicsSection.hidden = false;
    $topics.innerHTML = data.topics
      .map(
        (t) =>
          `<span class="topic-badge" title="${t.slug} — ${t.keyword_hits} keyword hits">
            ${t.name}
            <span class="confidence">${Math.round(t.confidence * 100)}%</span>
          </span>`
      )
      .join("");
  } else {
    $topicsSection.hidden = true;
  }

  // Bills
  if (data.bills && data.bills.length > 0) {
    $billsSection.hidden = false;
    $noResults.hidden = true;
    $bills.innerHTML = data.bills
      .map(
        (b) => `
        <a class="bill-card" href="${API_BASE.replace(':8000', ':3000')}/bills/${b.id}" target="_blank">
          <div class="bill-header">
            <span class="bill-number">${b.bill_number}</span>
            <span class="bill-score" title="Relevance score">Score: ${b.score}</span>
          </div>
          <div class="bill-title">${truncate(b.title, 120)}</div>
          <div class="bill-meta">
            ${b.sponsor_name ? `<span>${b.sponsor_name}</span>` : ""}
            ${b.topics.length > 0 ? `<span class="bill-topics">${b.topics.join(", ")}</span>` : ""}
          </div>
        </a>`
      )
      .join("");
  } else {
    $billsSection.hidden = true;
    $noResults.hidden = false;
  }
}

function truncate(str, max) {
  if (!str) return "";
  return str.length > max ? str.slice(0, max) + "…" : str;
}

function extractArticle() {
  const title = document.title || "";
  const selectors = [
    "article",
    '[role="article"]',
    '[itemtype*="Article"]',
    "main",
    "#content",
    ".post-content",
    ".article-body",
    ".story-body",
  ];

  let bodyEl = null;
  for (const sel of selectors) {
    bodyEl = document.querySelector(sel);
    if (bodyEl) break;
  }
  if (!bodyEl) bodyEl = document.body;

  const clone = bodyEl.cloneNode(true);
  const noiseSelectors = [
    "nav", "header", "footer", "aside",
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    ".sidebar", ".nav", ".menu", ".ad", ".advertisement", ".social-share",
    ".comments", ".related-articles", "script", "style", "iframe", "form",
  ];
  for (const sel of noiseSelectors) {
    clone.querySelectorAll(sel).forEach((el) => el.remove());
  }

  const rawText = (clone.textContent || "").replace(/\s+/g, " ").trim();
  return { title, text: rawText.slice(0, 10000), url: window.location.href };
}

async function run() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      showError("No active tab found.");
      return;
    }

    let result;
    try {
      [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: extractArticle,
      });
    } catch (scriptErr) {
      showError("Can't read this page (restricted by Chrome). Try a regular article.");
      return;
    }

    const article = result?.result;
    if (!article?.text) {
      showError("Couldn't extract text from this page.");
      return;
    }

    $status.textContent = "Matching against legislation…";

    let res;
    try {
      res = await fetch(`${API_BASE}/api/bills/match-article/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: article.text, url: article.url }),
      });
    } catch (fetchErr) {
      showError("Can't reach backend. Is the Django server running on localhost:8000?");
      return;
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.error || `Backend error: ${res.status}`);
      return;
    }

    const data = await res.json();
    showResults(data);
  } catch (err) {
    showError(err.message || "Unknown error");
  }
}

run();
