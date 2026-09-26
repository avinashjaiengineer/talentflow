import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Trash2, Upload, Users } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { api, type Candidate, type CandidateProfile } from "../api";
import IntakePanel from "../components/IntakePanel";
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
      <IntakePanel />
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
        </div>
        <Button variant="danger" onClick={onDelete}><Trash2 className="size-4" /> Delete</Button>
      </div>
      <ContactDetails c={c} />
      <div className="flex flex-wrap gap-1">{c.skills.map((s) => <Badge key={s}>{s}</Badge>)}</div>
      {c.profile && <ProfileDetails p={c.profile} />}
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
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Resume {c.resume_filename && `· ${c.resume_filename}`}</p>
          {c.has_original_file && (
            <a href={`/api/candidates/${c.id}/resume`} className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline">
              <Download className="size-3.5" /> Download original
            </a>
          )}
        </div>
        <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm text-slate-700">{c.resume_text}</pre>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{title}</p>
      {children}
    </div>
  );
}

/** Only http(s) links are clickable; "linkedin.com/in/x" gets https:// added. */
function safeHref(link: string): string | null {
  if (/^https?:\/\//i.test(link)) return link;
  if (/^[a-z][a-z0-9+.-]*:/i.test(link)) return null;
  return `https://${link}`;
}

function ProfileDetails({ p }: { p: CandidateProfile }) {
  const period = (start: string | null, end: string | null) => (start || end ? `${start ?? "?"} – ${end ?? "?"}` : null);
  return (
    <div className="space-y-4">
      {p.links.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {p.links.map((link) => {
            const href = safeHref(link);
            return href ? (
              <a key={link} href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">{link}</a>
            ) : (
              <span key={link} className="text-slate-500">{link}</span>
            );
          })}
        </div>
      )}
      {p.employment_history.length > 0 && (
        <Section title={`Work history${p.years_from_dates != null ? ` · ${p.years_from_dates} yrs from dates` : ""}`}>
          <ol className="space-y-2 border-l-2 border-slate-200 pl-4">
            {p.employment_history.map((job, i) => (
              <li key={i} className="text-sm">
                <p className="font-medium text-slate-800">
                  {job.title}
                  {job.company && <span className="font-normal text-slate-600"> · {job.company}</span>}
                </p>
                <p className="text-xs text-slate-500">{[period(job.start, job.end), job.location].filter(Boolean).join(" · ")}</p>
                {job.summary && <p className="mt-0.5 text-slate-600">{job.summary}</p>}
              </li>
            ))}
          </ol>
        </Section>
      )}
      {p.education.length > 0 && (
        <Section title="Education">
          <ul className="space-y-1 text-sm text-slate-700">
            {p.education.map((e, i) => (
              <li key={i}>
                {[e.degree, e.field].filter(Boolean).join(", ")}
                {e.institution && <span className="text-slate-500"> · {e.institution}</span>}
                {e.year && <span className="text-slate-500"> · {e.year}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {p.certifications.length > 0 && (
        <Section title="Certifications">
          <div className="flex flex-wrap gap-1">{p.certifications.map((x) => <Badge key={x} className="bg-violet-100 text-violet-700">{x}</Badge>)}</div>
        </Section>
      )}
      {p.projects.length > 0 && (
        <Section title="Projects">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{p.projects.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </Section>
      )}
    </div>
  );
}

function ContactDetails({ c }: { c: Candidate }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ email: c.email ?? "", phone: c.phone ?? "", location: c.location ?? "" });
  const save = useMutation({
    mutationFn: (body: Parameters<typeof api.updateCandidate>[1]) => api.updateCandidate(c.id, body),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries();
    },
  });
  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span>{c.email || <em className="text-slate-400">no email</em>}</span>
        <span>{c.phone || <em className="text-slate-400">no phone</em>}</span>
        {c.location && <span className="text-slate-500">{c.location}</span>}
        {c.do_not_call && <Badge className="bg-rose-100 text-rose-700">Do not call</Badge>}
        <button className="text-xs text-indigo-600 hover:underline" onClick={() => setEditing(true)}>Edit contact details</button>
      </div>
    );
  }
  return (
    <form
      className="grid gap-2 rounded-lg bg-slate-50 p-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ email: form.email || null, phone: form.phone || null, location: form.location || null });
      }}
    >
      <input className="input" type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      <input className="input" placeholder="Phone, e.g. +14155550100" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
      <input className="input" placeholder="Location" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input type="checkbox" checked={c.do_not_call} onChange={(e) => save.mutate({ do_not_call: e.target.checked })} />
        Do not call this candidate
      </label>
      <div className="flex gap-2 sm:justify-end">
        <Button type="button" variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Save</Button>
      </div>
      <div className="sm:col-span-3">
        <ErrorNote error={save.error} />
      </div>
    </form>
  );
}
