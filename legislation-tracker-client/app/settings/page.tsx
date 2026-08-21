"use client";

import { FormEvent, useEffect, useState } from "react";

import RequireAuth from "@/app/components/RequireAuth";
import {
  deleteLLMSettings,
  getLLMSettings,
  type LLMSettings,
  updateLLMSettings,
  validateLLMCredential,
} from "@/lib/api";

function statusLabel(status: LLMSettings["validation_status"]): string {
  if (status === "valid") return "Valid";
  if (status === "invalid") return "Invalid";
  return "Not validated";
}

function LLMSettingsSection() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<"save" | "validate" | "toggle" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getLLMSettings()
      .then((value) => {
        if (active) setSettings(value);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load AI settings.");
      });
    return () => {
      active = false;
    };
  }, []);

  async function saveKey(event: FormEvent) {
    event.preventDefault();
    const submittedKey = apiKey.trim();
    if (!submittedKey) return;
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const updated = await updateLLMSettings({ api_key: submittedKey });
      setSettings(updated);
      setNotice("API key saved. Validate it before enhancing a bill.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the API key.");
    } finally {
      setApiKey("");
      setBusy(null);
    }
  }

  async function validateKey() {
    setBusy("validate");
    setError(null);
    setNotice(null);
    try {
      const updated = await validateLLMCredential();
      setSettings(updated);
      setNotice(updated.validation_status === "valid" ? "API key validated." : "The API key is not valid for this model.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not validate the API key.");
    } finally {
      setBusy(null);
    }
  }

  async function toggleEnabled() {
    if (!settings) return;
    setBusy("toggle");
    setError(null);
    setNotice(null);
    try {
      const updated = await updateLLMSettings({ enabled: !settings.enabled });
      setSettings(updated);
      setNotice(updated.enabled ? "AI enhancement enabled." : "AI enhancement disabled.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this setting.");
    } finally {
      setBusy(null);
    }
  }

  async function removeKey() {
    setBusy("delete");
    setError(null);
    setNotice(null);
    try {
      await deleteLLMSettings();
      setSettings((current) => current ? {
        ...current,
        configured: false,
        key_suffix: null,
        revision: null,
        enabled: false,
        validation_status: "unverified",
        validated_revision: null,
        validated_at: null,
      } : current);
      setConfirmDelete(false);
      setNotice("API key deleted. Existing enhancement history remains private and readable.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the API key.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-8 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-amber-700 dark:text-amber-400">
          Private account controls
        </p>
        <h1 className="text-3xl font-semibold text-slate-950 dark:text-green-300">Settings</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-700 dark:text-green-600">
          Your provider key is encrypted by the server and used only after you confirm an enhancement for a specific bill.
        </p>

        <section className="mt-8 border-l-4 border-amber-500 bg-white/80 p-5 shadow-sm dark:border-amber-400 dark:bg-green-950/20 dark:shadow-none sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-300 pb-4 dark:border-green-900/70">
            <div>
              <h2 className="text-xl font-semibold text-slate-950 dark:text-green-300">AI bill enhancement</h2>
              <p className="mt-1 text-sm text-slate-600 dark:text-green-600">
                Optional, user-triggered analysis layered over the deterministic bill summary.
              </p>
            </div>
            {settings && (
              <span className="border border-slate-400 px-2 py-1 text-xs uppercase tracking-wide text-slate-700 dark:border-green-800 dark:text-green-500">
                {settings.feature_available ? "Available" : "Unavailable"}
              </span>
            )}
          </div>

          {!settings && !error && <p className="mt-5 text-sm">Loading settings…</p>}
          {settings && (
            <>
              <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-slate-500 dark:text-green-700">Provider</dt>
                  <dd className="mt-1 font-semibold capitalize">{settings.provider}</dd>
                </div>
                <div>
                  <dt className="text-slate-500 dark:text-green-700">Requested model</dt>
                  <dd className="mt-1 font-semibold">{settings.requested_model}</dd>
                </div>
                <div>
                  <dt className="text-slate-500 dark:text-green-700">Validation</dt>
                  <dd className="mt-1 font-semibold">{statusLabel(settings.validation_status)}</dd>
                </div>
              </dl>

              {settings.configured && (
                <p className="mt-5 text-sm text-slate-700 dark:text-green-500">
                  {`Stored key ending in ${settings.key_suffix} · revision ${settings.revision}`}
                </p>
              )}

              <form onSubmit={saveKey} className="mt-5">
                <label htmlFor="llm-api-key" className="block text-sm font-semibold">
                  OpenAI API key
                </label>
                <div className="mt-2 flex flex-col gap-3 sm:flex-row">
                  <input
                    id="llm-api-key"
                    type="password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    autoComplete="new-password"
                    spellCheck={false}
                    disabled={!settings.feature_available || busy !== null}
                    placeholder={settings.configured ? "Enter a replacement key" : "sk-…"}
                    className="min-w-0 flex-1 border border-slate-500 bg-white px-3 py-2 text-slate-950 outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-60 dark:border-green-800 dark:bg-black dark:text-green-200"
                  />
                  <button
                    type="submit"
                    disabled={!apiKey.trim() || !settings.feature_available || busy !== null}
                    className="border border-slate-900 bg-slate-900 px-4 py-2 font-semibold text-white hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-50 dark:border-green-500 dark:bg-green-500 dark:text-black dark:hover:bg-green-400"
                  >
                    {busy === "save" ? "Saving…" : "Save API key"}
                  </button>
                </div>
              </form>

              <p className="mt-4 text-xs leading-5 text-amber-800 dark:text-amber-300">
                Validating may create one small provider charge. It runs only when you select Validate key.
              </p>

              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={validateKey}
                  disabled={!settings.configured || !settings.feature_available || busy !== null}
                  className="border border-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-200 disabled:opacity-50 dark:border-green-700 dark:hover:bg-green-950/50"
                >
                  {busy === "validate" ? "Validating…" : "Validate key"}
                </button>
                <button
                  type="button"
                  onClick={toggleEnabled}
                  disabled={!settings.configured || (!settings.feature_available && !settings.enabled) || busy !== null}
                  className="border border-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-200 disabled:opacity-50 dark:border-green-700 dark:hover:bg-green-950/50"
                >
                  {busy === "toggle" ? "Saving…" : settings.enabled ? "Disable enhancement" : "Enable enhancement"}
                </button>
                {settings.configured && !confirmDelete && (
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(true)}
                    disabled={busy !== null}
                    className="border border-red-700 px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
                  >
                    Delete API key
                  </button>
                )}
              </div>

              {confirmDelete && (
                <div role="alertdialog" aria-label="Delete API key" className="mt-5 border border-red-400 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950/20">
                  <p>The key will be removed immediately. A provider request already in progress cannot be recalled.</p>
                  <div className="mt-3 flex gap-3">
                    <button type="button" onClick={removeKey} disabled={busy !== null} className="bg-red-800 px-3 py-2 font-semibold text-white disabled:opacity-50">
                      {busy === "delete" ? "Deleting…" : "Confirm deletion"}
                    </button>
                    <button type="button" onClick={() => setConfirmDelete(false)} disabled={busy !== null} className="border border-slate-600 px-3 py-2 font-semibold">
                      Keep key
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {error && <p role="alert" className="mt-5 text-sm text-red-700 dark:text-red-400">{error}</p>}
          {notice && <p role="status" className="mt-5 text-sm text-slate-700 dark:text-green-500">{notice}</p>}
        </section>
      </div>
    </main>
  );
}

export default function SettingsPage() {
  return (
    <RequireAuth>
      <LLMSettingsSection />
    </RequireAuth>
  );
}
