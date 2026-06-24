import { useCallback, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { MobileNav } from "@/components/shell/MobileNav";
import { Header } from "@/components/shell/Header";
import { Footer } from "@/components/shell/Footer";
import { CommandPalette } from "@/components/shell/CommandPalette";

const ROUTE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/hypervisors": "Hypervisors",
  "/vms": "Virtual Machines",
  "/migrations": "Migrations",
  "/reports": "Reports",
  "/users": "Users",
  "/roles": "Roles",
  "/settings": "Settings",
  "/infrastructure": "Infrastructure",
  "/styleguide": "Styleguide",
};

// Breadcrumb parent labels mirror the Sidebar's section headings exactly,
// so the breadcrumb and the nav agree on where each page lives.
const PARENT_PATH: Record<string, string> = {
  "/": "Operations",
  "/hypervisors": "Operations",
  "/vms": "Operations",
  "/migrations": "Operations",
  "/reports": "Operations",
  "/users": "Administration",
  "/roles": "Administration",
  "/settings": "Administration",
  "/infrastructure": "Administration",
  "/styleguide": "Pages",
};

/**
 * AppLayout — the Vision UI shell: a full-height navigation rail flush to the
 * left viewport edge, with the header, content, and footer in a padded column
 * beside it.
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │┌────────┐┌─ 24px padding ────────────────────────┐    │
 *   ││Sidebar ││  Header (topbar)                      │    │
 *   ││ rail   ││  ──────────────────────────────────── │    │
 *   ││ (full  ││  <Outlet />                           │    │
 *   ││ height,││                                       │    │
 *   ││ edge-  ││  Footer                               │    │
 *   ││ flush) ││                                       │    │
 *   │└────────┘└───────────────────────────────────────┘    │
 *   └──────────────────────────────────────────────────────┘
 *
 *   Body radial orbs (declared on body::before in base.css) bleed brand
 *   colour through the 120 px backdrop-blur on the rail and every glass card.
 *
 *   ⚠️  Don't wrap this layout in any element that has opacity/transform/
 *       filter/will-change/mask — that creates a backdrop-root and silently
 *       breaks the blur on the rail and every descendant card.
 */
export function AppLayout() {
  const location = useLocation();
  const titleFromPath = location.pathname.replace(/^\//, "");
  const fallbackTitle = titleFromPath
    ? titleFromPath.charAt(0).toUpperCase() + titleFromPath.slice(1)
    : "Dashboard";
  const title = ROUTE_TITLES[location.pathname] ?? fallbackTitle;
  const parent = PARENT_PATH[location.pathname] ?? "Pages";

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const openMobileNav = useCallback(() => setMobileNavOpen(true), []);
  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);

  return (
    <div className="min-h-[100dvh] flex">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 p-4 md:p-6 gap-6">
        <Header title={title} parent={parent} onMenuClick={openMobileNav} />
        <main className="flex-1 min-h-0">
          <Outlet />
        </main>
        <Footer />
      </div>
      <MobileNav open={mobileNavOpen} onClose={closeMobileNav} />
      <CommandPalette />
    </div>
  );
}
