import { useState } from "react";
import { useParams } from "react-router-dom";
import { Plus, Settings2, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList, useMeta } from "@/api/hooks";
import type { Category, MoneyRecord, MoneyStats, Order } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { ShareBars, TimelineChart } from "@/components/domain";
import { PeriodFilter } from "@/components/PeriodFilter";
import {
  Button,
  Card,
  DataTable,
  Field,
  IconButton,
  Input,
  Modal,
  MoneyInput,
  PageHeader,
  Pagination,
  SearchInput,
  Segmented,
  Select,
  StatTile,
  Textarea,
} from "@/components/ui";
import { date, money, phone } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

export default function AccountingPage() {
  const kind = useParams().kind === "expense" ? "expense" : "income";
  return <Ledger key={kind} kind={kind} />;
}

function Ledger({ kind }: { kind: "income" | "expense" }) {
  const { can, user } = useAuth();
  const { data: meta } = useMeta();
  const resource = kind === "income" ? "incomes" : "expenses";
  const catResource = kind === "income" ? "income-categories" : "expense-categories";
  const app = `accounting.${kind}`;
  const { state, page, set } = useUrlState({ search: "", period: "month", currency: "USD", category: "", date_from: "", date_to: "" });
  const { data, isFetching } = useList<MoneyRecord>(resource, { ...state, page });
  const { data: stats } = useGet<MoneyStats>(`/${resource}/stats/`, { ...state });
  const { data: categories } = useAll<Category>(catResource);
  const [form, setForm] = useState<{ category: string; desc: string; order: string; cost: { amount: number | string; currency: string } } | null>(null);
  const [manageCats, setManageCats] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { data: orders } = useList<Order>("orders", { page_size: 200, status: "waiting,created,detailing,working,assembly,installing" }, kind === "expense" && !!form);

  const add = useAction(
    () =>
      api.post(`/${resource}/`, {
        category: Number(form!.category),
        desc: form!.desc,
        cost: form!.cost,
        ...(kind === "expense" && form!.order ? { order: Number(form!.order) } : {}),
      }),
    { success: "Сохранено", invalidate: [resource], onSuccess: () => setForm(null) },
  );
  const remove = useAction((id: number) => api.delete(`/${resource}/${id}/`), { success: "Удалено", invalidate: [resource] });
  const title = kind === "income" ? "Приходы" : "Расходы";
  const cur = stats?.currency ?? state.currency;

  return (
    <div>
      <PageHeader
        title={title}
        subtitle={user?.is_superuser ? "Все записи" : "Ваши записи"}
        actions={
          <>
            {can(`accounting.view_${kind}category`) && (
              <Button variant="outline" icon={<Settings2 className="h-4 w-4" />} onClick={() => setManageCats(true)}>
                Категории
              </Button>
            )}
            {can(`accounting.add_${kind}`) && (
              <Button
                icon={<Plus className="h-4 w-4" />}
                onClick={() => (setErrors({}), setForm({ category: "", desc: "", order: "", cost: { amount: "", currency: meta?.default_currency ?? "USD" } }))}
              >
                {kind === "income" ? "Приход" : "Расход"}
              </Button>
            )}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <PeriodFilter value={state.period} onChange={(v) => set({ period: v })} />
        <Segmented value={state.currency} onChange={(v) => set({ currency: v })} options={(meta?.currencies ?? ["USD", "UZS"]).map((c) => ({ value: c, label: c }))} />
        <div className="flex items-center gap-2">
          <Input type="date" className="w-40" value={state.date_from} onChange={(e) => set({ date_from: e.target.value })} />
          <span className="muted">—</span>
          <Input type="date" className="w-40" value={state.date_to} onChange={(e) => set({ date_to: e.target.value })} />
        </div>
      </div>
      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <StatTile label={`${title}: итого`} value={money({ amount: stats?.total ?? 0, currency: cur })} hint={`${stats?.count ?? 0} записей`} tone={kind === "income" ? "ok" : "danger"} />
        <Card title="По категориям" className="lg:row-span-2">
          <ShareBars
            rows={(stats?.by_category ?? []).map((c) => ({
              label: c.label,
              value: c.amount,
              display: `${money({ amount: c.amount, currency: cur })} · ${Math.round(c.share * 100)}%`,
            }))}
          />
        </Card>
        <Card title="Динамика" className="lg:col-span-1">
          <TimelineChart data={stats?.timeline} height={160} valueFormatter={(v) => money({ amount: v, currency: cur })} />
        </Card>
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Описание или категория" />
          <Select className="sm:w-56" value={state.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">Все категории</option>
            {categories?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "cat", header: "Категория", cell: (r) => <span className="font-medium">{r.category_name}</span> },
            { key: "desc", header: "Описание", cell: (r) => <span className="line-clamp-1 max-w-xs">{r.desc || "—"}</span> },
            ...(kind === "expense"
              ? [{ key: "order", header: "Заказ", cell: (r: MoneyRecord) => (r.order_detail ? `№${r.order_detail.order_number}` : "—") }]
              : []),
            { key: "cost", header: "Сумма", cell: (r) => <span className="font-semibold tabular-nums">{money(r.cost)}</span> },
            { key: "who", header: "Кто", cell: (r) => r.user_detail?.name || phone(r.user_detail?.phone), hideOnMobile: true },
            { key: "date", header: "Дата", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
            ...(user?.is_superuser
              ? [{
                  key: "x",
                  header: "",
                  cell: (r: MoneyRecord) => (
                    <IconButton label="Удалить" onClick={() => confirm("Удалить запись?") && remove.mutate(r.id)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  ),
                  hideOnMobile: true,
                }]
              : []),
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>

      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={kind === "income" ? "Новый приход" : "Новый расход"}
        size="sm"
        footer={<Button loading={add.isPending} disabled={!form?.category} onClick={() => add.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Сохранить</Button>}
      >
        {form && (
          <div className="space-y-4">
            <Field label="Категория" error={errors.category}>
              <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">— выберите —</option>
                {categories?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="Сумма" error={errors.cost}>
              <MoneyInput value={form.cost} currencies={meta?.currencies} onChange={(cost) => setForm({ ...form, cost })} />
            </Field>
            {kind === "expense" && (
              <Field label="Заказ (необязательно)" error={errors.order || errors.non_field_errors}>
                <Select value={form.order} onChange={(e) => setForm({ ...form, order: e.target.value })}>
                  <option value="">—</option>
                  {orders?.results.map((o) => <option key={o.id} value={o.id}>№{o.order_number} · {o.client?.fio}</option>)}
                </Select>
              </Field>
            )}
            <Field label="Описание" error={errors.desc}>
              <Textarea value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
            </Field>
          </div>
        )}
      </Modal>
      {manageCats && <CategoriesModal resource={catResource} canAdd={can(`${app}category`.replace(".", ".add_"))} onClose={() => setManageCats(false)} />}
    </div>
  );
}

function CategoriesModal({ resource, canAdd, onClose }: { resource: string; canAdd: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const { data } = useAll<Category>(resource);
  const [name, setName] = useState("");
  const add = useAction(() => api.post(`/${resource}/`, { name }), { success: "Добавлено", invalidate: [resource], onSuccess: () => setName("") });
  const remove = useAction((id: number) => api.delete(`/${resource}/${id}/`), { success: "Удалено", invalidate: [resource] });
  return (
    <Modal open onClose={onClose} title="Категории" size="sm">
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {data?.map((c) => (
          <li key={c.id} className="flex items-center justify-between py-2 text-sm">
            {c.name}
            {user?.is_superuser && (
              <IconButton label="Удалить" onClick={() => confirm(`Удалить «${c.name}»?`) && remove.mutate(c.id)}>
                <Trash2 className="h-4 w-4" />
              </IconButton>
            )}
          </li>
        ))}
      </ul>
      {canAdd && (
        <div className="mt-3 flex gap-2">
          <Input placeholder="Новая категория" value={name} onChange={(e) => setName(e.target.value)} />
          <Button disabled={!name.trim()} loading={add.isPending} onClick={() => add.mutate()}>Добавить</Button>
        </div>
      )}
    </Modal>
  );
}
