"use client";

import { Loader2, UserPlus } from "lucide-react";
import { useMemo, useState, useTransition } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  inputClass,
} from "@/components/ui/primitives";
import { timeAgo } from "@/lib/utils/format";
import { inviteAdmin, revokeAdmin, updateAdmin } from "./actions";

export type AdminRow = {
  id: string;
  email: string;
  name: string | null;
  role: string;
  role_label: string;
  permissions: string[];
  is_pending: boolean;
  is_active: boolean;
  last_seen_at: string | null;
};

export type Catalogue = {
  permissions: { key: string; label: string }[];
  groups: { title: string; permissions: string[] }[];
  roles: { key: string; label: string; description: string; permissions: string[] }[];
};

export function AdminManager({
  admins,
  catalogue,
  currentAdminId,
}: {
  admins: AdminRow[];
  catalogue: Catalogue;
  currentAdminId: string;
}) {
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Administrators"
          description="Everyone who can sign in to this console, and what each of them can do."
          action={
            <Button size="sm" onClick={() => setInviting((value) => !value)}>
              <UserPlus className="h-4 w-4" aria-hidden />
              Add someone
            </Button>
          }
        />

        {inviting ? (
          <InviteForm catalogue={catalogue} onDone={() => setInviting(false)} />
        ) : null}

        <ul>
          {admins.map((admin) => (
            <li key={admin.id} className="border-b border-default last:border-0">
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    <span className="truncate">{admin.name ?? admin.email}</span>
                    {admin.is_pending ? (
                      <Badge tone="warning">Hasn&apos;t signed in yet</Badge>
                    ) : null}
                    {admin.id === currentAdminId ? <Badge tone="accent">You</Badge> : null}
                  </p>
                  <p className="truncate text-sm text-muted">
                    {admin.email} · {admin.role_label} ·{" "}
                    {admin.permissions.length} permission
                    {admin.permissions.length === 1 ? "" : "s"}
                    {admin.last_seen_at ? ` · last seen ${timeAgo(admin.last_seen_at)}` : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setEditing(editing === admin.id ? null : admin.id)}
                  >
                    {editing === admin.id ? "Close" : "Edit access"}
                  </Button>
                  <RevokeButton admin={admin} isSelf={admin.id === currentAdminId} />
                </div>
              </div>

              {editing === admin.id ? (
                <EditForm
                  admin={admin}
                  catalogue={catalogue}
                  onDone={() => setEditing(null)}
                />
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ── Permission picker, shared by invite and edit ──────────────────────────

function PermissionPicker({
  catalogue,
  selected,
  onChange,
}: {
  catalogue: Catalogue;
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const labels = useMemo(
    () => new Map(catalogue.permissions.map((p) => [p.key, p.label])),
    [catalogue.permissions],
  );

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  return (
    <fieldset className="space-y-4">
      <legend className="text-sm font-medium">Permissions</legend>
      {catalogue.groups.map((group) => (
        <div key={group.title}>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
            {group.title}
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {group.permissions.map((key) => (
              <label key={key} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.has(key)}
                  onChange={() => toggle(key)}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]"
                />
                <span>{labels.get(key) ?? key}</span>
              </label>
            ))}
          </div>
        </div>
      ))}
    </fieldset>
  );
}

function RoleSelect({
  catalogue,
  role,
  onPick,
}: {
  catalogue: Catalogue;
  role: string;
  onPick: (role: string, permissions: string[]) => void;
}) {
  const current = catalogue.roles.find((r) => r.key === role);
  return (
    <Field
      label="Role"
      htmlFor="role"
      hint={
        current?.description ??
        "Picking a role ticks its usual permissions. You can then adjust them."
      }
    >
      <select
        id="role"
        value={role}
        onChange={(event) => {
          const picked = catalogue.roles.find((r) => r.key === event.target.value);
          if (picked) onPick(picked.key, picked.permissions);
        }}
        className={inputClass}
      >
        {catalogue.roles.map((r) => (
          <option key={r.key} value={r.key}>
            {r.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

function InviteForm({ catalogue, onDone }: { catalogue: Catalogue; onDone: () => void }) {
  const fallback = catalogue.roles[0];
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState(fallback?.key ?? "support");
  const [selected, setSelected] = useState<Set<string>>(
    new Set(fallback?.permissions ?? []),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    startTransition(async () => {
      const result = await inviteAdmin(email, name, role, [...selected]);
      if (result.ok) onDone();
      else setError(result.error);
    });
  }

  return (
    <div className="space-y-4 border-b border-default bg-surface-muted px-5 py-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Email address" htmlFor="email" hint="They sign in with this.">
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={inputClass}
            placeholder="name@drop.co.ke"
            autoFocus
          />
        </Field>
        <Field label="Name" htmlFor="name" hint="Optional, but it makes the audit log readable.">
          <input
            id="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={inputClass}
          />
        </Field>
      </div>

      <RoleSelect
        catalogue={catalogue}
        role={role}
        onPick={(nextRole, permissions) => {
          setRole(nextRole);
          setSelected(new Set(permissions));
        }}
      />

      <PermissionPicker catalogue={catalogue} selected={selected} onChange={setSelected} />

      {error ? <p role="alert" className="text-sm text-[var(--danger)]">{error}</p> : null}

      <div className="flex gap-2">
        <Button onClick={submit} disabled={pending || !email.trim() || selected.size === 0}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Grant access
        </Button>
        <Button variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
      </div>
      <p className="text-xs text-muted">
        Access applies the next time they sign in. We don&apos;t say whether this
        address already has a Drop account.
      </p>
    </div>
  );
}

function EditForm({
  admin,
  catalogue,
  onDone,
}: {
  admin: AdminRow;
  catalogue: Catalogue;
  onDone: () => void;
}) {
  const [role, setRole] = useState(admin.role);
  const [selected, setSelected] = useState<Set<string>>(new Set(admin.permissions));
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    startTransition(async () => {
      const result = await updateAdmin(admin.id, role, [...selected]);
      if (result.ok) onDone();
      else setError(result.error);
    });
  }

  return (
    <div className="space-y-4 border-t border-default bg-surface-muted px-5 py-5">
      <RoleSelect
        catalogue={catalogue}
        role={role}
        onPick={(nextRole, permissions) => {
          setRole(nextRole);
          setSelected(new Set(permissions));
        }}
      />
      <PermissionPicker catalogue={catalogue} selected={selected} onChange={setSelected} />

      {error ? <p role="alert" className="text-sm text-[var(--danger)]">{error}</p> : null}

      <div className="flex gap-2">
        <Button onClick={submit} disabled={pending || selected.size === 0}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Save changes
        </Button>
        <Button variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function RevokeButton({ admin, isSelf }: { admin: AdminRow; isSelf: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    // A destructive, immediate action gets a confirmation naming the person —
    // "are you sure" with no subject is what gets clicked through.
    const confirmed = window.confirm(
      `Remove ${admin.name ?? admin.email} from this console?\n\n` +
        "They lose access on their next request. Everything they've already done stays in the audit log.",
    );
    if (!confirmed) return;

    setError(null);
    startTransition(async () => {
      const result = await revokeAdmin(admin.id);
      if (!result.ok) setError(result.error);
    });
  }

  return (
    <div className="text-right">
      <Button
        size="sm"
        variant="ghost"
        onClick={submit}
        // The server refuses this too; disabling it just avoids offering an
        // action that always fails.
        disabled={pending || isSelf}
        title={isSelf ? "You can't remove your own access" : undefined}
        className="text-[var(--danger)]"
      >
        {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        Remove
      </Button>
      {error ? <p role="alert" className="mt-1 text-xs text-[var(--danger)]">{error}</p> : null}
    </div>
  );
}
