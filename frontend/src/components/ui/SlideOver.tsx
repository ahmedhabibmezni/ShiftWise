import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Icon } from "./Icon";
import { useFocusTrap } from "@/hooks/useFocusTrap";

/**
 * Right-side drawer rendered through a portal to <body>.
 *
 * Why portal: any ancestor with `transform`, `filter`, `backdrop-filter`,
 * `perspective`, `will-change`, or `contain: paint|strict|content|layout`
 * becomes the containing block for `position: fixed` descendants. Our
 * glass cards use `backdrop-filter: blur(120px)` and pages are nested
 * inside layout flex containers — rendering the drawer in-tree caused it
 * to anchor to the nearest such ancestor (the main column), so `right-4`
 * landed on the *left* side of the viewport. The portal escapes that.
 *
 * Structure:
 *   ┌─ overlay (fixed inset-0, body-portal'd) ─────────┐
 *   │  [dimmer button — fills viewport]                 │
 *   │                       ┌── panel ──────────────┐   │
 *   │                       │ header (64 px)        │   │
 *   │                       │ body (scroll, 28 px)  │   │
 *   │                       │ footer (optional)     │   │
 *   │                       └───────────────────────┘   │
 *   └───────────────────────────────────────────────────┘
 */
export function SlideOver({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** md = 560 px, lg = 680 px. Both shrink to viewport on narrow screens. */
  size?: "md" | "lg";
}) {
  const trapRef = useFocusTrap<HTMLElement>(open);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // Lock body scroll while the drawer is open
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  const widthClass = size === "lg" ? "w-[680px]" : "w-[560px]";

  const overlay = (
    <div
      aria-hidden={!open}
      className={`fixed inset-0 z-[60] ${open ? "" : "pointer-events-none"}`}
    >
      <button
        type="button"
        aria-label="Close drawer"
        onClick={onClose}
        className={`absolute inset-0 transition-opacity duration-[var(--dur-slow)] ${
          open ? "opacity-100" : "opacity-0"
        }`}
        style={{
          background:
            "radial-gradient(ellipse at right, rgba(6, 11, 40, 0.7), rgba(6, 11, 40, 0.55))",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
        }}
        tabIndex={-1}
      />
      <aside
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        inert={!open}
        className={`glass-card fixed right-4 top-4 bottom-4 ${widthClass} max-w-[calc(100vw_-_32px)] flex flex-col transition-all duration-[var(--dur-slow)] ${
          open
            ? "translate-x-0 opacity-100"
            : "translate-x-[calc(100%_+_2rem)] opacity-0 pointer-events-none"
        }`}
      >
        <header className="relative z-[1] shrink-0 h-[68px] px-7 flex items-center justify-between gap-4 border-b border-[var(--hairline)]">
          <div className="min-w-0 flex-1">
            <h2 className="text-[18px] font-bold tracking-[-0.01em] leading-tight text-[var(--text-primary)] truncate">
              {title}
            </h2>
            {subtitle && (
              <div className="mt-0.5 text-[12px] text-[var(--text-secondary)] leading-snug truncate">
                {subtitle}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close drawer"
            className="shrink-0 h-9 w-9 inline-flex items-center justify-center rounded-xl text-[var(--text-secondary)] hover:text-[var(--accent-light)] hover:bg-[var(--surface-soft-strong)] transition-all duration-200"
          >
            <Icon icon={X} size={18} />
          </button>
        </header>
        <div className="relative z-[1] flex-1 overflow-y-auto overflow-x-hidden px-7 py-6">
          {children}
        </div>
        {footer && (
          <footer className="relative z-[1] shrink-0 px-7 py-4 flex items-center justify-end gap-3 border-t border-[var(--hairline)] bg-[var(--surface-soft-strong)]/30">
            {footer}
          </footer>
        )}
      </aside>
    </div>
  );

  return createPortal(overlay, document.body);
}
