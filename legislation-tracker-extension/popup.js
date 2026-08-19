/**
 * Popup script: extracts page text, calls the Django API, and lets signed-in
 * users track matched legislation.
 */

const utils = window.LegislationTrackerExtension;

let apiBase = utils.DEFAULT_API_BASE;
let appBase = utils.DEFAULT_APP_BASE;
let accessToken = "";
let refreshToken = "";
let topicCatalogBySlug = new Map();
let matchedTopicNamesBySlug = new Map();
let latestMatchData = null;

const $status = document.getElementById("status");
const $statusText = document.getElementById("status-text");
const $error = document.getElementById("error");
const $results = document.getElementById("results");
const $topics = document.getElementById("topics");
const $topicsSection = document.getElementById("topics-section");
const $bills = document.getElementById("bills");
const $billsSection = document.getElementById("bills-section");
const $noResults = document.getElementById("no-results");
const $openApp = document.getElementById("open-app");
const $openLogin = document.getElementById("open-login");
const $loginForm = document.getElementById("login-form");
const $loginEmail = document.getElementById("login-email");
const $loginPassword = document.getElementById("login-password");
const $authSignedOut = document.getElementById("auth-signed-out");
const $authSignedIn = document.getElementById("auth-signed-in");
const $logoutButton = document.getElementById("logout-button");
const $settingsForm = document.getElementById("settings-form");
const $settingsApiBase = document.getElementById("settings-api-base");
const $settingsAppBase = document.getElementById("settings-app-base");
const $settingsMessage = document.getElementById("settings-message");

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(items) {
  return new Promise((resolve) => chrome.storage.local.set(items, resolve));
}

function storageRemove(keys) {
  return new Promise((resolve) => chrome.storage.local.remove(keys, resolve));
}

function requestApiHostPermission(origin) {
  const host = new URL(origin).hostname;
  if (host === "localhost" || host === "127.0.0.1") return Promise.resolve(true);
  return new Promise((resolve) => {
    chrome.permissions.request({ origins: [origin] }, resolve);
  });
}

function queryActiveTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      resolve(tabs[0]);
    });
  });
}

function executeArticleExtraction(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript(
      {
        target: { tabId },
        files: ["content.js"],
      },
      (results) => {
        const runtimeError = chrome.runtime.lastError;
        if (runtimeError) {
          reject(new Error(runtimeError.message));
          return;
        }
        resolve(results?.[0]?.result);
      },
    );
  });
}

function setStatus(message) {
  $statusText.textContent = message;
  $status.hidden = false;
  $error.hidden = true;
}

function showError(message, options = {}) {
  $status.hidden = true;
  if (options.hideResults !== false) {
    $results.hidden = true;
  }
  $error.textContent = message;
  $error.hidden = false;
}

function updateLinks() {
  $openApp.href = utils.getBillsUrl(appBase);
  $openLogin.href = utils.getLoginUrl(appBase);
}

function updateAuthUi() {
  const signedIn = Boolean(accessToken);
  $authSignedOut.hidden = signedIn;
  $authSignedIn.hidden = !signedIn;
}

async function loadSettingsAndAuth() {
  const stored = await storageGet([
    utils.AUTH_TOKEN_KEY,
    utils.AUTH_REFRESH_KEY,
    utils.SETTINGS_API_BASE_KEY,
    utils.SETTINGS_APP_BASE_KEY,
  ]);
  apiBase = utils.normalizeBaseUrl(stored[utils.SETTINGS_API_BASE_KEY], utils.DEFAULT_API_BASE);
  appBase = utils.normalizeBaseUrl(stored[utils.SETTINGS_APP_BASE_KEY], utils.DEFAULT_APP_BASE);
  accessToken = stored[utils.AUTH_TOKEN_KEY] || "";
  refreshToken = stored[utils.AUTH_REFRESH_KEY] || "";
  $settingsApiBase.value = apiBase;
  $settingsAppBase.value = appBase;
  updateLinks();
  updateAuthUi();
}

