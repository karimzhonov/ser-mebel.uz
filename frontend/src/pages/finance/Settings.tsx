import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Card, DataTable, Field, IconButton, Input, Modal, PageHeader, SearchInput, Segmented, Select } from "@/components/ui";
import { useUrlState } from "@/lib/useUrlState";
import { RoleBadge, som, useCategories, useMembers } from "./shared";
import type { Car, FinCategory, ManualOrder, Member, Role, Worker } from "./types";

type Tab = "members" | "workers" | "categories" | "cars" | "orders" | "params";

export default function FinanceSettingsPage() {
  const { state, set } = useUrlState({ tab: "members" as Tab });
  return (
    <div>
      <PageHeader title="Moliya sozlamalari" subtitle="Telegram rollari, ro'yxatlar va bot parametrlari" />
      <div className="mb-4">
        <Segmented
          value={state.tab as Tab}
          onChange={(tab) => set({ tab })}
          options={[
            { value: "members", label: "👥 Telegram a'zolar" },
            { value: "workers", label: "👷 Ishchilar" },
            { value: "categories", label: "🗂 Kategoriyalar" },
            { value: "cars", label: "🚗 Mashinalar" },
            { value: "orders", label: "🧾 Qo'lda buyurtmalar" },
            { value: "params", label: "⚙️ Parametrlar" },
          ]}
        />
      </div>
      {state.tab === "members" && <MembersTab />}
      {state.tab === "workers" && <WorkersTab />}
      {state.tab === "categories" && <CategoriesTab />}
      {state.tab === "cars" && <CarsTab />}
      {state.tab === "orders" && <ManualOrdersTab />}
      {state.tab === "params" && <ParamsTab />}
    </div>
  );
}

/* ------------------------------------------------------------------ Telegram members */
const DUTIES: [keyof Member, string][] = [
  ["is_bonus_receiver", "🎁 «Готов» varaqasi va bonus"],
  ["is_deadline_receiver", "⏰ Srok eslatmalari"],
  ["is_site_entry", "🌐 Saytga kirituvchi"],
  ["is_feedback", "💬 Mijoz fikri"],
];

