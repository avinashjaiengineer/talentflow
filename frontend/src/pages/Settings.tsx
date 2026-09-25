import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, type User } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, ErrorNote, Modal, PageHeader, timeAgo } from "../components/ui";

export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader title="Settings" subtitle={`Signed in as ${user.email}`} />
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <ChangePassword />
        {user.role === "admin" && <Users me={user} />}
      </div>
    </>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    change.mutate();
  };
  return (
    <Card className="h-fit p-5">
      <h2 className="mb-4 font-semibold">Change password</h2>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Current password</label>
          <input type="password" autoComplete="current-password" required className="input" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div>
          <label className="label">New password (10+ characters)</label>
          <input type="password" autoComplete="new-password" minLength={10} required className="input" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <ErrorNote error={change.error} />
        {change.isSuccess && <p className="text-sm text-emerald-700">Password changed. Other sessions were signed out.</p>}
        <Button type="submit" loading={change.isPending}>Update password</Button>
      </form>
    </Card>
  );
}

function Users({ me }: { me: User }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const { data: users = [] } = useQuery({ queryKey: ["users"], queryFn: api.users });
  const update = useMutation({
    mutationFn: (v: { id: string; body: Parameters<typeof api.updateUser>[1] }) => api.updateUser(v.id, v.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold">Team</h2>
        <Button variant="secondary" onClick={() => setAdding(true)}><UserPlus className="size-4" /> Add user</Button>
      </div>
      <ul className="divide-y divide-slate-100">
        {users.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {u.name} {u.id === me.id && <span className="text-slate-500">(you)</span>}
              </p>
              <p className="text-xs text-slate-500">
                {u.email} · {u.last_login_at ? `last seen ${timeAgo(u.last_login_at)}` : "never signed in"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!u.is_active && <Badge className="bg-rose-100 text-rose-700">Deactivated</Badge>}
              <select
                className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                value={u.role}
                disabled={u.id === me.id}
                onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as User["role"] } })}
              >
                <option value="recruiter">Recruiter</option>
                <option value="admin">Admin</option>
              </select>
              {u.id !== me.id && (
                <Button variant={u.is_active ? "danger" : "secondary"} onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                  {u.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <ErrorNote error={update.error} />
      <AddUser open={adding} onClose={() => setAdding(false)} />
    </Card>
  );
}

function AddUser({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "recruiter" as User["role"] });
  const create = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setForm({ name: "", email: "", password: "", role: "recruiter" });
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <Modal open={open} onClose={onClose} title="Add a team member">
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Name</label>
          <input required className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">Email</label>
          <input type="email" required className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div>
          <label className="label">Temporary password (10+ characters; share it privately)</label>
          <input type="text" minLength={10} required autoComplete="off" className="input font-mono" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div>
          <label className="label">Role</label>
          <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as User["role"] })}>
            <option value="recruiter">Recruiter: run pipelines and make decisions</option>
            <option value="admin">Admin: also manages the team</option>
          </select>
        </div>
        <ErrorNote error={create.error} />
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Add user</Button>
        </div>
      </form>
    </Modal>
  );
}
