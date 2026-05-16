import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { SidebarBody } from "./Sidebar";

/**
 * Mobile primary navigation — a left-sliding overlay drawer.
 *
 * The desktop `Sidebar` rail is `hidden lg:flex`; below `lg` it is gone, so
 * this drawer is the only route between pages on phones and small tablets.
 * It reuses `SidebarBody` verbatim, and `onNavigate` (wired to `onClose`)
 * dismisses the overlay the instant a nav link is tapped.
 *
 * Portalled to <body> for the same reason as SlideOver: a `backdrop-filter`
 * ancestor would capture `position: fixed`.
 */
export function MobileNav({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const trapRef = useFocusTrap<HTMLElement>(open);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      aria-hidden={!open}
      className={`fixed inset-0 z-[60] lg:hidden ${
        open ? "" : "pointer-events-none"
      }`}
    >
      <button
        type="button"
        aria-label="Close navigation"
        tabIndex={-1}
        onClick={onClose}
        className={`absolute inset-0 transition-opacity duration-[var(--dur-slow)] ${
          open ? "opacity-100" : "opacity-0"
        }`}
        style={{
          background: "rgba(6, 11, 40, 0.6)",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
        }}
      />
      <aside
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Primary navigation"
        inert={!open}
        className={`glass-card fixed left-4 top-4 bottom-4 flex w-[280px] max-w-[calc(100vw_-_32px)] flex-col overflow-hidden transition-transform duration-[var(--dur-slow)] ${
          open ? "translate-x-0" : "-translate-x-[calc(100%_+_1.5rem)]"
        }`}
      >
        <SidebarBody onNavigate={onClose} />
      </aside>
    </div>,
    document.body,
  );
}
