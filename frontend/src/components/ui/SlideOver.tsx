import { useEffect } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Icon } from "./Icon";

export function SlideOver({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div
      aria-hidden={!open}
      className={`fixed inset-0 z-40 ${open ? "" : "pointer-events-none"}`}
    >
      <button
        type="button"
        aria-label="Fermer"
        onClick={onClose}
        className={`absolute inset-0 transition-opacity duration-200 ${
          open ? "opacity-100" : "opacity-0"
        }`}
        style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
        tabIndex={open ? 0 : -1}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`absolute right-0 top-0 h-full w-[480px] max-w-full bg-bg border-l border-line-strong flex flex-col transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="h-16 px-6 flex items-center justify-between border-b border-line">
          <h2 className="text-h2 lowercase">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="h-10 w-10 inline-flex items-center justify-center rounded-sm border border-transparent hover:bg-bg-elev hover:border-line text-ink-muted hover:text-ink transition-colors duration-150"
          >
            <Icon icon={X} size={20} />
          </button>
        </header>
        <div className="flex-1 overflow-auto p-8">{children}</div>
        {footer && (
          <footer className="h-16 px-6 flex items-center justify-end gap-2 border-t border-line">
            {footer}
          </footer>
        )}
      </aside>
    </div>
  );
}
