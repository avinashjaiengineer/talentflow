import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Briefcase, CheckSquare, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type Stage } from "../api";
import EventList from "../components/EventList";
import { Card, PageHeader } from "../components/ui";

const FUNNEL: { label: string; stages: Stage[] }[] = [
  { label: "Sourced", stages: ["sourced", "screening"] },
  { label: "Needs review", stages: ["screened"] },
  { label: "Outreach", stages: ["outreach", "contacted"] },
  { label: "Interviewing", stages: ["scheduling", "interview_scheduled", "evaluation"] },
  { label: "Offer decision", stages: ["evaluated"] },
  { label: "Offers", stages: ["offer"] },
];

export default function Dashboard() {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 5_000 });
  const { data: events = [] } = useQuery({ queryKey: ["events", "recent"], queryFn: () => api.events({ limit: 15 }), refetchInterval: 5_000 });
  const stages = stats?.stages ?? {};
  const counts = FUNNEL.map((f) => f.stages.reduce((n, s) => n + (stages[s] ?? 0), 0));
  const max = Math.max(1, ...counts);

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Your hiring pipeline at a glance" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat to="/jobs" icon={<Briefcase className="size-5" />} label="Open jobs" value={stats?.open_jobs} />
        <Stat to="/candidates" icon={<Users className="size-5" />} label="Candidates in pool" value={stats?.candidates} />
        <Stat to="/approvals" icon={<CheckSquare className="size-5" />} label="Waiting for you" value={stats?.pending_approvals} highlight={!!stats?.pending_approvals} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="p-5">
          <h2 className="mb-4 font-semibold">Pipeline</h2>
          <div className="space-y-3">
            {FUNNEL.map((f, i) => (
              <div key={f.label} className="grid grid-cols-[120px_1fr_40px] items-center gap-3 text-sm">
                <span className="text-slate-600">{f.label}</span>
                <div className="h-6 rounded-md bg-slate-100">
                  <div className="h-6 rounded-md bg-indigo-500 transition-all" style={{ width: `${(counts[i] / max) * 100}%` }} />
                </div>
                <span className="text-right font-medium tabular-nums">{counts[i]}</span>
              </div>
            ))}
            <p className="pt-1 text-xs text-slate-500">{stages.rejected ?? 0} rejected{stages.failed ? ` · ${stages.failed} failed` : ""}</p>
          </div>
        </Card>
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold">Agent activity</h2>
            <Link to="/activity" className="text-sm text-indigo-600 hover:underline">View all</Link>
          </div>
          <EventList events={events} compact />
        </Card>
      </div>

      {stats && stats.open_jobs === 0 && (
        <Card className="mt-6 p-5 text-sm text-slate-600">
          <p className="font-medium text-slate-800">Getting started</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>Upload resumes to the <Link className="text-indigo-600 hover:underline" to="/candidates">talent pool</Link>.</li>
            <li>Create a <Link className="text-indigo-600 hover:underline" to="/jobs">job</Link> and click <em>Source candidates</em>.</li>
            <li>Review screened candidates in <Link className="text-indigo-600 hover:underline" to="/approvals">Approvals</Link>; the agents handle the rest.</li>
          </ol>
          <p className="mt-2">Or load demo data: <code className="rounded bg-slate-100 px-1">docker compose exec app python -m app.seed</code></p>
        </Card>
      )}
    </>
  );
}

function Stat({ to, icon, label, value, highlight }: { to: string; icon: ReactNode; label: string; value?: number; highlight?: boolean }) {
  return (
    <Link to={to}>
      <Card className={`flex items-center gap-4 p-5 transition hover:shadow-md ${highlight ? "border-amber-300 bg-amber-50" : ""}`}>
        <div className={`rounded-lg p-2.5 ${highlight ? "bg-amber-100 text-amber-700" : "bg-indigo-50 text-indigo-600"}`}>{icon}</div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{value ?? "–"}</p>
          <p className="text-sm text-slate-500">{label}</p>
        </div>
      </Card>
    </Link>
  );
}

