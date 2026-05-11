import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { Footer } from "@/components/shell/Footer";
import { RoleStripe } from "@/components/shell/RoleStripe";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { usePrimaryRole } from "@/lib/permissions";
import { getRoleTheme } from "@/lib/role-theme";

const ROUTE_TITLES: Record<string, string> = {
  "/": "overview",
  "/hypervisors": "hypervisors",
  "/vms": "virtual machines",
  "/migrations": "migrations",
  "/reports": "reports",
  "/users": "users",
  "/roles": "roles",
  "/settings": "settings",
  "/styleguide": "styleguide",
};

function useCurrentTime() {
  const [now, setNow] = useState(() => formatTime(new Date()));
  useEffect(() => {
    const id = window.setInterval(() => setNow(formatTime(new Date())), 1_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

function formatTime(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

export function AppLayout() {
  const location = useLocation();
  const title =
    ROUTE_TITLES[location.pathname] ?? (location.pathname.replace(/^\//, "") || "overview");
  const timestamp = useCurrentTime();
  const role = usePrimaryRole();
  const theme = getRoleTheme(role);

  // Propagate the role accent at the document root so any element in the
  // app can reach it through `var(--role-accent)` — Sidebar brand, focus
  // outlines, drawer headers, anything that wants to reflect the operator's
  // privilege level without duplicating the role-theme switch.
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--role-accent", theme.accentColor);
    root.style.setProperty("--role-accent-tint", theme.accentTint);
    root.dataset.role = theme.role;
    return () => {
      root.style.removeProperty("--role-accent");
      root.style.removeProperty("--role-accent-tint");
      delete root.dataset.role;
    };
  }, [theme.role, theme.accentColor, theme.accentTint]);

  return (
    <div className="h-[100dvh] bg-bg text-ink flex flex-col relative overflow-hidden">
      <span aria-hidden className="sw-grain" />
      <div className="flex flex-1 min-h-0 relative z-[2]">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header title={title} timestamp={timestamp} />
          <RoleStripe />
          <main className="flex-1 overflow-auto">
            <Outlet />
          </main>
          <Footer />
        </div>
      </div>
      <CommandPalette />
    </div>
  );
}
