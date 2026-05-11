import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowRight,
  Home,
  LogOut,
  Monitor,
  Moon,
  Server,
  Sun,
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
      {
        id: "go-overview",
        label: "go to overview",
        hint: "/",
        group: "navigate",
        icon: Home,
        run: () => navigate("/"),
      },
      {
        id: "go-hypervisors",
        label: "go to hypervisors",
        hint: "/hypervisors",
        group: "navigate",
        icon: Server,
        run: () => navigate("/hypervisors"),
      },
      {
        id: "go-vms",
        label: "go to virtual machines",
        hint: "/vms",
        group: "navigate",
        icon: Monitor,
        run: () => navigate("/vms"),
      },
      {
        id: "toggle-theme",
        label: theme === "dark" ? "switch to light theme" : "switch to dark theme",
        hint: theme === "dark" ? "light" : "dark",
        group: "preferences",
        icon: theme === "dark" ? Sun : Moon,
        run: () => toggle(),
      },
      {
        id: "logout",
        label: "log out",
        hint: "end session",
        group: "session",
        icon: LogOut,
        run: () => logoutMutation.mutate(),
      },
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
        className="absolute inset-0 bg-[rgba(0,0,0,0.5)]"
        tabIndex={-1}
      />
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-[560px] bg-bg border border-line-strong rounded-sm shadow-[var(--shadow-hover)] overflow-hidden"
      >
        <header className="h-12 px-4 flex items-center justify-between border-b border-line bg-bg-elev">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <span>command palette</span>
          </div>
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
            <Kbd>↑↓</Kbd>
            navigate
            <span className="text-ink-faint">·</span>
            <Kbd>↵</Kbd>
            run
            <span className="text-ink-faint">·</span>
            <Kbd>esc</Kbd>
            close
          </div>
        </header>
        <div ref={listRef} className="max-h-[60vh] overflow-y-auto py-2">
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
                    type="button"
                    onClick={runSelected}
                    onMouseEnter={() => setSelected(currentIndex)}
                    className={`w-full flex items-center gap-3 h-10 px-3 rounded-sm text-left transition-colors duration-100 ${
                      isSelected
                        ? "bg-bg-elev-2 text-ink"
                        : "text-ink-muted hover:bg-bg-elev"
                    }`}
                  >
                    <Icon
                      icon={command.icon}
                      size={14}
                      className={isSelected ? "text-signal" : ""}
                    />
                    <span className="flex-1 font-mono text-[12px] lowercase tracking-[0.02em]">
                      {command.label}
                    </span>
                    {command.hint && (
                      <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
                        {command.hint}
                      </span>
                    )}
                    {isSelected && (
                      <Icon icon={ArrowRight} size={12} className="text-signal" />
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
