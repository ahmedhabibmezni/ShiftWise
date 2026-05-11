import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { Footer } from "@/components/shell/Footer";
import { CommandPalette } from "@/components/shell/CommandPalette";

const ROUTE_TITLES: Record<string, string> = {
  "/": "overview",
  "/hypervisors": "hypervisors",
  "/vms": "virtual machines",
  "/users": "users",
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

  return (
    <div className="min-h-[100dvh] bg-bg text-ink flex flex-col relative">
      <span aria-hidden className="sw-grain" />
      <div className="flex flex-1 min-h-0 relative z-[2]">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header title={title} timestamp={timestamp} />
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
