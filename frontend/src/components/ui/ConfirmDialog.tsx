import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, type LucideIcon } from "lucide-react";
import { Icon } from "./Icon";
import { Button } from "./Button";

const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Centered confirmation modal for irreversible / destructive actions.
 *
 * A modal is the correct affordance here, not laziness: the action cannot be
 * undone, so the operator must stop and read before committing. The dialog
 * names the exact entity and spells out the consequence.
 *
 * Keyboard ownership: the dialog opens on top of a `SlideOver`, which also
 * traps focus and closes on Escape. To stop one Escape press from closing
 * both layers, this component installs its keydown handler in the **capture**
 * phase and calls `stopImmediatePropagation()` — the SlideOver's bubble-phase
 * handler underneath never sees the event while the dialog is open.
 *
 * Portalled to <body> for the same reason as SlideOver: a `backdrop-filter`
 * ancestor would otherwise become the containing block for `position: fixed`.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  loading = false,
  icon = AlertTriangle,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  loading?: boolean;
  icon?: LucideIcon;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // The keydown handler is registered once per open; mirror `loading` into a
  // ref so it reads the live value without re-installing the listener.
  const loadingRef = useRef(loading);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    loadingRef.current = loading;
  }, [loading]);

  useEffect(() => {
    if (!open) return;
    const root = dialogRef.current;
    if (!root) return;

    const prevFocus = document.activeElement as HTMLElement | null;
    const getFocusable = () =>
      Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null,
      );

    // Initial focus → the dismiss button (first in DOM order). A destructive
    // prompt must never auto-focus its own irreversible action.
    const raf = requestAnimationFrame(() => getFocusable()[0]?.focus());

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        e.preventDefault();
        if (!loadingRef.current) onClose();
        return;
      }
      if (e.key !== "Tab") return;
      e.stopImmediatePropagation();
      const f = getFocusable();
      if (f.length === 0) {
        e.preventDefault();
        return;
      }
      const first = f[0];
      const last = f[f.length - 1];
      const cur = document.activeElement as HTMLElement | null;
      const atEdge = e.shiftKey ? cur === first || !root.contains(cur) : cur === last;
      if (atEdge) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      }
    };

    document.addEventListener("keydown", onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      if (prevFocus && document.contains(prevFocus)) prevFocus.focus();
    };
  }, [open, onClose]);

  if (!mounted) return null;

  const overlay = (
    <div
      aria-hidden={!open}
      className={`fixed inset-0 z-[70] flex items-center justify-center p-4 ${
        open ? "" : "pointer-events-none"
      }`}
    >
      <button
        type="button"
        aria-label="Dismiss dialog"
        tabIndex={-1}
        onClick={() => !loading && onClose()}
        className={`absolute inset-0 transition-opacity duration-200 ${
          open ? "opacity-100" : "opacity-0"
        }`}
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(6, 11, 40, 0.74), rgba(6, 11, 40, 0.62))",
          backdropFilter: "blur(3px)",
          WebkitBackdropFilter: "blur(3px)",
        }}
      />
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className={`glass-card relative w-full max-w-[440px] p-7 transition-all duration-200 ${
          open
            ? "opacity-100 translate-y-0 scale-100"
            : "opacity-0 translate-y-2 scale-[0.98] pointer-events-none"
        }`}
      >
        <div className="relative z-[1] flex flex-col items-start gap-4">
          <span
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl"
            style={{
              background: "rgba(224, 61, 61, 0.14)",
              color: "var(--alert-critical)",
            }}
          >
            <Icon icon={icon} size={20} strokeWidth={2} />
          </span>
          <div className="space-y-2">
            <h2
              id="confirm-dialog-title"
              className="text-[18px] font-bold tracking-[-0.01em] text-[var(--text-primary)]"
            >
              {title}
            </h2>
            <div
              id="confirm-dialog-message"
              className="text-[13px] leading-relaxed text-[var(--text-secondary)]"
            >
              {message}
            </div>
          </div>
          <div className="mt-2 flex w-full items-center justify-end gap-3">
            <Button variant="secondary" onClick={onClose} disabled={loading}>
              {cancelLabel}
            </Button>
            <Button variant="danger" loading={loading} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