async function saveSettings(event) {
  event.preventDefault();
  $settingsMessage.hidden = true;
  try {
    const nextApiBase = utils.normalizeBaseUrl($settingsApiBase.value);
    const nextAppBase = utils.normalizeBaseUrl($settingsAppBase.value);
    const apiOrigin = utils.originPermissionForBaseUrl(nextApiBase);
    utils.originPermissionForBaseUrl(nextAppBase);
    const granted = await requestApiHostPermission(apiOrigin);
    if (!granted) {
      throw new Error("Allow access to the API host to use this endpoint.");
    }
    apiBase = nextApiBase;
    appBase = nextAppBase;
    topicCatalogBySlug = new Map();
    await storageSet({
      [utils.SETTINGS_API_BASE_KEY]: apiBase,
      [utils.SETTINGS_APP_BASE_KEY]: appBase,
    });
    updateLinks();
    $settingsMessage.textContent = "Endpoints saved.";
    $settingsMessage.hidden = false;
  } catch (err) {
    $settingsMessage.textContent = err.message || "Could not save endpoints.";
    $settingsMessage.hidden = false;
  }
}

async function saveTokens(access, refresh) {
  accessToken = access || "";
  refreshToken = refresh || "";
  await storageSet({
    [utils.AUTH_TOKEN_KEY]: accessToken,
    [utils.AUTH_REFRESH_KEY]: refreshToken,
  });
  updateAuthUi();
}

async function clearTokens() {
  accessToken = "";
  refreshToken = "";
  await storageRemove([utils.AUTH_TOKEN_KEY, utils.AUTH_REFRESH_KEY]);
  updateAuthUi();
}

async function parseJsonResponse(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `Request failed: ${res.status}`);
  }
  return data;
}

async function publicJson(path, init) {
  const res = await fetch(`${apiBase}${path}`, init);
  return parseJsonResponse(res);
}

async function refreshAccessToken() {
  if (!refreshToken) return false;
  const res = await fetch(
    `${apiBase}/api/auth/token/refresh/`,
    utils.buildJsonRequest("POST", { refresh: refreshToken }),
  );
  if (!res.ok) {
    await clearTokens();
    return false;
  }
  const data = await res.json();
  if (!data.access) {
    await clearTokens();
    return false;
  }
  await saveTokens(data.access, refreshToken);
  return true;
}

async function authJson(path, method, body, retried = false) {
  if (!accessToken) {
    throw new Error("Sign in before tracking items.");
  }

  const res = await fetch(
    `${apiBase}${path}`,
    utils.buildJsonRequest(method, body, accessToken),
  );

  if (res.status === 401 && !retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return authJson(path, method, body, true);
    throw new Error("Your session expired. Sign in again.");
  }

  return parseJsonResponse(res);
}

async function loadTopicCatalog() {
  if (topicCatalogBySlug.size > 0) return;
  try {
    const topics = await publicJson("/api/topics/");
    topicCatalogBySlug = new Map(topics.map((topic) => [topic.slug, topic]));
  } catch (err) {
    topicCatalogBySlug = new Map();
  }
}

function topicName(slug) {
  return matchedTopicNamesBySlug.get(slug) || topicCatalogBySlug.get(slug)?.name || slug;
}

function renderTopics(topics) {
  matchedTopicNamesBySlug = new Map(topics.map((topic) => [topic.slug, topic.name]));

  if (!topics.length) {
    $topicsSection.hidden = true;
    return;
  }

  $topicsSection.hidden = false;
  $topics.innerHTML = topics
    .map((topic) => {
      const topicId = topicCatalogBySlug.get(topic.slug)?.id;
      const followButton = accessToken
        ? `<button type="button" data-action="follow-topic" data-topic-id="${utils.escapeHtml(topicId || "")}" ${topicId ? "" : "disabled"}>Follow</button>`
        : "";
      const confidence = utils.formatPercent(topic.confidence);
      return `
        <div class="topic-badge" title="${utils.escapeHtml(topic.slug)} - ${utils.escapeHtml(topic.keyword_hits)} keyword hits">
          <span>${utils.escapeHtml(topic.name)}</span>
          ${confidence ? `<span class="confidence">${utils.escapeHtml(confidence)}</span>` : ""}
          ${followButton}
        </div>`;
    })
    .join("");
}

