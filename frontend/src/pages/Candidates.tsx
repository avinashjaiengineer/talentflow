import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Trash2, Upload, Users } from "lucide-react";
import { useRef, useState } from "react";
import { api, type Candidate } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Modal, PageHeader, StageBadge, cn, timeAgo } from "../components/ui";

type UploadState = { name: string; status: "uploading" | "done" | "error"; message?: string };

export default function CandidatesPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [pasting, setPasting] = useState(false);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const { data: candidates, isLoading } = useQuery({ queryKey: ["candidates", q], queryFn: () => api.candidates(q) });

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    setUploads(list.map((f) => ({ name: f.name, status: "uploading" })));
    // Parse sequentially so each resume's LLM call doesn't compete for rate limit.
    for (const [i, file] of list.entries()) {
      try {
        await api.uploadResume(file);
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, status: "done" } : x)));
      } catch (e) {
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, status: "error", message: (e as Error).message } : x)));
      }
      qc.invalidateQueries({ queryKey: ["candidates"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    }
  }

  return (
    <>
      <PageHeader
        title="Talent pool"
        subtitle="Every candidate is parsed and embedded so the sourcing agent can find them by meaning"
        actions={
          <>
            <Button variant="secondary" onClick={() => setPasting(true)}><FileText className="size-4" /> Paste resume</Button>
            <Button onClick={() => fileInput.current?.click()}><Upload className="size-4" /> Upload resumes</Button>
          </>
        }
      />
      <input
        ref={fileInput}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md"
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) uploadFiles(e.target.files);
          e.target.value = "";
        }}
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
        }}
        className={cn(
          "mb-6 rounded-xl border-2 border-dashed p-5 text-center text-sm transition",
          dragging ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-slate-300 text-slate-500",
        )}
      >
        Drop PDF, DOCX, or TXT resumes here
        {uploads.length > 0 && (
          <ul className="mx-auto mt-3 max-w-md space-y-1 text-left">
            {uploads.map((u) => (
              <li key={u.name} className="flex justify-between gap-2 text-xs">
                <span className="truncate">{u.name}</span>
                <span className={u.status === "error" ? "text-rose-600" : u.status === "done" ? "text-emerald-600" : "text-slate-500"}>
                  {u.status === "uploading" ? "Parsing…" : u.status === "done" ? "Added" : u.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <input className="input mb-4 max-w-sm" placeholder="Search by name, title, or skill" value={q} onChange={(e) => setQ(e.target.value)} />

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !candidates?.length ? (
        <Empty icon={<Users className="size-8" />} title={q ? "No matches" : "Your talent pool is empty"}>
          {q ? "Try a different search." : "Upload resumes to get started."}
        </Empty>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="hidden px-4 py-3 font-medium md:table-cell">Skills</th>
                <th className="hidden px-4 py-3 font-medium sm:table-cell">Experience</th>
                <th className="hidden px-4 py-3 font-medium lg:table-cell">Added</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {candidates.map((c) => (
                <tr key={c.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setSelected(c.id)}>
                  <td className="px-4 py-3">
                    <p className="font-medium">{c.name}</p>
                    <p className="line-clamp-1 text-xs text-slate-500">{c.headline}</p>
                  </td>
                  <td className="hidden px-4 py-3 md:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {c.skills.slice(0, 5).map((s) => <Badge key={s}>{s}</Badge>)}
                      {c.skills.length > 5 && <span className="text-xs text-slate-500">+{c.skills.length - 5}</span>}
                    </div>
                  </td>
                  <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">{c.years_experience != null ? `${c.years_experience} yrs` : "–"}</td>
                  <td className="hidden px-4 py-3 text-slate-500 lg:table-cell">{timeAgo(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <PasteResume open={pasting} onClose={() => setPasting(false)} />
      <Modal open={!!selected} onClose={() => setSelected(null)} title="Candidate" wide>
        {selected && <CandidateDetail id={selected} onDeleted={() => setSelected(null)} />}
      </Modal>
    </>
  );
}

function PasteResume({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const create = useMutation({
    mutationFn: () => api.createCandidate({ resume_text: text }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidates"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      setText("");
      onClose();
    },
  });
  return (
    <Modal open={open} onClose={onClose} title="Paste a resume">
      <textarea className="input min-h-64 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the full resume text…" />
      <ErrorNote error={create.error} />
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => create.mutate()} disabled={text.trim().length < 20} loading={create.isPending}>Add candidate</Button>
      </div>
    </Modal>
  );
}

function CandidateDetail({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["candidate", id], queryFn: () => api.candidate(id) });
  const { data: apps = [] } = useQuery({ queryKey: ["candidate", id, "applications"], queryFn: () => api.candidateApplications(id) });
  const remove = useMutation({
    mutationFn: () => api.deleteCandidate(id),
    onSuccess: () => {
      qc.invalidateQueries();
      onDeleted();
    },
  });
  if (!c) return <p className="text-sm text-slate-500">Loading…</p>;
  return <CandidateBody c={c} apps={apps} onDelete={() => confirm(`Delete ${c.name}?`) && remove.mutate()} />;
}

function CandidateBody({ c, apps, onDelete }: { c: Candidate; apps: Awaited<ReturnType<typeof api.candidateApplications>>; onDelete: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{c.name}</h3>
          <p className="text-sm text-slate-500">{c.headline}</p>
          <p className="text-xs text-slate-500">{[c.email, c.phone, c.location].filter(Boolean).join(" · ")}</p>
        </div>
        <Button variant="danger" onClick={onDelete}><Trash2 className="size-4" /> Delete</Button>
      </div>
      <div className="flex flex-wrap gap-1">{c.skills.map((s) => <Badge key={s}>{s}</Badge>)}</div>
      {apps.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Pipelines</p>
          <ul className="space-y-1">
            {apps.map((a) => (
              <li key={a.id} className="flex items-center justify-between text-sm">
                <span>{a.job_title}</span>
                <StageBadge stage={a.stage} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Resume {c.resume_filename && `· ${c.resume_filename}`}</p>
        <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm text-slate-700">{c.resume_text}</pre>
      </div>
    </div>
  );
}
