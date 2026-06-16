import { Suspense, lazy, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";
import Login from "@/pages/Login";
import NotFound from "@/pages/NotFound";
import { ProtectedRoute } from "@/routes/ProtectedRoute";
import { PublicOnlyRoute } from "@/routes/PublicOnlyRoute";
import { AppLayout } from "@/app/AppLayout";
import { RouteFallback } from "@/components/ui/RouteFallback";

// Route-level code-splitting: each authenticated page becomes its own chunk so
// the initial bundle no longer ships the whole app at once. `Login` and
// `NotFound` stay eager — they are tiny and on the first-paint / fallback path.
const Styleguide = lazy(() => import("@/pages/Styleguide"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Hypervisors = lazy(() => import("@/pages/Hypervisors"));
const Vms = lazy(() => import("@/pages/Vms"));
const Migrations = lazy(() => import("@/pages/Migrations"));
const Reports = lazy(() => import("@/pages/Reports"));
const Roles = lazy(() => import("@/pages/Roles"));
const Settings = lazy(() => import("@/pages/Settings"));
const Users = lazy(() => import("@/pages/Users"));
const Infrastructure = lazy(() => import("@/pages/Infrastructure"));

function lazyRoute(node: ReactNode): ReactNode {
  return <Suspense fallback={<RouteFallback />}>{node}</Suspense>;
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
      { path: "/styleguide", element: lazyRoute(<Styleguide />) },
      {
        element: <AppLayout />,
        children: [
          { path: "/", element: lazyRoute(<Dashboard />) },
          { path: "/hypervisors", element: lazyRoute(<Hypervisors />) },
          { path: "/vms", element: lazyRoute(<Vms />) },
          { path: "/migrations", element: lazyRoute(<Migrations />) },
          { path: "/reports", element: lazyRoute(<Reports />) },
          { path: "/users", element: lazyRoute(<Users />) },
          { path: "/roles", element: lazyRoute(<Roles />) },
          { path: "/infrastructure", element: lazyRoute(<Infrastructure />) },
          { path: "/settings", element: lazyRoute(<Settings />) },
        ],
      },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
