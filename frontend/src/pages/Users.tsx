import { useState } from "react";
import { Pencil, Plus, Send } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useList } from "@/api/hooks";
import type { StaffUser } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PhoneLink } from "@/components/domain";
import { Badge, Button, Card, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, Pagination, SearchInput } from "@/components/ui";
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
        subtitle="Batafsil huquqlar avvalgidek /admin/ da sozlanadi"
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
                  <IconButton label="Test xabari" onClick={() => test.mutate(r.id)}><Send className="h-4 w-4" /></IconButton>
                  <IconButton
                    label="Tahrirlash"
                    onClick={() => (setErrors({}), setForm({ id: r.id, phone: r.phone, name: r.name ?? "", password: "", is_active: r.is_active, is_staff: r.is_staff, groups: r.groups }))}
                  >
                    <Pencil className="h-4 w-4" />
                  </IconButton>
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
    </div>
  );
}