function MembersTab() {
  const { can } = useAuth();
  const [role, setRole] = useState("");
  const [search, setSearch] = useState("");
  const { data, isFetching } = useMembers(role ? { role } : {});
  const [edit, setEdit] = useState<Member | null>(null);
  const rows = (data ?? []).filter((m) => !search || `${m.name} ${m.username} ${m.telegram_id}`.toLowerCase().includes(search.toLowerCase()));
  return (
    <Card padded={false}>
      <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
        <SearchInput className="flex-1" value={search} onChange={setSearch} placeholder="Ism, username, Telegram ID" />
        <Segmented
          value={role}
          onChange={setRole}
          options={[
            { value: "", label: "Hammasi" },
            { value: "admin", label: "Rahbar" },
            { value: "staff", label: "Xodim" },
            { value: "pending", label: "Kutmoqda", count: data?.filter((m) => m.role === "pending").length },
            { value: "blocked", label: "Bloklangan" },
          ]}
        />
      </div>
      <p className="muted border-b border-slate-100 px-4 py-2 text-xs dark:border-slate-800">
        Bu rollar faqat Telegram moliya boti uchun, sayt huquqlaridan alohida. Yangi xodim botga /moliya yozib «Ro'yxatdan o'tish»ni bosadi, siz shu yerda yoki botda tasdiqlaysiz. Sayt profilini faqat shu yerda ulang (botdagi bog'lanish tekshirilmagan).
      </p>
      <DataTable
        rows={rows}
        loading={isFetching}
        rowKey={(r) => r.id}
        onRowClick={can("oauth.change_telegrammember") ? setEdit : undefined}
        columns={[
          { key: "n", header: "Ism", cell: (r) => <span className="font-medium">{r.name}</span> },
          { key: "u", header: "Telegram", cell: (r) => <span className="muted text-sm">{r.username ? `@${r.username} · ` : ""}{r.telegram_id}</span>, hideOnMobile: true },
          { key: "r", header: "Rol", cell: (r) => <RoleBadge role={r.role} label={r.role_label} /> },
          {
            key: "d",
            header: "Vazifalar",
            cell: (r) => (
              <div className="flex flex-wrap gap-1">
                {DUTIES.filter(([k]) => r[k]).map(([k, label]) => (
                  <Badge key={k} tone="info" dot={false}>{label}</Badge>
                ))}
                {r.is_task_only && <Badge tone="warn" dot={false}>hamyonsiz</Badge>}
              </div>
            ),
          },
          { key: "s", header: "Sayt profili", cell: (r) => r.user_detail?.name || r.user_detail?.phone || "—", hideOnMobile: true },
        ]}
      />
      {edit && <MemberModal m={edit} onClose={() => setEdit(null)} />}
    </Card>
  );
}

function MemberModal({ m, onClose }: { m: Member; onClose: () => void }) {
  const { can } = useAuth();
  const { data: users } = useAll<{ id: number; name: string | null; phone: string }>("users", { page_size: 500 }, can("oauth.view_user"));
  const [f, setF] = useState({ ...m, user: m.user });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api.patch(`/finance/members/${m.id}/`, {
        name: f.name,
        role: f.role,
        user: f.user,
        is_site_entry: f.is_site_entry,
        is_feedback: f.is_feedback,
        is_bonus_receiver: f.is_bonus_receiver,
        is_deadline_receiver: f.is_deadline_receiver,
      }),
    { success: "Saqlandi", invalidate: ["finance"], onSuccess: onClose },
  );
  const userList = Array.isArray(users) ? users : ((users as unknown as { results?: typeof users })?.results ?? []);
  return (
    <Modal open onClose={onClose} title={`${m.name} · ${m.telegram_id}`} size="sm" footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}>
      <div className="space-y-4">
        <Field label="Ism" error={errors.name}>
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Rol" error={errors.role}>
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
            <option value="admin">Rahbar — hamma narsani ko'radi, pul beradi</option>
            <option value="staff">Xodim — o'z hamyoni</option>
            <option value="pending">Tasdiq kutmoqda</option>
            <option value="blocked">Bloklangan</option>
          </Select>
        </Field>
        <div className="space-y-2">
          <span className="label">Vazifalar</span>
          {DUTIES.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={!!f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} />
              {label}
            </label>
          ))}
          <p className="muted text-xs">Saytga kirituvchi / mijoz fikri vazifasi bor xodim (rahbar bo'lmasa) kirim-chiqim kiritmaydi.</p>
        </div>
        {userList.length > 0 && (
          <Field label="Sayt profili (ixtiyoriy)" hint="Ulansa, u saytdagi Moliya bo'limida o'z hamyonini ko'radi" error={errors.user}>
            <Select value={f.user ?? ""} onChange={(e) => setF({ ...f, user: e.target.value ? Number(e.target.value) : null })}>
              <option value="">—</option>
              {userList.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name || u.phone}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ simple catalogs */
function useCatalogActions(resource: string) {
  const save = useAction((v: { id?: number; body: Record<string, unknown> }) => (v.id ? api.patch(`/${resource}/${v.id}/`, v.body) : api.post(`/${resource}/`, v.body)), {
    success: "Saqlandi",
    invalidate: [resource],
  });
  const remove = useAction((id: number) => api.delete(`/${resource}/${id}/`), { success: "O'chirildi", invalidate: [resource] });
  return { save, remove };
}

function WorkersTab() {
  const { data } = useAll<Worker>("finance/workers");
  const { save, remove } = useCatalogActions("finance/workers");
  const [f, setF] = useState({ group: "", name: "", position: "" });
  return (
    <Card padded={false}>
      <div className="grid gap-2 border-b border-slate-100 p-4 sm:grid-cols-4 dark:border-slate-800">
        <Input list="worker-groups" placeholder="Bo'lim (masalan Zavod)" value={f.group} onChange={(e) => setF({ ...f, group: e.target.value })} />
        <datalist id="worker-groups">{[...new Set(data?.map((w) => w.group))].map((g) => <option key={g} value={g} />)}</datalist>
        <Input placeholder="Ism" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <Input placeholder="Lavozim" value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })} />
        <Button icon={<Plus className="h-4 w-4" />} disabled={!f.group || !f.name} onClick={() => save.mutateAsync({ body: { ...f, ordering: (data?.length ?? 0) + 1 } }).then(() => setF({ ...f, name: "", position: "" }))}>
          Qo'shish
        </Button>
      </div>
      <DataTable
        rows={data}
        rowKey={(r) => r.id}
        columns={[
          { key: "g", header: "Bo'lim", cell: (r) => r.group },
          { key: "n", header: "Ism", cell: (r) => <span className="font-medium">{r.name}</span> },
          { key: "p", header: "Lavozim", cell: (r) => r.position || "—" },
          {
            key: "a",
            header: "Faol",
            cell: (r) => <input type="checkbox" checked={r.is_active} onChange={(e) => save.mutate({ id: r.id, body: { is_active: e.target.checked } })} />,
          },
          {
            key: "x",
            header: "",
            cell: (r) => (
              <IconButton label="O'chirish" onClick={() => confirm(`${r.name} o'chirilsinmi?`) && remove.mutate(r.id)}>
                <Trash2 className="h-4 w-4" />
              </IconButton>
            ),
          },
        ]}
      />
    </Card>
  );
}

