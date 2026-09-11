import {
  Activity,
  ArchiveX,
  Box,
  ChevronRight,
  ClipboardList,
  History,
  KeyRound,
  Layers,
  ListTodo,
  LockKeyhole,
  LogOut,
  Menu,
  Plus,
  RadioTower,
  Server,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useAction } from "../components/Management";
import type { UserRole } from "../lib/api";
import { isDemoAccount } from "../lib/demo";

const roleNames: Record<UserRole, string> = {
  ADMIN: "Admin",
  PUBLISHER: "Publisher",
  PRODUCER: "Producer",
  WORKER: "Worker",
};
const sections: Record<UserRole, [string, string, LucideIcon][]> = {
  ADMIN: [
    ["jobs", "Jobs", ListTodo],
    ["dead-letters", "Dead letters", ArchiveX],
    ["queues", "Queues", Layers],
    ["workers", "Workers", Server],
    ["releases", "Releases", Box],
    ["users", "Accounts", Users],
    ["audit", "Action history", History],
  ],
  PUBLISHER: [
    ["releases", "Job Types & releases", Box],
    ["jobs", "Jobs", ListTodo],
  ],
  PRODUCER: [
    ["jobs", "Jobs", ListTodo],
    ["submit", "Submit a job", Plus],
    ["keys", "API keys", KeyRound],
  ],
  WORKER: [
    ["agents", "Worker Agents", Server],
    ["assignments", "Assignments", ClipboardList],
    ["attempts", "Attempt history", History],
  ],
};
export function Brand() {
  return (
    <div>
      <div className="brand">
        <span className="brand-mark">
          <RadioTower size={23} />
        </span>
        Relay
      </div>
      <p className="brand-subtitle">Distributed job queue</p>
    </div>
  );
}
export function DashboardLayout({ role }: { role: UserRole }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const action = useAction();
  const root = `/${role.toLowerCase()}`;
  const section = location.pathname.split("/")[2];
  const label =
    sections[role].find(([path]) => path === section)?.[1] ?? "Overview";
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        menu.current?.focus();
      }
      if (event.key === "Tab") {
        const items = Array.from(
          sidebar.current?.querySelectorAll<HTMLElement>("a, button, select") ??
            [],
        ).filter((node) => node.getClientRects().length);
        const first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", handler);
    };
  }, [open]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {open && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => {
            setOpen(false);
            menu.current?.focus();
          }}
        />
      )}
      <aside
        id="navigation"
        ref={sidebar}
        className={`sidebar ${open ? "is-open" : ""}`}
        aria-label="Workspace navigation"
        role={open ? "dialog" : undefined}
        aria-modal={open ? true : undefined}
      >
        <div className="flex items-center justify-between">
          <Brand />
          <button
            className="icon-button mobile-menu"
            aria-label="Close navigation"
            onClick={() => {
              setOpen(false);
              menu.current?.focus();
            }}
          >
            <X size={18} />
          </button>
        </div>
        <div className="role-switch">
          <label htmlFor="role-switch">Role</label>
          <select
            id="role-switch"
            className="input"
            value={role}
            onChange={(event) =>
              navigate(`/${event.target.value.toLowerCase()}`)
            }
          >
            {user?.roles.map((r) => (
              <option key={r} value={r}>
                {roleNames[r]}
              </option>
            ))}
          </select>
        </div>
        <p className="nav-label">Workspace</p>
        <nav
          className="sidebar-nav"
          aria-label={`${roleNames[role]} navigation`}
        >
          <NavLink
            end
            to={root}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <Activity size={16} />
            Overview
          </NavLink>
          {sections[role].map(([path, name, Icon]) => (
            <NavLink
              key={path}
              to={`${root}/${path}`}
              className={({ isActive }) =>
                `nav-item ${isActive ? "active" : ""}`
              }
            >
              <Icon size={16} />
              {name}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-account">
          <p className="account-name">{user?.display_name}</p>
          <p className="account-email" title={user?.email}>
            {user?.email}
          </p>
          {!isDemoAccount(user?.email) && (
            <NavLink to="/password" className="nav-item">
              <LockKeyhole size={15} />
              Change password
            </NavLink>
          )}
          <button
            className="nav-item w-full"
            disabled={action.busy}
            onClick={() =>
              void action.run(async () => {
                await logout();
                navigate("/login");
              }, "Signed out")
            }
          >
            <LogOut size={15} />
            Sign out
          </button>
        </div>
      </aside>
      <div className="app-body">
        <div className="topbar">
          <button
            ref={menu}
            className="icon-button mobile-menu"
            aria-label="Open navigation"
            aria-expanded={open}
            aria-controls="navigation"
            onClick={() => setOpen(true)}
          >
            <Menu size={19} />
          </button>
          <span>{roleNames[role]}</span>
          <ChevronRight size={12} />
          <span className="location">{label}</span>
          {location.pathname.split("/").length > 3 && (
            <>
              <ChevronRight size={12} />
              <span>Details</span>
            </>
          )}
        </div>
        <main id="main-content" className="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
