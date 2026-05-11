import { createBrowserRouter } from "react-router-dom";
import Styleguide from "@/pages/Styleguide";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Hypervisors from "@/pages/Hypervisors";
import Vms from "@/pages/Vms";
import { ProtectedRoute } from "@/routes/ProtectedRoute";
import { PublicOnlyRoute } from "@/routes/PublicOnlyRoute";
import { AppLayout } from "@/app/AppLayout";

function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg text-ink p-6">
      <div className="border border-line p-6 max-w-md">
        <div className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
          404 — ROUTE INTROUVABLE
        </div>
        <p className="mt-2 text-[13px]">
          Cette page n'est pas encore disponible. Voir{" "}
          <a href="/" className="text-info underline">
            /
          </a>
          .
        </p>
      </div>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    element: <PublicOnlyRoute />,
    children: [{ path: "/login", element: <Login /> }],
  },
  {
    element: <ProtectedRoute />,
    children: [
      // Styleguide ships its own shell (it is a kitchen-sink demo) and must
      // sit outside AppLayout to avoid a double Sidebar/Header/Footer.
      { path: "/styleguide", element: <Styleguide /> },
      {
        element: <AppLayout />,
        children: [
          { path: "/", element: <Dashboard /> },
          { path: "/hypervisors", element: <Hypervisors /> },
          { path: "/vms", element: <Vms /> },
        ],
      },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
