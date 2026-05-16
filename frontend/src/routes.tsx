import { createBrowserRouter } from "react-router-dom";
import Styleguide from "@/pages/Styleguide";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Hypervisors from "@/pages/Hypervisors";
import Vms from "@/pages/Vms";
import Migrations from "@/pages/Migrations";
import Reports from "@/pages/Reports";
import Roles from "@/pages/Roles";
import Settings from "@/pages/Settings";
import Users from "@/pages/Users";
import { ProtectedRoute } from "@/routes/ProtectedRoute";
import { PublicOnlyRoute } from "@/routes/PublicOnlyRoute";
import { AppLayout } from "@/app/AppLayout";

function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="glass-card max-w-md p-6">
        <div className="kicker mb-2">404 · Page Not Found</div>
        <p className="mt-2 text-[13px] text-[var(--text-secondary)]">
          That page does not exist. It may have moved, or the link is wrong.{" "}
          <a href="/" className="text-[var(--accent-light)] hover:text-[var(--accent-primary)] font-bold">
            Go to dashboard →
          </a>
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
          { path: "/migrations", element: <Migrations /> },
          { path: "/reports", element: <Reports /> },
          { path: "/users", element: <Users /> },
          { path: "/roles", element: <Roles /> },
          { path: "/settings", element: <Settings /> },
        ],
      },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
