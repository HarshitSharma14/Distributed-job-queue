import { Activity, Boxes, ChevronRight, LogOut, RadioTower } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import type { UserRole } from "../lib/api";

const roleRoutes: Record<UserRole, { path: string; label: string }> = {
  ADMIN: { path: "/admin", label: "Admin" },
  PUBLISHER: { path: "/publisher", label: "Publisher" },
  PRODUCER: { path: "/producer", label: "Producer" },
  WORKER: { path: "/worker", label: "Worker" },
};

export function DashboardLayout({ role }: { role: UserRole }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const current = roleRoutes[role];
  return (
    <div className="min-h-screen bg-[#f6f7f2] text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col bg-[#101827] px-4 py-5 text-white lg:flex">
        <div className="flex items-center gap-3 px-2">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-500 shadow-lg shadow-indigo-950/30"><RadioTower className="h-5 w-5" /></div>
          <div><p className="font-semibold tracking-tight">Relay</p><p className="text-[11px] text-slate-400">Distributed queue</p></div>
        </div>
        <div className="mt-9 px-2 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Workspace</div>
        <nav className="mt-3 space-y-1">
          <NavLink to={current.path} className="flex items-center gap-3 rounded-xl bg-white/10 px-3 py-2.5 text-sm font-medium"><Activity className="h-4 w-4 text-indigo-300" />Overview</NavLink>
        </nav>
        <div className="mt-8 px-2 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Your roles</div>
        <nav className="mt-3 space-y-1">
          {user?.roles.map((userRole) => {
            const item = roleRoutes[userRole];
            return <NavLink key={userRole} to={item.path} className={({ isActive }) => `flex items-center justify-between rounded-xl px-3 py-2 text-sm ${isActive ? "text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}><span className="flex items-center gap-3"><Boxes className="h-4 w-4" />{item.label}</span><ChevronRight className="h-3.5 w-3.5" /></NavLink>;
          })}
        </nav>
        <div className="mt-auto rounded-2xl border border-white/10 bg-white/5 p-3">
          <p className="truncate text-sm font-medium">{user?.display_name}</p>
          <p className="mt-0.5 truncate text-xs text-slate-400">{user?.email}</p>
          <button className="mt-3 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-slate-300 hover:bg-white/10" onClick={() => void logout().then(() => navigate("/login"))}><LogOut className="h-3.5 w-3.5" />Sign out</button>
        </div>
      </aside>
      <div className="lg:pl-64">
        <div className="border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
          <div className="flex items-center justify-between"><span className="font-semibold">Relay</span><button aria-label="Sign out" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" onClick={() => void logout().then(() => navigate("/login"))}><LogOut className="h-4 w-4" /></button></div>
          <nav className="mt-2 flex gap-1 overflow-x-auto">{user?.roles.map((userRole) => { const item = roleRoutes[userRole]; return <NavLink key={userRole} to={item.path} className={({ isActive }) => `whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-500"}`}>{item.label}</NavLink>; })}</nav>
        </div>
        <main className="mx-auto max-w-[1440px] px-5 py-8 md:px-8 md:py-10"><Outlet /></main>
      </div>
    </div>
  );
}
