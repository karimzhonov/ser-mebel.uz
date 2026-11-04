import { useState } from "react";
import { KeyRound, Lock, Pencil, Plus, Trash2, UserMinus, UserPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList } from "@/api/hooks";
import type { StaffGroup, StaffUser } from "@/api/types";
import { AccessEditor } from "@/components/AccessEditor";
import { PhoneLink } from "@/components/domain";
import { Badge, Button, Card, Confirm, DataTable, Empty, Field, IconButton, Input, Modal, PageLoader, SearchInput, Segmented } from "@/components/ui";

/** members of a group as the API returns them (a list, or a page) */
type Member = Pick<StaffUser, "id" | "phone" | "name"> & Partial<Pick<StaffUser, "telegram_id" | "is_active">>;

/** why a locked group (the keeper «Omborchi») can't be edited here */
export const LOCKED_HINT = "Omborchi Ombor sahifasida boshqariladi";

export const memberCount = (g: StaffGroup) => g.member_count ?? g.members_count ?? g.user_count ?? 0;

/** «Guruhlar (rollar)» — superuser only: a group is a role (Operator, Dizayner, Narxchi …);
 * every member gets its section levels and task flags. */
export function GroupsPanel() {
  const { data: groups, isFetching } = useAll<StaffGroup>("groups");
  const [form, setForm] = useState<{ id?: number; name: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [del, setDel] = useState<StaffGroup | null>(null);
  const [open, setOpen] = useState<{ group: StaffGroup; tab: "access" | "members" } | null>(null);

  const save = useAction(() => (form!.id ? api.patch(`/groups/${form!.id}/`, { name: form!.name.trim() }) : api.post("/groups/", { name: form!.name.trim() })), {
    success: "Saqlandi",
    invalidate: ["groups", "users"],
    onSuccess: () => setForm(null),
  });
  const remove = useAction((id: number) => api.delete(`/groups/${id}/`), {
    success: "Guruh o'chirildi",
    invalidate: ["groups", "users"],
    onSuccess: () => setDel(null),
  });

  return (
    <>
      <Card
        padded={false}
        title="Guruhlar (rollar)"
        actions={
          <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setForm({ name: "" }))}>
            Guruh
          </Button>
        }
      >
        <p className="muted border-b border-slate-100 px-5 py-3 text-xs dark:border-slate-800">
          Guruh — bu rol: Operator, O'lcham oluvchi, Dizayner, Narxchi, Bosh menejer, Menejer, Konstruktor … Guruhga berilgan bo'lim huquqlari va vazifa belgilari
          undagi har bir xodimga o'tadi. Telegram'ga ulangan xodimga shu rol bo'yicha xabarlar bot orqali boradi.
        </p>
        {groups && !groups.length ? (
          <Empty title="Guruhlar yo'q" text="«Guruh» tugmasi bilan birinchi rolni yarating." />
        ) : (
          <DataTable
            rows={groups}
            loading={isFetching}
            rowKey={(g) => g.id}
            onRowClick={(g) => setOpen({ group: g, tab: "access" })}
            columns={[
              {
                key: "name",
                header: "Nomi",
                cell: (g) => (
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{g.name}</span>
                    {g.locked && (
                      <span title={LOCKED_HINT}>
                        <Badge tone="warn" dot={false}>
                          <Lock className="mr-1 inline h-3 w-3" />
                          Ombor
                        </Badge>
                      </span>
                    )}
                  </span>
                ),
              },
              { key: "members", header: "Xodimlar", cell: (g) => <Badge dot={false}>{memberCount(g)} ta</Badge> },
              {
                key: "x",
                header: "",
                cell: (g) => (
                  <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                    <IconButton label="Huquqlar" onClick={() => setOpen({ group: g, tab: "access" })}>
                      <KeyRound className="h-4 w-4" />
                    </IconButton>
                    <IconButton label="Xodimlar" onClick={() => setOpen({ group: g, tab: "members" })}>
                      <UserPlus className="h-4 w-4" />
                    </IconButton>
                    <IconButton
                      label={g.locked ? LOCKED_HINT : "Nomini o'zgartirish"}
                      disabled={g.locked}
                      className="disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={() => (setErrors({}), setForm({ id: g.id, name: g.name }))}
                    >
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                    <IconButton label={g.locked ? LOCKED_HINT : "O'chirish"} disabled={g.locked} className="disabled:cursor-not-allowed disabled:opacity-40" onClick={() => setDel(g)}>
                      <Trash2 className={g.locked ? "h-4 w-4" : "h-4 w-4 text-rose-600"} />
                    </IconButton>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? "Guruh nomini o'zgartirish" : "Yangi guruh (rol)"}
        size="sm"
        footer={
          <Button disabled={!form?.name.trim()} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Saqlash
          </Button>
        }
      >
        {form && (
          <Field label="Nomi" error={errors.name ?? errors.non_field_errors}>
            <Input autoFocus value={form.name} placeholder="Masalan: Narxchi" onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
        )}
      </Modal>

      {open && <GroupModal group={groups?.find((g) => g.id === open.group.id) ?? open.group} tab={open.tab} onTab={(tab) => setOpen({ ...open, tab })} onClose={() => setOpen(null)} />}

      <Confirm
        open={!!del}
        onClose={() => setDel(null)}
        onConfirm={() => remove.mutate(del!.id)}
        loading={remove.isPending}
        variant="danger"
        confirmLabel="O'chirish"
        title="Guruhni o'chirish"
        text={
          del && memberCount(del) > 0 ? (
            <>
              <b>{del.name}</b> guruhida {memberCount(del)} ta xodim bor — avval ularni guruhdan chiqaring.
            </>
          ) : (
            <>
              <b>{del?.name}</b> guruhi o'chiriladi.
            </>
          )
        }
      />
    </>
  );
}

function GroupModal({ group, tab, onTab, onClose }: { group: StaffGroup; tab: "access" | "members"; onTab: (t: "access" | "members") => void; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={`Rol — ${group.name}`} size="lg">
      <Segmented
        className="mb-4"
        value={tab}
        onChange={onTab}
        options={[
          { value: "access", label: "Huquqlar" },
          { value: "members", label: "Xodimlar", count: memberCount(group) },
        ]}
      />
      {group.locked && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <Lock className="h-4 w-4 shrink-0" />
          <span>
            {LOCKED_HINT}.{" "}
            <Link to="/warehouse/settings" className="font-medium underline">
              Ochish
            </Link>
          </span>
        </div>
      )}
      {group.locked ? (
        tab === "access" ? (
          <p className="muted text-sm">Bu rolning huquqlari bu yerda o'zgartirilmaydi.</p>
        ) : (
          <Members group={group} readOnly />
        )
      ) : tab === "access" ? (
        <AccessEditor path={`/groups/${group.id}/access/`} subject="group" invalidate={["groups", "users"]} />
      ) : (
        <Members group={group} />
      )}
    </Modal>
  );
}

function Members({ group, readOnly }: { group: StaffGroup; readOnly?: boolean }) {
  const path = `/groups/${group.id}/members/`;
  const { data, isLoading } = useGet<Member[] | { results: Member[] }>(path);
  const members: Member[] = Array.isArray(data) ? data : data?.results ?? [];
  const [search, setSearch] = useState("");
  const found = useList<StaffUser>("users", { search }, !readOnly && search.trim().length >= 2);
  const ids = new Set(members.map((m) => m.id));
  const change = useAction((body: { add?: number[]; remove?: number[] }) => api.post(path, body), {
    success: "Saqlandi",
    invalidate: ["groups", "users"],
  });
  const person = (m: Member) => m.name || m.phone;

  return (
    <div className="space-y-4">
      {!readOnly && (
        <div>
          <div className="label">Xodim qo'shish</div>
          <SearchInput value={search} onChange={setSearch} placeholder="Ism yoki telefon (kamida 2 belgi)" />
          {search.trim().length >= 2 && (
            <ul className="mt-2 max-h-56 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
              {found.isFetching && !found.data ? (
                <li className="px-3 py-2"><PageLoader /></li>
              ) : !found.data?.results.length ? (
                <li className="muted px-3 py-2 text-sm">Topilmadi</li>
              ) : (
                found.data.results.map((u) => (
                  <li key={u.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{u.name || "—"}</span> <span className="muted">{u.phone}</span>
                    </span>
                    {ids.has(u.id) ? (
                      <Badge tone="ok" dot={false}>guruhda</Badge>
                    ) : (
                      <Button size="sm" variant="outline" icon={<UserPlus className="h-4 w-4" />} loading={change.isPending && change.variables?.add?.[0] === u.id} onClick={() => change.mutate({ add: [u.id] })}>
                        Qo'shish
                      </Button>
                    )}
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      )}
      <div>
        <div className="label">Guruhdagi xodimlar · {members.length}</div>
        {isLoading ? (
          <PageLoader />
        ) : !members.length ? (
          <Empty title="Guruhda xodim yo'q" />
        ) : (
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
            {members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{person(m)}</span>
                  <span className="muted flex flex-wrap items-center gap-2 text-xs">
                    {m.name && <PhoneLink value={m.phone} />}
                    {m.telegram_id ? <Badge tone="info" dot={false}>Telegram</Badge> : m.telegram_id === null ? <span className="text-amber-700 dark:text-amber-300">Telegram ulanmagan</span> : null}
                    {m.is_active === false && <Badge tone="danger" dot={false}>O'chirilgan</Badge>}
                  </span>
                </span>
                {!readOnly && (
                  <Button size="sm" variant="ghost" icon={<UserMinus className="h-4 w-4 text-rose-600" />} loading={change.isPending && change.variables?.remove?.[0] === m.id} onClick={() => change.mutate({ remove: [m.id] })}>
                    Chiqarish
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
