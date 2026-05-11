import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { Footer } from "@/components/shell/Footer";

const ROUTE_TITLES: Record<string, { title: string; sidebarKey: string }> = {
  "/": { title: "overview", sidebarKey: "overview" },
  "/styleguide": { title: "styleguide", sidebarKey: "overview" },
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
  const route = ROUTE_TITLES[location.pathname] ?? {
    title: location.pathname.replace(/^\//, "") || "overview",
    sidebarKey: "overview",
  };
  const timestamp = useCurrentTime();

  return (
    <div className="min-h-screen bg-bg text-ink flex flex-col">
      <div className="flex flex-1 min-h-0">
        <Sidebar active={route.sidebarKey} />
        <div className="flex-1 flex flex-col min-w-0">
          <Header title={route.title} timestamp={timestamp} />
          <main className="flex-1 overflow-auto">
            <Outlet />
          </main>
          <Footer />
        </div>
      </div>
    </div>
  );
}
