import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowRightLeft,
  BarChart3,
  LayoutDashboard,
  LogOut,
  Monitor,
  Moon,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  Sun,
  Users as UsersIcon,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { Kbd } from "@/components/ui/Kbd";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { useTheme } from "@/hooks/useTheme";
import { logout as logoutRequest } from "@/api/auth";
import { forceLogout } from "@/lib/session";

type Command = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: LucideIcon;
  run: () => void;
};

const OPEN_EVENT = "shiftwise:open-cmdk";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(0);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const listRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  // `navigate` returns a Promise in react-router v7; the command `run`
  // signature is `() => void`, so wrap it in a void-returning closure rather
  // than handing the floating promise to the property.
  const go = useCallback(
    (path: string) => () => {
      void navigate(path);
    },
    [navigate],
  );

  // `forceLogout` clears the auth store, purges the query cache (so a
  // next sign-in cannot show the prior tenant's data), and redirects to
  // /login — fired whether the server logout succeeds or fails.
  const logoutMutation = useMutation({
    mutationFn: logoutRequest,
    onSettled: () => forceLogout(),
  });

  const commands = useMemo<Command[]>(
    () => [
      { id: "go-overview",    label: "Go to Dashboard",        hint: "/",            group: "Navigate",    icon: LayoutDashboard, run: go("/") },
      { id: "go-hypervisors", label: "Go to Hypervisors",      hint: "/hypervisors", group: "Navigate",    icon: Server,          run: go("/hypervisors") },
      { id: "go-vms",         label: "Go to Virtual Machines", hint: "/vms",         group: "Navigate",    icon: Monitor,         run: go("/vms") },
      { id: "go-migrations",  label: "Go to Migrations",       hint: "/migrations",  group: "Navigate",    icon: ArrowRightLeft,  run: go("/migrations") },
      { id: "go-reports",     label: "Go to Reports",          hint: "/reports",     group: "Navigate",    icon: BarChart3,       run: go("/reports") },
      { id: "go-users",       label: "Go to Users",            hint: "/users",       group: "Navigate",    icon: UsersIcon,       run: go("/users") },
      { id: "go-roles",       label: "Go to Roles",            hint: "/roles",       group: "Navigate",    icon: ShieldCheck,     run: go("/roles") },
      { id: "go-settings",    label: "Go to Settings",         hint: "/settings",    group: "Navigate",    icon: Settings2,       run: go("/settings") },
      {
        id: "toggle-theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        hint: theme === "dark" ? "Light" : "Dark",
        group: "Preferences",
        icon: theme === "dark" ? Sun : Moon,
        run: () => toggle(),
      },
      { id: "logout", label: "Log out", hint: "End session", group: "Session", icon: LogOut, run: () => logoutMutation.mutate() },
    ],
    // Depend on the stable `.mutate` reference, not the `logoutMutation`
    // object — TanStack Query returns a fresh result object every render,
    // so depending on it would defeat the memo entirely.
    [go, theme, toggle, logoutMutation.mutate],
  );

  // Commands matching the typed query — a case-insensitive substring match
  // over label and hint. With the query empty, every command shows.
  const filtered = useMemo<Command[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        (c.hint?.toLowerCase().includes(q) ?? false),
    );
  }, [commands, query]);

  useEffect(() => {
    const isMac = typeof navigator !== "undefined" && /mac/i.test(navigator.platform);
    const onKey = (event: KeyboardEvent) => {
      const mod = isMac ? event.metaKey : event.ctrlKey;
      if (mod && event.key.toLowerCase() === "k" && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        setOpen((value) => !value);
      } else if (event.key === "Escape" && open) {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  // Closing resets the query and selection so the next open starts clean.
  useEffect(() => {
    if (!open) {
      setSelected(0);
      setQuery("");
    }
  }, [open]);

  // A new query can shrink the result list below the current selection —
  // clamp it back to the first row so the highlight stays valid.
  useEffect(() => {
    setSelected(0);
  }, [query]);

  const runSelected = useCallback(() => {
    const command = filtered[selected];
    if (!command) return;
    close();
    queueMicrotask(() => command.run());
  }, [filtered, selected, close]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (filtered.length === 0) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((value) => (value + 1) % filtered.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((value) => (value - 1 + filtered.length) % filtered.length);
      } else if (event.key === "Enter") {
        event.preventDefault();
        runSelected();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, filtered.length, runSelected]);

  if (!open) return null;

  const groups = filtered.reduce<Record<string, Command[]>>((acc, command) => {
    (acc[command.group] ??= []).push(command);
    return acc;
  }, {});

  let runningIndex = -1;

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center pt-[12vh] px-4">
      <button
        type="button"
        aria-label="Close command palette"
        onClick={close}
        className="absolute inset-0"
        style={{
          background: "rgba(6, 11, 40, 0.55)",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
        }}
        tabIndex={-1}
      />
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="glass-card relative w-full max-w-[600px] overflow-hidden"
      >
        {/* The search input is the first focusable element, so the focus
            trap lands the caret here on open — and the keyboard nav effect
            still drives ↑/↓/↵ regardless of where focus sits. */}
        <header className="relative z-[1] h-12 px-3 flex items-center gap-2.5 border-b border-[var(--hairline)]">
          <Icon icon={Search} size={14} className="text-[var(--text-muted)] shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search commands…"
            aria-label="Search commands"
            aria-controls="cmdk-listbox"
            aria-activedescendant={
              filtered[selected]
                ? `cmd-opt-${filtered[selected].id}`
                : undefined
            }
            spellCheck={false}
            autoComplete="off"
            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
          />
          <div className="hidden sm:flex items-center gap-1.5 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)] shrink-0">
            <Kbd>↑↓</Kbd>
            <Kbd>↵</Kbd>
            <Kbd>Esc</Kbd>
          </div>
        </header>
        <div
          ref={listRef}
          id="cmdk-listbox"
          role="listbox"
          aria-label="Commands"
          className="relative z-[1] max-h-[60vh] overflow-y-auto py-2 outline-none"
        >
          {Object.entries(groups).map(([group, list]) => (
            <div key={group} className="px-2 pb-2">
              <div className="kicker px-3 pt-2 pb-1">{group}</div>
              {list.map((command) => {
                runningIndex += 1;
                const isSelected = runningIndex === selected;
                const currentIndex = runningIndex;
                return (
                  <button
                    key={command.id}
                    id={`cmd-opt-${command.id}`}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={-1}
                    onClick={runSelected}
                    onMouseEnter={() => setSelected(currentIndex)}
                    className={`w-full flex items-center gap-3 h-10 px-3 rounded-xl text-left transition-colors duration-200 ${
                      isSelected
                        ? "bg-[var(--surface-soft-strong)] text-[var(--text-primary)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--surface-soft)]"
                    }`}
                  >
                    <Icon
                      icon={command.icon}
                      size={14}
                      className={isSelected ? "text-[var(--accent-light)]" : ""}
                    />
                    <span className="flex-1 text-[13px] font-medium tracking-[0.005em]">
                      {command.label}
                    </span>
                    {command.hint && (
                      <span className="text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
                        {command.hint}
                      </span>
                    )}
                    {isSelected && (
                      <Icon
                        icon={ArrowRight}
                        size={12}
                        className="text-[var(--accent-light)]"
                      />
                    )}
                  </button>
                );
              })}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="px-5 py-8 text-center text-[13px] text-[var(--text-muted)]">
              No command matches “{query.trim()}”.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
