import { createBrowserRouter, Navigate } from "react-router-dom";
import Styleguide from "@/pages/Styleguide";
import Login from "@/pages/Login";
import { ProtectedRoute } from "@/routes/ProtectedRoute";
import { PublicOnlyRoute } from "@/routes/PublicOnlyRoute";

function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg text-ink p-6">
      <div className="border border-line p-6 max-w-md">
        <div className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
          404 — ROUTE INTROUVABLE
        </div>
        <p className="mt-2 text-[13px]">
          Cette page n'est pas encore disponible. Voir{" "}
          <a href="/styleguide" className="text-info underline">
            /styleguide
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
      { path: "/", element: <Navigate to="/styleguide" replace /> },
      { path: "/styleguide", element: <Styleguide /> },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
