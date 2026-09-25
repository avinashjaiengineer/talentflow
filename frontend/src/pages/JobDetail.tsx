import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Search, Sparkles, Trash2, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Application, type Stage } from "../api";
import ApplicationPanel from "../components/ApplicationPanel";
import { Badge, Button, Card, Empty, ErrorNote, Modal, PageHeader, STAGE_META, ScoreBadge, StageBadge } from "../components/ui";

const COLUMNS: { title: string; stages: Stage[] }[] = [
  { title: "Sourced & screening", stages: ["sourced", "screening"] },
  { title: "Needs review", stages: ["screened"] },
  { title: "Outreach", stages: ["outreach", "contacted"] },
  { title: "Interview", stages: ["scheduling", "interview_scheduled", "evaluation"] },
  { title: "Decision", stages: ["evaluated", "offer"] },
];

export default function JobDetail() {
  const { jobId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [showRejected, setShowRejected] = useState(false);

  const { data: job, error } = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
  const { data: apps = [] } = useQuery({
    queryKey: ["job", jobId, "applications"],
    queryFn: () => api.jobApplications(jobId),
    refetchInterval: (q) => (q.state.data?.some((a) => STAGE_META[a.stage].working) ? 1500 : 5000),
  });

  const [sourceTaskId, setSourceTaskId] = useState<number | null>(null);
  const source = useMutation({
    mutationFn: () => api.source(jobId, 10),
    onSuccess: (task) => setSourceTaskId(task.id),
  });
  const { data: sourceTask } = useQuery({
    queryKey: ["task", sourceTaskId],
    queryFn: () => api.task(sourceTaskId!),
    enabled: sourceTaskId !== null,
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1500),
  });
  const sourcing = source.isPending || (!!sourceTask && ["queued", "running"].includes(sourceTask.status));
  useEffect(() => {
    if (sourceTask?.status === "succeeded") qc.invalidateQueries();
  }, [sourceTask?.status, qc]);

  const remove = useMutation({
    mutationFn: () => api.deleteJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries();
      navigate("/jobs");
    },
  });
  const toggleStatus = useMutation({
    mutationFn: () => api.updateJob(jobId, { status: job?.status === "open" ? "closed" : "open" }),
    onSuccess: () => qc.invalidateQueries(),
  });

  const rejected = apps.filter((a) => a.stage === "rejected" || a.stage === "failed");

  if (error) return <ErrorNote error={error} />;
  if (!job) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <>
      <Link to="/jobs" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> Jobs
      </Link>
      <PageHeader
        title={job.title}
        subtitle={[job.department, job.location, job.status === "closed" && "Closed"].filter(Boolean).join(" · ")}
        actions={
          <>
            <Button variant="secondary" onClick={() => setAdding(true)}><UserPlus className="size-4" /> Add candidate</Button>
            <Button onClick={() => source.mutate()} loading={sourcing} disabled={job.status === "closed" || sourcing}>
              <Sparkles className="size-4" /> Source candidates
            </Button>
          </>
        }
      />
      {sourceTask && (
        <p className={`mb-4 rounded-lg px-3 py-2 text-sm ${sourceTask.status === "failed" ? "bg-rose-50 text-rose-700" : "bg-indigo-50 text-indigo-800"}`}>
          {sourceTask.status === "queued" || sourceTask.status === "running"
            ? "The sourcing agent is searching your talent pool…"
            : sourceTask.status === "failed"
              ? `Sourcing failed: ${sourceTask.last_error}`
              : sourceTask.result?.count
                ? `The sourcing agent found ${sourceTask.result.count} new candidates. The screening agent is reviewing them now.`
                : "No new matching candidates in the talent pool. Upload more resumes to widen the search."}
        </p>
      )}
      <ErrorNote error={source.error} />

      <details className="mb-6 rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <summary className="cursor-pointer font-medium text-slate-700">Job description & requirements</summary>
        <p className="mt-3 whitespace-pre-wrap text-slate-600">{job.description}</p>
        <div className="mt-3 flex flex-wrap gap-1">{job.requirements.map((r) => <Badge key={r}>{r}</Badge>)}</div>
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" onClick={() => toggleStatus.mutate()} loading={toggleStatus.isPending}>
            {job.status === "open" ? "Close job" : "Reopen job"}
          </Button>
          <Button variant="danger" onClick={() => confirm(`Delete "${job.title}" and its whole pipeline?`) && remove.mutate()}>
            <Trash2 className="size-4" /> Delete
          </Button>
        </div>
      </details>

      {apps.length === 0 ? (
        <Empty icon={<Search className="size-8" />} title="No candidates in this pipeline yet">
          Click <strong>Source candidates</strong> to let the sourcing agent search your talent pool by meaning, not just keywords.
        </Empty>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4 pb-2">
          <div className="grid min-w-[1000px] grid-cols-5 gap-3">
            {COLUMNS.map((col) => {
              const items = apps.filter((a) => col.stages.includes(a.stage));
              return (
                <div key={col.title} className="rounded-xl bg-slate-100/70 p-2">
                  <div className="flex items-center justify-between px-2 py-1.5">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{col.title}</h3>
                    <span className="text-xs text-slate-500">{items.length}</span>
                  </div>
                  <div className="space-y-2">
                    {items.map((a) => <AppCard key={a.id} app={a} onClick={() => setSelected(a.id)} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {rejected.length > 0 && (
        <div className="mt-6">
          <button className="text-sm text-slate-500 hover:text-slate-800" onClick={() => setShowRejected((s) => !s)}>
            {showRejected ? "Hide" : "Show"} {rejected.length} rejected
          </button>
          {showRejected && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {rejected.map((a) => <AppCard key={a.id} app={a} onClick={() => setSelected(a.id)} />)}
            </div>
          )}
        </div>
      )}

      <Modal open={!!selected} onClose={() => setSelected(null)} title="Candidate" wide>
        {selected && <ApplicationPanel applicationId={selected} />}
      </Modal>
      <AddCandidate jobId={jobId} open={adding} onClose={() => setAdding(false)} existing={apps} />
    </>
  );
}

function AppCard({ app, onClick }: { app: Application; onClick: () => void }) {
  return (
    <button onClick={onClick} className="w-full text-left">
      <Card className="p-3 transition hover:border-indigo-300 hover:shadow-md">
        <div className="flex items-start justify-between gap-2">
          <p className="truncate text-sm font-medium">{app.candidate.name}</p>
          <ScoreBadge score={app.screening_score} />
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{app.candidate.headline}</p>
        <div className="mt-2 flex items-center justify-between">
          <StageBadge stage={app.stage} />
          {app.error && <span className="text-xs font-medium text-rose-600">Error</span>}
        </div>
      </Card>
    </button>
  );
}

function AddCandidate({ jobId, open, onClose, existing }: { jobId: string; open: boolean; onClose: () => void; existing: Application[] }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const { data: candidates = [] } = useQuery({ queryKey: ["candidates", q], queryFn: () => api.candidates(q), enabled: open });
  const inPipeline = useMemo(() => new Set(existing.map((a) => a.candidate.id)), [existing]);
  const add = useMutation({
    mutationFn: (candidateId: string) => api.addToJob(jobId, candidateId),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <Modal open={open} onClose={onClose} title="Add a candidate from the talent pool">
      <input className="input mb-3" placeholder="Search by name, title, or skill" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
        {candidates.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{c.name}</p>
              <p className="truncate text-xs text-slate-500">{c.headline}</p>
            </div>
            {inPipeline.has(c.id) ? (
              <span className="text-xs text-slate-500">In pipeline</span>
            ) : (
              <Button variant="secondary" onClick={() => add.mutate(c.id)} loading={add.isPending && add.variables === c.id}>Add & screen</Button>
            )}
          </li>
        ))}
        {!candidates.length && <li className="py-6 text-center text-sm text-slate-500">No candidates found.</li>}
      </ul>
      <ErrorNote error={add.error} />
    </Modal>
  );
}
