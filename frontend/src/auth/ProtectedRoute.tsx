import { Navigate, Outlet, useLocation } from "react-router-dom";

import { type UserRole } from "../lib/api";
import { useAuth } from "./AuthProvider";
import { FullPageLoader } from "../components/Feedback";

export function ProtectedRoute({ role }: { role?: UserRole }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullPageLoader />;
  if (!user)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.password_change_required && location.pathname !== "/password")
    return <Navigate to="/password" replace />;
  if (role && !user.roles.includes(role)) return <Navigate to="/" replace />;
  return <Outlet />;
}
