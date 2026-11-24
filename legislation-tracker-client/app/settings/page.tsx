"use client";
import LoadingSpinner from "@/app/components/LoadingSpinner";

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
  const [draft, setDraft] = useState<{provider: string; model: string} | null>(null);
  const provider = draft?.provider ?? settings?.provider ?? "";
  const model = draft?.model ?? settings?.requested_model ?? "";
  const selected = settings?.models.find(item => item.provider === provider && item.model === model);
  const compatible = Boolean(selected);
  const changed = provider !== settings?.provider || model !== settings?.requested_model;
  const saved = settings?.saved_credentials?.find(item => item.provider === provider);
  const hasKey = Boolean(saved || (settings?.configured && provider === settings.provider));
  const providerLabel = ({openai: "OpenAI", openrouter: "OpenRouter", anthropic: "Anthropic", gemini: "Google"} as Record<string,string>)[provider] ?? provider;
  const [busy, setBusy] = useState<"save" | "validate" | "toggle" | "delete" | null>(null);
  const [deleteProvider, setDeleteProvider] = useState<string | null>(null);
  const [settingsRevision, setSettingsRevision] = useState(0);
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
  }, [settingsRevision]);

  async function saveKey(event: FormEvent) {
    event.preventDefault();
    const submittedKey = apiKey.trim();
    if (!settings || !compatible || (!submittedKey && (!changed || !hasKey))) return;
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const updated = await updateLLMSettings({
        ...(submittedKey ? {api_key: submittedKey} : {}),
        provider, requested_model: selected?.model ?? settings.requested_model,
      });
      setSettings(updated);
      setDraft(null);
      setNotice("Saved. Validate the key before enhancing a bill.");
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
      const updated = await validateLLMCredential(provider);
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
      const updated = await updateLLMSettings({ enabled: !settings.enabled }, provider);
      setSettings(updated);
      setNotice(updated.enabled ? "AI enhancement enabled." : "AI enhancement disabled.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this setting.");
    } finally {
      setBusy(null);
    }
  }

  async function removeKey() {
    if (!deleteProvider) return;
    setBusy("delete");
    setError(null);
    setNotice(null);
    try {
      await deleteLLMSettings(deleteProvider);
      setDeleteProvider(null);
      setDraft(null);
      setApiKey("");
      setSettings(null);
      setSettingsRevision(value => value + 1);
      setNotice("API key deleted. Existing enhancement history remains private and readable.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the API key.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="tracker-page min-h-[calc(100vh-4rem)] font-sans">
      <div className="mx-auto max-w-4xl">
        <p className="mb-2 text-sm font-medium text-muted">
          Private account controls
        </p>
        <h1 className="tracker-heading text-ink">Settings</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Your provider key is encrypted by the server and used only after you confirm an enhancement for a specific bill.
        </p>

        <section className="tracker-panel mt-8 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-4">
            <div>
              <h2 className="text-xl font-semibold text-ink">AI bill enhancement</h2>
              <p className="mt-1 text-sm text-muted">
                Optional, user-triggered analysis layered over the deterministic bill summary.
              </p>
            </div>
            {settings && (
              <span className="border border-line px-2 py-1 text-xs uppercase tracking-wide text-muted">
                {settings.feature_available ? "Available" : "Unavailable"}
              </span>
            )}
          </div>

          <LoadingSpinner centered active={!settings && !error} label="Loading settings…" />
          {settings && (
            <>
              <label htmlFor="enhancement-provider" className="mt-5 block text-sm font-semibold">Provider</label>
              <select id="enhancement-provider" value={provider} disabled={busy !== null}
                onChange={event => {
                  const next = event.target.value;
                  const stored = settings.saved_credentials?.find(item => item.provider === next);
                  const choices = settings.models.filter(item => item.provider === next);
                  const model = choices.find(item => item.model === stored?.selected_model)?.model ?? choices[0]?.model ?? "";
                  setDraft({provider: next, model});
                  setApiKey("");
                  setDeleteProvider(null);
                  setError(null);
                  setNotice(null);
                }}>
                {Array.from(new Set([settings.provider, ...settings.models.map(item => item.provider),
                  ...(settings.saved_credentials ?? []).map(item => item.provider)])).map(name =>
                  <option key={name} value={name}>{name}</option>
                )}
              </select>
              <label htmlFor="enhancement-model" className="mt-5 block text-sm font-semibold">Model</label>
              <select id="enhancement-model" className="mt-2 rounded border border-control bg-paper px-3 py-2"
                value={model}
                disabled={!settings.feature_available || busy !== null}
                onChange={event => {setDraft({provider, model: event.target.value}); setApiKey(""); setDeleteProvider(null); setError(null); setNotice(null);}}>
                {!compatible &&
                  <option value={model} disabled>Choose a compatible model</option>}
                {settings.models.filter(m => m.provider === provider).map(m => <option key={m.model} value={m.model}>
                  {m.model}{m.free ? " · Free" : ""}
                </option>)}
              </select>
              <dl className="mt-4 text-sm">
                <div>
                  <dt className="text-muted">Validation</dt>
                  <dd className="mt-1 font-semibold">{changed ? compatible ? "Not saved" : "Model unavailable" : statusLabel(settings.validation_status)}</dd>
                </div>
              </dl>

              {hasKey && (
                <p className="mt-5 text-sm text-muted">
                  {`Stored key ending in ${saved?.key_suffix ?? settings.key_suffix} · revision ${saved?.revision ?? settings.revision}`}
                </p>
              )}

              <form onSubmit={saveKey} className="mt-5">
                <label htmlFor="llm-api-key" className="block text-sm font-semibold">
                  {providerLabel} API key
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
                    placeholder={hasKey ? "Enter a replacement key" : "Enter API key"}
                    className="min-w-0 flex-1 border border-control bg-paper px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-focus disabled:opacity-60"
                  />
                  <button
                    type="submit"
                    disabled={!compatible || (!apiKey.trim() && (!changed || !hasKey)) || !settings.feature_available || busy !== null}
                    className="border border-control bg-ink px-4 py-2 font-semibold text-paper hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-focus disabled:opacity-50"
                  >
                    {busy === "save" ? "Saving…" : changed ? "Save model" : "Save API key"}
                  </button>
                </div>
              </form>

              <p className="mt-4 text-xs leading-5 text-amber-800 dark:text-amber-300">
                {settings.models.some(m => m.provider === provider && m.model === (selected?.model ?? settings.requested_model) && m.free)
                    ? "This model has no token charge. Provider limits apply."
                    : "Validating may create one small provider charge. It runs only when you select Validate key."}
              </p>

              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={validateKey}
                  disabled={!compatible || changed || !settings.configured || !settings.feature_available || busy !== null}
                  className="border border-control px-3 py-2 text-sm font-semibold hover:bg-wash disabled:opacity-50"
                >
                  {busy === "validate" ? "Validating…" : "Validate key"}
                </button>
                <button
                  type="button"
                  onClick={toggleEnabled}
                  disabled={changed || !settings.configured || (!settings.feature_available && !settings.enabled) || busy !== null}
                  className="border border-control px-3 py-2 text-sm font-semibold hover:bg-wash disabled:opacity-50"
                >
                  {busy === "toggle" ? "Saving…" : settings.enabled ? "Disable enhancement" : "Enable enhancement"}
                </button>
                {hasKey && !deleteProvider && (
                  <button
                    type="button"
                    onClick={() => setDeleteProvider(provider)}
                    disabled={busy !== null}
                    className="border border-red-700 px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
                  >
                    Delete API key
                  </button>
                )}
              </div>

              {deleteProvider && (
                <div role="alertdialog" aria-label="Delete API key" className="mt-5 border border-red-400 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950/20">
                  <p>The {deleteProvider} key will be removed immediately. A provider request already in progress cannot be recalled.</p>
                  <div className="mt-3 flex gap-3">
                    <button type="button" onClick={removeKey} disabled={busy !== null} className="bg-red-800 px-3 py-2 font-semibold text-white disabled:opacity-50">
                      {busy === "delete" ? "Deleting…" : "Confirm deletion"}
                    </button>
                    <button type="button" onClick={() => setDeleteProvider(null)} disabled={busy !== null} className="border border-control px-3 py-2 font-semibold">
                      Keep key
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {error && <p role="alert" className="mt-5 text-sm text-red-700 dark:text-red-400">{error}</p>}
          {!settings && error && (
            <button type="button" onClick={() => { setError(null); setSettingsRevision(value => value + 1); }}>
              Reload settings
            </button>
          )}
          {notice && <p role="status" className="mt-5 text-sm text-muted">{notice}</p>}
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
