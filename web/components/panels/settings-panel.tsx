"use client";

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Save, RotateCcw, AlertCircle, Loader2 } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useSettings } from "@/lib/use-settings";
import type { SettingView } from "@/lib/api";

interface SettingsPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Read + edit the non-secret runtime settings.
 *
 * Pulled by ``useSettings``. The panel is whole-form: clicking
 * "Save" persists every changed value via one PUT per key. Cancel
 * discards the in-flight edits. "Reset all" sends ``null`` to each
 * key (the server interprets that as restore-to-default).
 *
 * Inputs render off the ``type`` field returned by the server, not
 * off ``typeof value`` — that way a value that's currently a string
 * (because someone hand-edited the JSON file) still gets the right
 * widget for its declared type.
 */
export function SettingsPanel({ open, onOpenChange }: SettingsPanelProps) {
  const { settings, isLoading, error, update, refresh } = useSettings();

  // Edit buffer: { key -> staged value }. We only commit on Save.
  const [edits, setEdits] = React.useState<Record<string, unknown>>({});
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  // Reset edit buffer whenever the panel re-opens.
  React.useEffect(() => {
    if (open) {
      setEdits({});
      setSaveError(null);
    }
  }, [open]);

  const dirty = Object.keys(edits).length > 0;

  function setEdit(key: string, value: unknown) {
    setEdits((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!dirty) return;
    setSaving(true);
    setSaveError(null);
    try {
      // Sequential PUTs — small N (<10 typically); not worth parallelizing.
      for (const [key, value] of Object.entries(edits)) {
        await update(key, value);
      }
      setEdits({});
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      setSaveError(err.detail ?? err.message ?? String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleResetAll() {
    if (!settings) return;
    const ok = window.confirm(
      "Reset all settings to their defaults? This cannot be undone.",
    );
    if (!ok) return;
    setSaving(true);
    setSaveError(null);
    try {
      for (const s of settings) {
        await update(s.key, null);
      }
      setEdits({});
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      setSaveError(err.detail ?? err.message ?? String(e));
    } finally {
      setSaving(false);
    }
  }

  // Group settings by category so the form is scannable.
  const grouped = React.useMemo(() => {
    if (!settings) return [];
    const byCat: Record<string, SettingView[]> = {};
    for (const s of settings) {
      (byCat[s.category] ??= []).push(s);
    }
    return Object.entries(byCat);
  }, [settings]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 bg-ink/40 backdrop-blur-[3px] z-[150]",
            "animate-fade-in",
          )}
        />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
            "w-[640px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-64px)]",
            "bg-card border border-slate-200 rounded-4 shadow-modal",
            "flex flex-col z-[151] animate-fade-up overflow-hidden",
          )}
        >
          {/* Header */}
          <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 shrink-0">
            <div className="flex-1 min-w-0">
              <Dialog.Title className="text-15 font-semibold text-ink">
                Settings
              </Dialog.Title>
              <Dialog.Description className="text-12 text-slate-500 mt-0.5">
                Non-secret runtime knobs. Persisted to{" "}
                <code className="mono">~/.aamp_settings.json</code>.
              </Dialog.Description>
            </div>
            <button
              onClick={() => void refresh()}
              disabled={isLoading}
              className={cn(
                "text-12 text-slate-500 hover:text-slate-700 px-2 h-8 rounded-2",
                "hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed",
              )}
              title="Refresh"
            >
              {isLoading ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                "Refresh"
              )}
            </button>
            <Dialog.Close asChild>
              <IconButton aria-label="Close">
                <X size={16} strokeWidth={1.8} />
              </IconButton>
            </Dialog.Close>
          </div>

          {/* Body */}
          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
            {error && (
              <div className="mb-4 flex gap-2.5 items-start px-3 py-2.5 bg-critical-soft border border-critical/30 rounded-2">
                <AlertCircle size={16} className="text-critical mt-0.5 shrink-0" />
                <div className="flex-1 text-13 text-slate-700">
                  <div className="font-semibold text-critical">Couldn&apos;t load settings</div>
                  <div className="text-12 mt-0.5">{error.detail}</div>
                </div>
              </div>
            )}
            {!settings && isLoading && (
              <div className="py-12 flex items-center justify-center text-13 text-slate-500">
                <Loader2 size={16} className="animate-spin mr-2" />
                Loading…
              </div>
            )}
            {settings && settings.length === 0 && (
              <div className="py-12 text-13 text-slate-500 text-center italic">
                No settings registered.
              </div>
            )}
            {grouped.map(([category, rows]) => (
              <section key={category} className="mb-5 last:mb-0">
                <h3 className="text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 mb-2">
                  {category}
                </h3>
                <div className="flex flex-col gap-3">
                  {rows.map((s) => {
                    const liveValue = s.key in edits ? edits[s.key] : s.value;
                    return (
                      <SettingRow
                        key={s.key}
                        setting={s}
                        liveValue={liveValue}
                        onChange={(v) => setEdit(s.key, v)}
                        onReset={() => setEdit(s.key, s.default)}
                      />
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          {/* Footer */}
          <div
            className={cn(
              "flex items-center gap-2 px-5 py-3 border-t border-slate-200 shrink-0",
              "bg-slate-50",
            )}
          >
            {saveError && (
              <div className="text-12 text-critical flex-1 truncate">
                {saveError}
              </div>
            )}
            {!saveError && dirty && (
              <div className="text-12 text-slate-600 flex-1">
                {Object.keys(edits).length} unsaved change
                {Object.keys(edits).length === 1 ? "" : "s"}
              </div>
            )}
            {!saveError && !dirty && <div className="flex-1" />}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResetAll}
              disabled={saving || !settings}
              iconLeft={<RotateCcw size={13} strokeWidth={1.9} />}
            >
              Reset all
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEdits({})}
              disabled={!dirty || saving}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={!dirty || saving}
              iconLeft={
                saving ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Save size={13} strokeWidth={1.9} />
                )
              }
            >
              Save
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ---------------------------------------------------------------------------
// Per-row widget
// ---------------------------------------------------------------------------

function SettingRow({
  setting,
  liveValue,
  onChange,
  onReset,
}: {
  setting: SettingView;
  liveValue: unknown;
  onChange: (v: unknown) => void;
  onReset: () => void;
}) {
  const isDirty =
    JSON.stringify(liveValue) !== JSON.stringify(setting.value);
  const isDefault =
    JSON.stringify(liveValue) === JSON.stringify(setting.default);

  return (
    <div
      className={cn(
        "border rounded-3 px-3.5 py-3 transition-colors",
        isDirty
          ? "border-accent/40 bg-accent/[0.03]"
          : "border-slate-200 bg-card",
      )}
    >
      <div className="flex items-baseline gap-3 mb-1.5">
        <div className="mono text-[12.5px] font-semibold text-ink">
          {setting.key}
        </div>
        <div className="text-11 text-slate-500">{setting.type}</div>
        <div className="flex-1" />
        {!isDefault && (
          <button
            onClick={onReset}
            className="text-11 text-accent hover:text-accent-700"
          >
            reset to default
          </button>
        )}
      </div>
      <div className="text-12 text-slate-600 mb-2 leading-relaxed">
        {setting.description}
      </div>
      <SettingInput
        type={setting.type}
        value={liveValue}
        onChange={onChange}
        defaultValue={setting.default}
      />
    </div>
  );
}

function SettingInput({
  type,
  value,
  onChange,
  defaultValue,
}: {
  type: SettingView["type"];
  value: unknown;
  onChange: (v: unknown) => void;
  defaultValue: unknown;
}) {
  const inputClass = cn(
    "block w-full px-3 py-2 rounded-2 border border-slate-200 bg-card",
    "text-13 text-ink mono",
    "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20",
  );

  if (type === "bool") {
    return (
      <label className="inline-flex items-center gap-2 text-13 text-slate-700 cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-accent"
        />
        {value ? "Enabled" : "Disabled"}
      </label>
    );
  }

  if (type === "int" || type === "float") {
    return (
      <input
        type="number"
        step={type === "int" ? 1 : "any"}
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(defaultValue);
            return;
          }
          const parsed = type === "int" ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(parsed) ? raw : parsed);
        }}
        className={inputClass}
      />
    );
  }

  if (type === "json") {
    return (
      <textarea
        rows={3}
        value={JSON.stringify(value, null, 2)}
        onChange={(e) => {
          try {
            onChange(JSON.parse(e.target.value));
          } catch {
            onChange(e.target.value);
          }
        }}
        className={cn(inputClass, "resize-y")}
      />
    );
  }

  // string fallback
  return (
    <input
      type="text"
      value={value === null || value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
      className={inputClass}
    />
  );
}
