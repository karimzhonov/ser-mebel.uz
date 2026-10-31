import { useState } from "react";
import { KeyRound, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList } from "@/api/hooks";
import type { AccessLevel, StaffUser, UserAccess } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PhoneLink } from "@/components/domain";
import { Badge, Button, Card, Confirm, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, PageLoader, Pagination, SearchInput, Segmented } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

type Form = { id?: number; phone: string; name: string; password: string; is_active: boolean; is_staff: boolean; groups: number[] };

export default function UsersPage() {
  const { user } = useAuth();
  const { state, page, set } = useUrlState({ search: "" });
  const { data, isFetching } = useList<StaffUser>("users", { ...state, page }, !!user?.is_superuser);
  const { data: groups } = useAll<{ id: number; name: string }>("groups", {}, !!user?.is_superuser);
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [del, setDel] = useState<StaffUser | null>(null);
  const [rights, setRights] = useState<StaffUser | null>(null);
  const remove = useAction((id: number) => api.delete(`/users/${id}/`), {
    success: "O'chirildi",
    invalidate: ["users"],
    onSuccess: () => setDel(null),
  });
  const save = useAction(
    () => {
      const body: Record<string, unknown> = { ...form };
      if (!form!.password) delete body.password;
      return form!.id ? api.patch(`/users/${form!.id}/`, body) : api.post("/users/", body);
    },
    { success: "Saqlandi", invalidate: ["users"], onSuccess: () => setForm(null) },
  );
  const test = useAction((id: number) => api.post(`/users/${id}/test-message/`).then((r) => r.data), {
    onSuccess: (r: any) =>
      r.sent ? toast.success("Test xabari yuborildi") : r.without_telegram ? toast.warning("Telegram ulanmagan") : toast.error("Bot ishlamayapti"),
  });

  if (!user?.is_superuser) return <Empty title="Faqat administrator uchun" />;
  const groupName = (id: number) => groups?.find((g) => g.id === id)?.name ?? id;

  return (
    <div>
      <PageHeader
        title="Xodimlar"
        subtitle="Sayt foydalanuvchilari va ularning guruhlari"
        actions={
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setForm({ phone: "+998", name: "", password: "", is_active: true, is_staff: true, groups: [] }))}>
            Xodim
          </Button>
        }
      />
      <Card padded={false}>
        <div className="border-b border-slate-100 p-4 dark:border-slate-800">
          <SearchInput value={state.search} onChange={(v) => set({ search: v })} placeholder="Ism yoki telefon" />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "name", header: "Ism", cell: (r) => <span className="font-medium">{r.name || "—"}</span> },
            { key: "phone", header: "Telefon", cell: (r) => <PhoneLink value={r.phone} /> },
            { key: "groups", header: "Guruhlar", cell: (r) => <div className="flex flex-wrap gap-1">{r.groups.map((g) => <Badge key={g} dot={false}>{groupName(g)}</Badge>)}</div> },
            {
              key: "flags",
              header: "Holat",
              cell: (r) => (
                <div className="flex flex-wrap gap-1">
                  {r.is_superuser && <Badge tone="primary">Admin</Badge>}
                  {r.is_active ? <Badge tone="ok">Faol</Badge> : <Badge tone="danger">O'chirilgan</Badge>}
                  {r.telegram_id && <Badge tone="info">Telegram</Badge>}
                </div>
              ),
            },
            { key: "login", header: "Oxirgi kirish", cell: (r) => <span className="muted">{dateTime(r.last_login)}</span>, hideOnMobile: true },
            {
              key: "x",
              header: "",
              cell: (r) => (
                <div className="flex justify-end gap-1">
                  {!r.is_superuser && (
                    <IconButton label="Bo'limlar huquqi" onClick={() => setRights(r)}>
                      <KeyRound className="h-4 w-4" />
                    </IconButton>
                  )}
                  <IconButton label="Test xabari" onClick={() => test.mutate(r.id)}><Send className="h-4 w-4" /></IconButton>
                  <IconButton
                    label="Tahrirlash"
                    onClick={() => (setErrors({}), setForm({ id: r.id, phone: r.phone, name: r.name ?? "", password: "", is_active: r.is_active, is_staff: r.is_staff, groups: r.groups }))}
                  >
                    <Pencil className="h-4 w-4" />
                  </IconButton>
                  {r.id !== user?.id && (
                    <IconButton label="O'chirish" onClick={() => setDel(r)}>
                      <Trash2 className="h-4 w-4 text-rose-600" />
                    </IconButton>
                  )}
                </div>
              ),
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? "Xodimni tahrirlash" : "Yangi xodim"}
        footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}
      >
        {form && (
          <div className="space-y-4">
            <Field label="Telefon" error={errors.phone}><Input inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="Ism" error={errors.name}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={form.id ? "Yangi parol (ixtiyoriy)" : "Parol"} error={errors.password}>
              <Input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </Field>
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Faol</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_staff} onChange={(e) => setForm({ ...form, is_staff: e.target.checked })} /> Panelga kirish huquqi</label>
            </div>
            <Field label="Guruhlar">
              <div className="flex flex-wrap gap-2">
                {groups?.map((g) => {
                  const on = form.groups.includes(g.id);
                  return (
                    <button
                      key={g.id}
                      type="button"
                      onClick={() => setForm({ ...form, groups: on ? form.groups.filter((x) => x !== g.id) : [...form.groups, g.id] })}
                      className={on ? "rounded-full bg-brand-600 px-3 py-1 text-xs font-medium text-white" : "rounded-full border border-slate-200 px-3 py-1 text-xs dark:border-slate-700"}
                    >
                      {g.name}
                    </button>
                  );
                })}
              </div>
            </Field>
          </div>
        )}
      </Modal>
      {rights && <AccessModal user={rights} onClose={() => setRights(null)} />}
      <Confirm
        open={!!del}
        onClose={() => setDel(null)}
        onConfirm={() => remove.mutate(del!.id)}
        loading={remove.isPending}
        variant="danger"
        confirmLabel="O'chirish"
        title="Xodimni o'chirish"
        text={
          <>
            <b>{del?.name || del?.phone}</b> butunlay o'chiriladi. Agar uning ish tarixi bo'lsa (yig'ish, izohlar), tizim o'chirmaydi — unda «Faol» belgisini olib qo'ying.
          </>
        }
      />
    </div>
  );
}