function CarsTab() {
  const { data } = useAll<Car>("finance/cars");
  const { save, remove } = useCatalogActions("finance/cars");
  const [name, setName] = useState("");
  return (
    <Card padded={false}>
      <div className="flex gap-2 border-b border-slate-100 p-4 dark:border-slate-800">
        <Input placeholder="Labo — Elyor" value={name} onChange={(e) => setName(e.target.value)} />
        <Button disabled={!name.trim()} onClick={() => save.mutateAsync({ body: { name, ordering: (data?.length ?? 0) + 1 } }).then(() => setName(""))}>Qo'shish</Button>
      </div>
      <DataTable
        rows={data}
        rowKey={(r) => r.id}
        columns={[
          { key: "n", header: "Mashina / kim (zapravka)", cell: (r) => r.name },
          { key: "a", header: "Faol", cell: (r) => <input type="checkbox" checked={r.is_active} onChange={(e) => save.mutate({ id: r.id, body: { is_active: e.target.checked } })} /> },
          { key: "x", header: "", cell: (r) => <IconButton label="O'chirish" onClick={() => confirm(`${r.name} o'chirilsinmi?`) && remove.mutate(r.id)}><Trash2 className="h-4 w-4" /></IconButton> },
        ]}
      />
    </Card>
  );
}

function CategoriesTab() {
  const { data } = useCategories();
  const { save } = useCatalogActions("finance/categories");
  const [edit, setEdit] = useState<Partial<FinCategory> | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const kinds = { expense: "Chiqim", income: "Kirim", internal: "Ichki" };
  return (
    <Card
      padded={false}
      title="Kategoriyalar"
      actions={<Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setEdit({ kind: "expense", color: "#94A3B8", emoji: "📦", keywords: [], is_active: true }))}>Yangi</Button>}
    >
      <DataTable
        rows={data}
        rowKey={(r) => r.id}
        onRowClick={(r) => (setErrors({}), setEdit(r))}
        rowClassName={(r) => (r.is_active ? undefined : "opacity-50")}
        columns={[
          { key: "n", header: "Nomi", cell: (r) => <span><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: r.color }} />{r.emoji} {r.name}</span> },
          { key: "c", header: "Kod", cell: (r) => <code className="text-xs">{r.code}</code> },
          { key: "k", header: "Turi", cell: (r) => kinds[r.kind] },
          {
            key: "f",
            header: "Qoidalar",
            cell: (r) => (
              <div className="flex flex-wrap gap-1 text-xs">
                {r.no_order && <Badge dot={false}>buyurtmasiz</Badge>}
                {r.needs_order && <Badge dot={false} tone="warn">buyurtma shart</Badge>}
                {r.admin_only && <Badge dot={false} tone="primary">faqat rahbar</Badge>}
                {r.excluded && <Badge dot={false} tone="info">hisobga kirmaydi</Badge>}
              </div>
            ),
            hideOnMobile: true,
          },
        ]}
      />
      {edit && (
        <Modal
          open
          onClose={() => setEdit(null)}
          title={edit.id ? `${edit.emoji} ${edit.name}` : "Yangi kategoriya"}
          size="sm"
          footer={
            <Button
              loading={save.isPending}
              onClick={() =>
                save
                  .mutateAsync({ id: edit.id, body: edit as Record<string, unknown> })
                  .then(() => setEdit(null))
                  .catch((e) => setErrors(fieldErrors(e)))
              }
            >
              Saqlash
            </Button>
          }
        >
          <div className="space-y-3">
            <div className="grid grid-cols-[80px_1fr] gap-3">
              <Field label="Emoji">
                <Input value={edit.emoji ?? ""} onChange={(e) => setEdit({ ...edit, emoji: e.target.value })} />
              </Field>
              <Field label="Nomi" error={errors.name}>
                <Input value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kod" hint="lotincha, keyin o'zgarmaydi" error={errors.code}>
                <Input value={edit.code ?? ""} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, code: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })} />
              </Field>
              <Field label="Turi">
                <Select value={edit.kind} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, kind: e.target.value as FinCategory["kind"] })}>
                  <option value="expense">Chiqim</option>
                  <option value="income">Kirim</option>
                </Select>
              </Field>
            </div>
            <Field label="Rang">
              <Input type="color" value={edit.color} onChange={(e) => setEdit({ ...edit, color: e.target.value })} />
            </Field>
            <Field label="Kalit so'zlar" hint="Tezkor yozuv uchun («350000 furnitura 406»), vergul bilan">
              <Input value={(edit.keywords ?? []).join(", ")} onChange={(e) => setEdit({ ...edit, keywords: e.target.value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) })} />
            </Field>
            {(
              [
                ["no_order", "Buyurtma so'ralmaydi (faqat tavsif)"],
                ["needs_order", "Buyurtmasiz bo'lsa tekshiruvda ogohlantirish"],
                ["archive", "«🗄 Arxiv ID» tugmasi"],
                ["admin_only", "Faqat rahbar ko'radi"],
                ["excluded", "Kompaniya xarajati/daromadiga kirmaydi (shaxsiy, ichki)"],
                ["is_active", "Faol"],
              ] as [keyof FinCategory, string][]
            ).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!edit[k]} onChange={(e) => setEdit({ ...edit, [k]: e.target.checked })} />
                {label}
              </label>
            ))}
          </div>
        </Modal>
      )}
    </Card>
  );
}

