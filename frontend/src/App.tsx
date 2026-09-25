import { useQuery } from "@tanstack/react-query";
import { Activity, Briefcase, CheckSquare, LayoutDashboard, LogOut, Menu, Settings, Users, Workflow } from "lucide-react";
import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, type Health } from "./api";
import { useAuth } from "./auth";
import { cn } from "./components/ui";
import ActivityPage from "./pages/Activity";
import ApprovalsPage from "./pages/Approvals";
import CandidatesPage from "./pages/Candidates";
import Dashboard from "./pages/Dashboard";
import JobDetail from "./pages/JobDetail";
import JobsPage from "./pages/Jobs";
import SettingsPage from "./pages/Settings";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/jobs", label: "Jobs", icon: Briefcase },
  { to: "/candidates", label: "Talent pool", icon: Users },
  { to: "/approvals", label: "Approvals", icon: CheckSquare, badge: true },
  { to: "/activity", label: "Agent activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, logout } = useAuth();
  const { data: health } = useQuery({ queryKey: ["system"], queryFn: api.system, staleTime: 60_000 });
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 5_000 });

  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end, badge }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setMenuOpen(false)}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
              isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )
          }
        >
          <Icon className="size-4" />
          <span className="flex-1">{label}</span>
          {badge && !!stats?.pending_approvals && (
            <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">{stats.pending_approvals}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-white p-4 lg:flex lg:flex-col">
        <Logo />
        <div className="mt-6 flex-1">{nav}</div>
        <SystemInfo health={health} />
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-200 pt-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user.name}</p>
            <p className="truncate text-xs text-slate-500">{user.role}</p>
          </div>
          <button onClick={logout} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800" title="Sign out" aria-label="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <Logo />
        <button onClick={() => setMenuOpen((o) => !o)} className="rounded-md p-2 text-slate-600 hover:bg-slate-100" aria-label="Menu">
          <Menu className="size-5" />
        </button>
      </header>
      {menuOpen && (
        <div className="border-b border-slate-200 bg-white p-3 lg:hidden">
          {nav}
          <button onClick={logout} className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">
            <LogOut className="size-4" /> Sign out ({user.name})
          </button>
        </div>
      )}

      <main className="min-w-0 flex-1">
        {health?.llm.startsWith("mock") && (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-800">
            <strong>Offline mode:</strong> agents are using built-in heuristics. Set <code className="rounded bg-amber-100 px-1">ANTHROPIC_API_KEY</code> and
            restart the backend to use Claude.
          </div>
        )}
        <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/:jobId" element={<JobDetail />} />
            <Route path="/candidates" element={<CandidatesPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<p className="text-slate-500">Page not found.</p>} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="flex size-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
        <Workflow className="size-4" />
      </div>
      <span className="text-lg font-semibold tracking-tight">TalentFlow</span>
    </div>
  );
}

function SystemInfo({ health }: { health?: Health }) {
  if (!health) return null;
  const models = [...new Set(Object.values(health.models))];
  return (
    <div className="space-y-1 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
      <div className="flex items-center gap-1.5">
        <span className={cn("size-2 rounded-full", health.llm === "anthropic" ? "bg-emerald-500" : "bg-amber-500")} />
        <span className="font-medium text-slate-700">{health.llm === "anthropic" ? "Claude connected" : "Offline mode"}</span>
      </div>
      {models.length > 0 && <div>Model: {models.join(", ")}</div>}
      <div>Version {health.version}</div>
      <div>Embeddings: {health.embeddings}</div>
      <div>Email: {health.integrations.email === "graph" ? "Outlook" : "not connected"}</div>
      <div>Calendar: {health.integrations.calendar === "graph" ? "Outlook + Teams" : "not connected"}</div>
      <div>Calls: {health.integrations.voice === "twilio" ? "Twilio" : "simulated"}</div>
      <div>Database: {health.database}</div>
    </div>
  );
}