const LEVEL_LABEL: Record<string, string> = { none: "Yo'q", view: "Ko'rish", edit: "O'zgartirish", custom: "Qo'lda sozlangan" };

/** Per-section access: none / view / edit, saved as the person's own permissions. */
function AccessModal({ user, onClose }: { user: StaffUser; onClose: () => void }) {
  const { data } = useGet<UserAccess>(`/users/${user.id}/access/`);
  const [changed, setChanged] = useState<Record<string, AccessLevel>>({});
  const save = useAction(() => api.post(`/users/${user.id}/access/`, { levels: changed }), {
    success: "Huquqlar saqlandi",
    invalidate: ["users"],
    onSuccess: onClose,
  });
  const titles = data ? [...new Set(data.sections.map((s) => s.title))] : [];

  return (
    <Modal
      open
      onClose={onClose}
      title={`Bo'limlar huquqi — ${user.name || user.phone}`}
      size="lg"
      footer={
        <Button disabled={!Object.keys(changed).length || data?.is_keeper} loading={save.isPending} onClick={() => save.mutate()}>
          Saqlash
        </Button>
      }
    >
      {!data ? (
        <PageLoader />
      ) : data.is_keeper ? (
        <Empty title="Bu xodim — omborchi" text="Uning huquqlari Ombor → Omborchi sahifasida boshqariladi." />
      ) : (
        <div className="space-y-5">
          <p className="muted text-xs">
            «Ko'rish» — bo'limni ochadi, lekin hech narsani o'zgartira olmaydi. «O'zgartirish» — qo'shish, tahrirlash va o'chirish ham mumkin. Guruhdan kelgan
            huquqlar shu yerda o'zgarmaydi — ular yonida ko'rsatilgan.
          </p>
          {titles.map((title) => (
            <section key={title}>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
              <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
                {data.sections
                  .filter((s) => s.title === title)
                  .map((s) => {
                    const value: string = (changed[s.key] as AccessLevel | undefined) ?? s.level;
                    const options = [
                      { value: "none", label: "Yo'q" },
                      { value: "view", label: "Ko'rish" },
                      ...(s.can_edit ? [{ value: "edit", label: "O'zgartirish" }] : []),
                    ];
                    return (
                      <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium">{s.label}</div>
                          <div className="muted flex flex-wrap gap-x-2 text-xs">
                            {s.hint && <span>{s.hint}</span>}
                            {s.from_groups !== "none" && <span className="text-brand-700 dark:text-brand-300">guruhdan: {LEVEL_LABEL[s.from_groups]}</span>}
                            {value === "custom" && <span className="text-amber-700">qo'lda sozlangan — tanlasangiz almashtiriladi</span>}
                          </div>
                        </div>
                        <Segmented
                          value={value}
                          options={options}
                          onChange={(v) =>
                            setChanged((c) => {
                              const next = { ...c };
                              if (v === s.level) delete next[s.key];
                              else next[s.key] = v as AccessLevel;
                              return next;
                            })
                          }
                        />
                      </li>
                    );
                  })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Modal>
  );
}
