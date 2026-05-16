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
import { useAuthStore } from "@/store/auth";
import { logout as logoutRequest } from "@/api/auth";

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
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const clearSession = useAuthStore((s) => s.clearSession);
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const listRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  const logoutMutation = useMutation({
    mutationFn: logoutRequest,
    onSettled: () => clearSession(),
  });

  const commands = useMemo<Command[]>(
    () => [
      { id: "go-overview",    label: "Go to Dashboard",        hint: "/",            group: "Navigate",    icon: LayoutDashboard, run: () => navigate("/") },
      { id: "go-hypervisors", label: "Go to Hypervisors",      hint: "/hypervisors", group: "Navigate",    icon: Server,          run: () => navigate("/hypervisors") },
      { id: "go-vms",         label: "Go to Virtual Machines", hint: "/vms",         group: "Navigate",    icon: Monitor,         run: () => navigate("/vms") },
      { id: "go-migrations",  label: "Go to Migrations",       hint: "/migrations",  group: "Navigate",    icon: ArrowRightLeft,  run: () => navigate("/migrations") },
      { id: "go-reports",     label: "Go to Reports",          hint: "/reports",     group: "Navigate",    icon: BarChart3,       run: () => navigate("/reports") },
      { id: "go-users",       label: "Go to Users",            hint: "/users",       group: "Navigate",    icon: UsersIcon,       run: () => navigate("/users") },
      { id: "go-roles",       label: "Go to Roles",            hint: "/roles",       group: "Navigate",    icon: ShieldCheck,     run: () => navigate("/roles") },
      { id: "go-settings",    label: "Go to Settings",         hint: "/settings",    group: "Navigate",    icon: Settings2,       run: () => navigate("/settings") },
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
    [navigate, theme, toggle, logoutMutation],
  );

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

  useEffect(() => {
    if (!open) setSelected(0);
  }, [open]);

  const runSelected = useCallback(() => {
    const command = commands[selected];
    if (!command) return;
    close();
    queueMicrotask(() => command.run());
  }, [commands, selected, close]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((value) => (value + 1) % commands.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((value) => (value - 1 + commands.length) % commands.length);
      } else if (event.key === "Enter") {
        event.preventDefault();
        runSelected();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, commands.length, runSelected]);

  if (!open) return null;

  const groups = commands.reduce<Record<string, Command[]>>((acc, command) => {
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
        <header className="relative z-[1] h-12 px-4 flex items-center justify-between border-b border-[var(--hairline)]">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-secondary)]">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <span>Command palette</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
            <Kbd>↑↓</Kbd>
            Navigate
            <span>·</span>
            <Kbd>↵</Kbd>
            Run
            <span>·</span>
            <Kbd>Esc</Kbd>
            Close
          </div>
        </header>
        <div
          ref={listRef}
          role="listbox"
          aria-label="Commands"
          tabIndex={0}
          aria-activedescendant={`cmd-opt-${commands[selected]?.id ?? ""}`}
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
        </div>
      </div>
    </div>
  );
}
