import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, MapPin, Plus } from "lucide-react";
import { type ChangeEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Modal, PageHeader } from "../components/ui";

export default function JobsPage() {
  const [open, setOpen] = useState(false);
  const { data: jobs, isLoading } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs });

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle="Each job has its own pipeline run by the agents"
        actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> New job</Button>}
      />
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !jobs?.length ? (
        <Empty icon={<Briefcase className="size-8" />} title="No jobs yet">
          Create a job, then let the sourcing agent find matching candidates in your talent pool.
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {jobs.map((job) => {
            const total = Object.values(job.stage_counts).reduce((a, b) => a + b, 0);
            const review = (job.stage_counts.screened ?? 0) + (job.stage_counts.evaluated ?? 0);
            return (
              <Link key={job.id} to={`/jobs/${job.id}`}>
                <Card className="h-full p-5 transition hover:border-indigo-300 hover:shadow-md">
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="font-semibold">{job.title}</h2>
                    <Badge className={job.status === "open" ? "bg-emerald-100 text-emerald-700" : undefined}>{job.status}</Badge>
                  </div>
                  <p className="mt-1 flex items-center gap-1 text-sm text-slate-500">
                    {job.department}
                    {job.location && <><MapPin className="ml-1 size-3.5" /> {job.location}</>}
                  </p>
                  <p className="mt-3 line-clamp-2 text-sm text-slate-600">{job.description}</p>
                  <div className="mt-4 flex gap-4 text-sm">
                    <span><strong className="tabular-nums">{total}</strong> <span className="text-slate-500">in pipeline</span></span>
                    {review > 0 && <span className="text-amber-700"><strong>{review}</strong> need review</span>}
                    {job.stage_counts.offer ? <span className="text-emerald-700"><strong>{job.stage_counts.offer}</strong> offers</span> : null}
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
      <JobForm open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function JobForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", department: "", location: "", description: "", requirements: "" });
  const create = useMutation({
    mutationFn: () =>
      api.createJob({
        title: form.title,
        department: form.department || null,
        location: form.location || null,
        description: form.description,
        requirements: form.requirements.split("\n").map((r) => r.trim()).filter(Boolean),
      }),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      onClose();
      navigate(`/jobs/${job.id}`);
    },
  });
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <Modal open={open} onClose={onClose} title="New job">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div>
          <label className="label">Title</label>
          <input className="input" required value={form.title} onChange={set("title")} placeholder="Senior Backend Engineer" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Department</label>
            <input className="input" value={form.department} onChange={set("department")} placeholder="Engineering" />
          </div>
          <div>
            <label className="label">Location</label>
            <input className="input" value={form.location} onChange={set("location")} placeholder="Remote" />
          </div>
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input min-h-28" required value={form.description} onChange={set("description")} placeholder="What the role does and why it matters" />
        </div>
        <div>
          <label className="label">Requirements (one per line)</label>
          <textarea className="input min-h-24" value={form.requirements} onChange={set("requirements")} placeholder={"5+ years backend development\nPython\nPostgreSQL"} />
        </div>
        <ErrorNote error={create.error} />
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create job</Button>
        </div>
      </form>
    </Modal>
  );
}
