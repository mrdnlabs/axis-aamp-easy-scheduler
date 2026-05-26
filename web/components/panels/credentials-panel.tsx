"use client";

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  X,
  Lock,
  Check,
  AlertCircle,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { IconButton, Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useCredentials } from "@/lib/use-credentials";
import type { CredentialSlotView } from "@/lib/api";

interface CredentialsPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Called with ``account_id/field`` when the user clicks Rotate.
   * The parent opens SecureCaptureModal with this composed key.
   * After the modal completes, ``onCaptured`` is the parent's
   * concern; we just refresh the list when this panel re-opens.
   */
  onRotate: (credentialKey: string) => void;
}

/**
 * Read-only view of the credential slots known to ChAAMP. Values
 * never cross the wire — the panel only shows which slots have a
 * value stored, not what it is.
 *
 * "Rotate" overwrites a slot via the existing SecureCaptureModal.
 * There is intentionally no Delete: revocation is done in the OS
 * keyring tool (Windows Credential Manager / macOS Keychain) so
 * that no client can accidentally wipe credentials.
 */
export function CredentialsPanel({
  open,
  onOpenChange,
  onRotate,
}: CredentialsPanelProps) {
  const { credentials, isLoading, error, refresh } = useCredentials();

  // Re-fetch every time the panel opens so the "stored" booleans
  // reflect any rotations or external keyring edits that happened
  // since last view. Cheap.
  React.useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

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
            "w-[680px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-64px)]",
            "bg-card border border-slate-200 rounded-4 shadow-modal",
            "flex flex-col z-[151] animate-fade-up overflow-hidden",
          )}
        >
          <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 shrink-0">
            <Lock size={18} className="text-slate-500" strokeWidth={1.9} />
            <div className="flex-1 min-w-0">
              <Dialog.Title className="text-15 font-semibold text-ink">
                Credentials
              </Dialog.Title>
              <Dialog.Description className="text-12 text-slate-500 mt-0.5">
                Values are stored in the OS keyring and never enter chat. Rotate to overwrite.
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
              {isLoading ? <Loader2 size={14} className="animate-spin" /> : "Refresh"}
            </button>
            <Dialog.Close asChild>
              <IconButton aria-label="Close">
                <X size={16} strokeWidth={1.8} />
              </IconButton>
            </Dialog.Close>
          </div>

          {/* Trust-model banner */}
          <div className="px-5 py-3 bg-ink/[0.03] border-b border-slate-200 text-12 text-slate-700 leading-relaxed">
            To <strong>revoke</strong> a credential entirely, delete the
            corresponding <code className="mono">aamp/&hellip;</code> entry in your OS
            credential manager (Windows Credential Manager, macOS Keychain, or
            libsecret). Rotation here only overwrites.
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
            {error && (
              <div className="mb-4 flex gap-2.5 items-start px-3 py-2.5 bg-critical-soft border border-critical/30 rounded-2">
                <AlertCircle size={16} className="text-critical mt-0.5 shrink-0" />
                <div className="flex-1 text-13 text-slate-700">
                  <div className="font-semibold text-critical">
                    Couldn&apos;t load credentials
                  </div>
                  <div className="text-12 mt-0.5">{error.detail}</div>
                </div>
              </div>
            )}

            {!credentials && isLoading && (
              <div className="py-12 flex items-center justify-center text-13 text-slate-500">
                <Loader2 size={16} className="animate-spin mr-2" />
                Loading…
              </div>
            )}

            {credentials && credentials.length === 0 && (
              <div className="py-12 text-13 text-slate-500 text-center italic">
                No credential slots registered.
              </div>
            )}

            <div className="flex flex-col gap-2.5">
              {credentials?.map((c) => (
                <CredentialRow
                  key={`${c.account_id}/${c.field}`}
                  slot={c}
                  onRotate={() => onRotate(`${c.account_id}/${c.field}`)}
                />
              ))}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CredentialRow({
  slot,
  onRotate,
}: {
  slot: CredentialSlotView;
  onRotate: () => void;
}) {
  return (
    <div
      className={cn(
        "border rounded-3 px-3.5 py-3 transition-colors",
        slot.stored ? "border-slate-200 bg-card" : "border-warning/40 bg-warning-soft",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center justify-center w-7 h-7 rounded-2 shrink-0",
            slot.stored ? "bg-success-soft text-success" : "bg-warning/10 text-warning",
          )}
          aria-hidden="true"
        >
          {slot.stored ? (
            <Check size={14} strokeWidth={2.4} />
          ) : (
            <AlertCircle size={14} strokeWidth={2} />
          )}
        </span>
        <div className="flex-1 min-w-0">
          <div className="mono text-[12.5px] font-semibold text-ink">
            {slot.account_id}/{slot.field}
          </div>
          <div className="text-12 text-slate-600 mt-0.5">{slot.description}</div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={onRotate}
          iconLeft={<RotateCcw size={12} strokeWidth={2} />}
        >
          {slot.stored ? "Rotate" : "Set"}
        </Button>
      </div>
    </div>
  );
}
