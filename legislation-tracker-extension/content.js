/**
 * Content script: extracts article text from the current page.
 * Injected on-demand by popup.js via chrome.scripting.executeScript.
 */

function extractArticle() {
  const title = document.title || "";

  // Try semantic containers in priority order
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
  if (!bodyEl) {
    bodyEl = document.body;
  }

  // Clone and strip noise
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

  // Get text, collapse whitespace
  const rawText = (clone.textContent || "").replace(/\s+/g, " ").trim();

  // Cap at 10k chars (backend caps too, but save bandwidth)
  const text = rawText.slice(0, 10000);

  return { title, text, url: window.location.href };
}

extractArticle();
