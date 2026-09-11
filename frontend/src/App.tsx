import { InteractionProvider } from "./components/InteractionProvider";
import { Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense } from "react";

import { useAuth } from "./auth/AuthProvider";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { FullPageLoader } from "./components/Feedback";
import { DashboardLayout } from "./layout/DashboardLayout";
import type { UserRole } from "./lib/api";
import { AccountsPage, PasswordPage, AuditPage } from "./pages/AccountsPage";
import { ReleasesPage, ReleaseDetailPage } from "./pages/ReleasesPage";
import { JobsPage, JobDetailPage, SubmitPage } from "./pages/JobsPage";
import {
  WorkerActivityPage,
  AgentsPage,
  AdminWorkersPage,
  QueuesPage,
  KeysPage,
} from "./pages/OperationsPage";
import { LoginPage } from "./pages/LoginPage";

const AdminOverviewPage = lazy(() =>
  import("./pages/AdminOverviewPage").then((module) => ({
    default: module.AdminOverviewPage,
  })),
);
const RoleOverviewPage = lazy(() =>
  import("./pages/RoleOverviewPage").then((module) => ({
    default: module.RoleOverviewPage,
  })),
);
const WorkerOverviewPage = lazy(() =>
  import("./pages/WorkerOverviewPage").then((module) => ({
    default: module.WorkerOverviewPage,
  })),
);

const destinations: Record<UserRole, string> = {
  ADMIN: "/admin",
  PUBLISHER: "/publisher",
  PRODUCER: "/producer",
  WORKER: "/worker",
};

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <FullPageLoader />;
  if (!user) return <Navigate to="/login" replace />;
  const role = (
    ["ADMIN", "PUBLISHER", "PRODUCER", "WORKER"] as UserRole[]
  ).find((item) => user.roles.includes(item));
  return role ? (
    <Navigate to={destinations[role]} replace />
  ) : (
    <Navigate to="/login" replace />
  );
}

export function App() {
  return (
    <InteractionProvider>
      <AppRoutes />
    </InteractionProvider>
  );
}

function AppRoutes() {
  return (
    <Suspense fallback={<FullPageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route index element={<HomeRedirect />} />
          <Route path="password" element={<PasswordPage />} />
        </Route>
        <Route element={<ProtectedRoute role="ADMIN" />}>
          <Route element={<DashboardLayout role="ADMIN" />}>
            <Route path="admin" element={<AdminOverviewPage />} />
            <Route path="admin/users" element={<AccountsPage />} />
            <Route path="admin/audit" element={<AuditPage />} />
            <Route
              path="admin/releases"
              element={<ReleasesPage role="admin" />}
            />
            <Route
              path="admin/releases/:id"
              element={<ReleaseDetailPage role="admin" />}
            />
            <Route path="admin/jobs" element={<JobsPage role="admin" />} />
            <Route
              path="admin/jobs/:id"
              element={<JobDetailPage role="admin" />}
            />
            <Route
              path="admin/dead-letters"
              element={<JobsPage role="admin" deadLetters />}
            />
            <Route path="admin/workers" element={<AdminWorkersPage />} />
            <Route path="admin/queues" element={<QueuesPage />} />
          </Route>
        </Route>
        <Route element={<ProtectedRoute role="PUBLISHER" />}>
          <Route element={<DashboardLayout role="PUBLISHER" />}>
            <Route
              path="publisher"
              element={<RoleOverviewPage role="publisher" />}
            />
            <Route
              path="publisher/releases"
              element={<ReleasesPage role="publisher" />}
            />
            <Route
              path="publisher/releases/:id"
              element={<ReleaseDetailPage role="publisher" />}
            />
            <Route
              path="publisher/jobs"
              element={<JobsPage role="publisher" />}
            />
            <Route
              path="publisher/jobs/:id"
              element={<JobDetailPage role="publisher" />}
            />
          </Route>
        </Route>
        <Route element={<ProtectedRoute role="PRODUCER" />}>
          <Route element={<DashboardLayout role="PRODUCER" />}>
            <Route
              path="producer"
              element={<RoleOverviewPage role="producer" />}
            />
            <Route path="producer/submit" element={<SubmitPage />} />
            <Route
              path="producer/jobs"
              element={<JobsPage role="producer" />}
            />
            <Route
              path="producer/jobs/:id"
              element={<JobDetailPage role="producer" />}
            />
            <Route path="producer/keys" element={<KeysPage />} />
          </Route>
        </Route>
        <Route element={<ProtectedRoute role="WORKER" />}>
          <Route element={<DashboardLayout role="WORKER" />}>
            <Route path="worker" element={<WorkerOverviewPage />} />
            <Route path="worker/agents" element={<AgentsPage />} />
            <Route
              path="worker/assignments"
              element={<WorkerActivityPage kind="assignments" />}
            />
            <Route
              path="worker/attempts"
              element={<WorkerActivityPage kind="attempts" />}
            />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
