(function attachExtensionUtils(root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }
  root.LegislationTrackerExtension = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function buildExtensionUtils() {
  const DEFAULT_API_BASE = "http://localhost:8000";
  const DEFAULT_APP_BASE = "http://localhost:3000";
  const AUTH_TOKEN_KEY = "legislation_tracker_access";
  const AUTH_REFRESH_KEY = "legislation_tracker_refresh";
  const SETTINGS_API_BASE_KEY = "legislation_tracker_api_base";
  const SETTINGS_APP_BASE_KEY = "legislation_tracker_app_base";

  function normalizeBaseUrl(value, fallback = "") {
    const raw = String(value || fallback || "").trim();
    return raw.replace(/\/+$/, "");
  }

  function originPermissionForBaseUrl(value) {
    let url;
    try {
      url = new URL(normalizeBaseUrl(value));
    } catch {
      throw new Error("Enter a valid HTTP or HTTPS URL.");
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error("Enter a valid HTTP or HTTPS URL.");
    }
    return `${url.protocol}//${url.host}/*`;
  }

  function getBillUrl(appBase, billId) {
    return `${normalizeBaseUrl(appBase, DEFAULT_APP_BASE)}/bills/${encodeURIComponent(String(billId))}`;
  }

  function getBillsUrl(appBase) {
    return `${normalizeBaseUrl(appBase, DEFAULT_APP_BASE)}/bills`;
  }

  function getLoginUrl(appBase) {
    return `${normalizeBaseUrl(appBase, DEFAULT_APP_BASE)}/login`;
  }

  function getTopicTrackingPath() {
    return "/api/tracking/topics/";
  }

  function buildJsonRequest(method, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    return {
      method,
      headers,
      body: body == null ? undefined : JSON.stringify(body),
    };
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatPercent(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "";
    return `${Math.round(value * 100)}%`;
  }

  return {
    AUTH_REFRESH_KEY,
    AUTH_TOKEN_KEY,
    DEFAULT_API_BASE,
    DEFAULT_APP_BASE,
    SETTINGS_API_BASE_KEY,
    SETTINGS_APP_BASE_KEY,
    buildJsonRequest,
    escapeHtml,
    formatPercent,
    getBillUrl,
    getBillsUrl,
    getLoginUrl,
    getTopicTrackingPath,
    normalizeBaseUrl,
    originPermissionForBaseUrl,
  };
});
