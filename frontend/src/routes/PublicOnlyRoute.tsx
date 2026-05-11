import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store/auth";

export function PublicOnlyRoute() {
  const user = useAuthStore((s) => s.user);

  if (user) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