function renderBills(bills) {
  if (!bills.length) {
    $billsSection.hidden = true;
    $noResults.hidden = false;
    return;
  }

  $billsSection.hidden = false;
  $noResults.hidden = true;
  $bills.innerHTML = bills
    .map((bill) => {
      const topics = Array.isArray(bill.topics)
        ? bill.topics.map(topicName).filter(Boolean).join(", ")
        : "";
      const sponsor = bill.sponsor_name || "";
      const billUrl = utils.getBillUrl(appBase, bill.id);
      const trackingButton = accessToken
        ? `<button type="button" data-action="track-bill" data-bill-id="${utils.escapeHtml(bill.id)}">Track</button>`
        : "";
      return `
        <article class="bill-card">
          <div class="bill-header">
            <span class="bill-number">${utils.escapeHtml(bill.bill_number)}</span>
            <span class="bill-score" title="Relevance score">Score: ${utils.escapeHtml(bill.score)}</span>
          </div>
          <div class="bill-title">${utils.escapeHtml(truncate(bill.title, 140))}</div>
          <div class="bill-meta">
            ${sponsor ? `<span>${utils.escapeHtml(sponsor)}</span>` : ""}
            ${topics ? `<span class="bill-topics">${utils.escapeHtml(topics)}</span>` : ""}
          </div>
          <div class="bill-actions">
            <a href="${utils.escapeHtml(billUrl)}" target="_blank">View</a>
            ${trackingButton}
          </div>
        </article>`;
    })
    .join("");
}

function showResults(data) {
  latestMatchData = data;
  const topics = Array.isArray(data.topics) ? data.topics : [];
  const bills = Array.isArray(data.bills) ? data.bills : [];

  $status.hidden = true;
  $error.hidden = true;
  $results.hidden = false;

  renderTopics(topics);
  renderBills(bills);
}

function truncate(value, max) {
  const str = String(value || "");
  return str.length > max ? `${str.slice(0, max)}...` : str;
}

async function handleLogin(event) {
  event.preventDefault();
  const email = $loginEmail.value.trim().toLowerCase();
  const password = $loginPassword.value;
  if (!email || !password) return;

  const submitButton = $loginForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  submitButton.textContent = "Signing in...";
  try {
    const data = await publicJson(
      "/api/auth/token/",
      utils.buildJsonRequest("POST", { email, password }),
    );
    await saveTokens(data.access, data.refresh);
    $loginPassword.value = "";
    if (latestMatchData) showResults(latestMatchData);
  } catch (err) {
    showError(err.message || "Sign in failed.", { hideResults: false });
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Sign in";
  }
}

async function handleResultAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;

  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Saving...";

  try {
    if (button.dataset.action === "track-bill") {
      const billId = Number(button.dataset.billId);
      await authJson("/api/tracking/bills/", "POST", { bill: billId });
      button.textContent = "Tracked";
    } else if (button.dataset.action === "follow-topic") {
      const topicId = Number(button.dataset.topicId);
      await authJson("/api/preferences/follow-topic/", "POST", { topic_id: topicId });
      button.textContent = "Following";
    }
    button.classList.add("is-saved");
  } catch (err) {
    button.disabled = false;
    button.textContent = originalLabel;
    showError(err.message || "Could not save tracking preference.", { hideResults: false });
  }
}

async function matchArticle(article) {
  return publicJson(
    "/api/bills/match-article/",
    utils.buildJsonRequest("POST", { text: article.text, url: article.url }),
  );
}

async function run() {
  try {
    await loadSettingsAndAuth();
    setStatus("Analyzing article...");

    const tab = await queryActiveTab();
    if (!tab?.id) {
      showError("No active tab found.");
      return;
    }

    let article;
    try {
      article = await executeArticleExtraction(tab.id);
    } catch (scriptErr) {
      showError("Can't read this page. Try a regular article.");
      return;
    }

    if (!article?.text) {
      showError("Couldn't extract text from this page.");
      return;
    }

    setStatus("Matching against legislation...");
    const data = await matchArticle(article);
    await loadTopicCatalog();
    showResults(data);
  } catch (err) {
    if (err instanceof TypeError) {
      showError("Can't reach backend. Is the Django server running on localhost:8000?");
      return;
    }
    showError(err.message || "Unknown error.");
  }
}

$loginForm.addEventListener("submit", handleLogin);
$settingsForm.addEventListener("submit", saveSettings);
$logoutButton.addEventListener("click", async () => {
  await clearTokens();
  if (latestMatchData) showResults(latestMatchData);
});
$topics.addEventListener("click", handleResultAction);
$bills.addEventListener("click", handleResultAction);

run();