function ManualOrdersTab() {
  const { data } = useAll<ManualOrder>("finance/manual-orders");
  const { save } = useCatalogActions("finance/manual-orders");
  return (
    <Card padded={false}>
      <p className="muted border-b border-slate-100 p-4 text-sm dark:border-slate-800">
        Saytda yo'q buyurtma ID lari (eski «SM-001» kabi). Saytdagi buyurtmalar bu yerga kerak emas — ular avtomatik ko'rinadi.
      </p>
      <DataTable
        rows={data}
        rowKey={(r) => r.id}
        columns={[
          { key: "r", header: "ID", cell: (r) => <b>{r.ref}</b> },
          { key: "c", header: "Mijoz", cell: (r) => r.client },
          { key: "p", header: "Shartnoma", cell: (r) => som(r.price) },
          { key: "s", header: "Yopilgan", cell: (r) => <input type="checkbox" checked={r.is_closed} onChange={(e) => save.mutate({ id: r.id, body: { is_closed: e.target.checked } })} /> },
        ]}
      />
    </Card>
  );
}

/* ------------------------------------------------------------------ params */
interface Params {
  FIN_REMINDER_HOUR: number;
  FIN_ADMIN_REPORT_HOUR: number;
  FIN_MONTH_END_DAYS: number;
  FIN_WARN_PERCENT: number;
  FIN_USD_RATE: number;
  FIN_CHANNEL_ID: string;
  FIN_READY_DAYS: number;
  FIN_BONUS_SINCE: string;
  usd_rate_effective: number;
}

const PARAMS: [keyof Params, string, string][] = [
  ["FIN_REMINDER_HOUR", "Xodimlarga kunlik eslatma soati", "number"],
  ["FIN_ADMIN_REPORT_HOUR", "Rahbarga kunlik hisobot soati", "number"],
  ["FIN_MONTH_END_DAYS", "Oy tugashiga necha kun qolganda eslatma", "number"],
  ["FIN_WARN_PERCENT", "Buyurtma byudjetining necha % sarflansa ogohlantirish", "number"],
  ["FIN_USD_RATE", "Dollar kursi (0 — Markaziy bank kursi)", "number"],
  ["FIN_CHANNEL_ID", "Telegram kanal (@username yoki -100…)", "text"],
  ["FIN_READY_DAYS", "«Готов» zakaz qoldiq to'lov ro'yxatida necha kun turadi", "number"],
  ["FIN_BONUS_SINCE", "Bonus kuzatuvi shu sanadan keyingi «Готов»lar uchun", "date"],
];

function ParamsTab() {
  const { can } = useAuth();
  const { data } = useGet<Params>("/finance/settings/");
  const [f, setF] = useState<Partial<Params>>({});
  useEffect(() => data && setF(data), [data]);
  const save = useAction(() => api.patch("/finance/settings/", Object.fromEntries(PARAMS.map(([k]) => [k, f[k]]))), { success: "Saqlandi", invalidate: ["/finance/settings/"] });
  return (
    <Card title="Bot parametrlari" actions={can("accounting.change_financecategory") && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {PARAMS.map(([k, label, type]) => (
          <Field key={k} label={label} hint={k === "FIN_USD_RATE" && data ? `Hozir ishlatilayotgan kurs: ${som(data.usd_rate_effective)}` : undefined}>
            <Input type={type} value={String(f[k] ?? "")} onChange={(e) => setF({ ...f, [k]: type === "number" ? Number(e.target.value) : e.target.value })} />
          </Field>
        ))}
      </div>
    </Card>
  );
}
