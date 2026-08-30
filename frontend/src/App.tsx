import { Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense } from "react";

import { useAuth } from "./auth/AuthProvider";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { FullPageLoader } from "./components/Feedback";
import { DashboardLayout } from "./layout/DashboardLayout";
import type { UserRole } from "./lib/api";
import { LoginPage } from "./pages/LoginPage";

const AdminOverviewPage = lazy(() => import("./pages/AdminOverviewPage").then((module) => ({ default: module.AdminOverviewPage })));
const RoleOverviewPage = lazy(() => import("./pages/RoleOverviewPage").then((module) => ({ default: module.RoleOverviewPage })));
const WorkerOverviewPage = lazy(() => import("./pages/WorkerOverviewPage").then((module) => ({ default: module.WorkerOverviewPage })));

const destinations: Record<UserRole, string> = { ADMIN: "/admin", PUBLISHER: "/publisher", PRODUCER: "/producer", WORKER: "/worker" };

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <FullPageLoader />;
  if (!user) return <Navigate to="/login" replace />;
  const role = (["ADMIN", "PUBLISHER", "PRODUCER", "WORKER"] as UserRole[]).find((item) => user.roles.includes(item));
  return role ? <Navigate to={destinations[role]} replace /> : <Navigate to="/login" replace />;
}

export function App() {
  return (
    <Suspense fallback={<FullPageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}><Route index element={<HomeRedirect />} /></Route>
        <Route element={<ProtectedRoute role="ADMIN" />}><Route element={<DashboardLayout role="ADMIN" />}><Route path="admin" element={<AdminOverviewPage />} /></Route></Route>
        <Route element={<ProtectedRoute role="PUBLISHER" />}><Route element={<DashboardLayout role="PUBLISHER" />}><Route path="publisher" element={<RoleOverviewPage role="publisher" />} /></Route></Route>
        <Route element={<ProtectedRoute role="PRODUCER" />}><Route element={<DashboardLayout role="PRODUCER" />}><Route path="producer" element={<RoleOverviewPage role="producer" />} /></Route></Route>
        <Route element={<ProtectedRoute role="WORKER" />}><Route element={<DashboardLayout role="WORKER" />}><Route path="worker" element={<WorkerOverviewPage />} /></Route></Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
