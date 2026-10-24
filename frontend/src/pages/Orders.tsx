import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  Hammer,
  Pencil,
  Plus,
} from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList, useMeta } from "@/api/hooks";
import type {
  Category,
  Design,
  Factory,
  HistoryEntry,
  Metering,
  MoneyRecord,
  Order,
  OrderDetail,
  StatusStats,
} from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  AddressLink,
  BackLink,
  DeadlinePill,
  FolderButton,
  OrderStatusBadge,
  PhoneLink,
  ROW_TONE,
  TimelineChart,
} from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import {
  Button,
  Card,
  Check,
  Chip,
  Confirm,
  DataTable,
  Empty,
  Field,
  Input,
  KV,
  Modal,
  MoneyInput,
  PageHeader,
  PageLoader,
  Pagination,
  SearchInput,
  Segmented,
  Select,
  StatTile,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { date, dateTime, money, num, phone, todayISO } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

/* ------------------------------------------------------------------ List */

export function OrdersPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { data: factories } = useAll<Factory>("factories");
  const { state, page, set } = useUrlState({ search: "", status: "", warning: "", factory: "", date_from: "", date_to: "" });
  const { data, isFetching } = useList<Order>("orders", { ...state, page });
  const { data: stats } = useGet<StatusStats>("/orders/stats/", {
    search: state.search,
    date_from: state.date_from, date_to: state.date_to,
    factory: state.factory,
  });
  const counts = Object.fromEntries((stats?.by_status ?? []).map((s) => [s.key, s.count]));
  const warn = Object.fromEntries((stats?.warnings ?? []).map((s) => [s.key, s.count]));
  const selected = state.status.split(",").filter(Boolean);
  const showMoney = can("order.view_order_price");

  return (
    <div>
      <PageHeader
        title="Заказы"
        subtitle={`Всего: ${stats?.total ?? "…"}`}
        actions={
          can("order.add_order") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/orders/new")}>
              Новый заказ
            </Button>
          )
        }
      />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile
          label="Просрочены"
          value={warn.danger ?? "…"}
          tone="danger"
          icon={<AlertTriangle className="h-5 w-5" />}
          active={state.warning === "danger"}
          onClick={() => set({ warning: state.warning === "danger" ? "" : "danger" })}
        />
        <StatTile
          label={`Меньше ${meta?.warning_order_days ?? 7} дней`}
          value={warn.warning ?? "…"}
          tone="warn"
          icon={<Clock className="h-5 w-5" />}
          active={state.warning === "warning"}
          onClick={() => set({ warning: state.warning === "warning" ? "" : "warning" })}
        />
        <StatTile
          label="В срок"
          value={warn.success ?? "…"}
          tone="ok"
          icon={<CheckCircle2 className="h-5 w-5" />}
          active={state.warning === "success"}
          onClick={() => set({ warning: state.warning === "success" ? "" : "success" })}
        />
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <Chip active={!selected.length} onClick={() => set({ status: "" })}>
          Все · {stats?.total ?? "…"}
        </Chip>
        {meta?.order_statuses.map((s) => (
          <Chip
            key={s.value}
            tone={s.tone}
            active={selected.includes(String(s.value))}
            onClick={() =>
              set({
                status: (selected.includes(String(s.value))
                  ? selected.filter((x) => x !== s.value)
                  : [...selected, String(s.value)]
                ).join(","),
              })
            }
          >
            {s.label} · {counts[String(s.value)] ?? 0}
          </Chip>
        ))}
      </div>

      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="№, клиент, телефон, адрес" />
          <Select className="lg:w-48" value={state.factory} onChange={(e) => set({ factory: e.target.value })}>
            <option value="">Все заводы</option>
            {factories?.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </Select>
          <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/orders/${r.id}`)}
          rowClassName={(r) => ROW_TONE[r.deadline.level]}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="font-semibold">{r.order_number}</span> },
            {
              key: "client",
              header: "Клиент",
              cell: (r) => (
                <div>
                  <div className="font-medium">{r.client?.fio ?? "—"}</div>
                  <PhoneLink value={r.client?.phone} />
                </div>
              ),
            },
            { key: "factory", header: "Завод", cell: (r) => r.factory.name, hideOnMobile: true },
            { key: "address", header: "Адрес", cell: (r) => <span className="line-clamp-1 max-w-[200px]">{r.address}</span>, hideOnMobile: true },
            { key: "status", header: "Статус", cell: (r) => <OrderStatusBadge status={r.status} label={r.status_label} /> },
            { key: "dates", header: "Приём / сдача", cell: (r) => <span className="whitespace-nowrap text-xs">{date(r.reception_date)}<br />{date(r.end_date)}</span> },
            { key: "deadline", header: "Срок", cell: (r) => <DeadlinePill deadline={r.deadline} /> },
            ...(showMoney
              ? [
                  { key: "total", header: "Итого", cell: (r: Order) => <span className="tabular-nums">{money(r.total_price)}</span> },
                  { key: "left", header: "Остаток", cell: (r: Order) => <span className="font-medium tabular-nums">{money(r.money_left)}</span> },
                ]
              : []),
          ]}
          mobileCard={(r) => (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">№{r.order_number} · {r.client?.fio}</span>
                <OrderStatusBadge status={r.status} label={r.status_label} />
              </div>
              <div className="muted text-sm">{r.address}</div>
              <div className="flex items-center justify-between">
                <DeadlinePill deadline={r.deadline} />
                {showMoney && <span className="text-sm font-medium">{money(r.money_left)}</span>}
              </div>
            </div>
          )}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      <Card title="Заказы по дате приёма" className="mt-4">
        <TimelineChart data={stats?.timeline} height={200} />
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- Detail */

export function OrderDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: o, isLoading } = useGet<OrderDetail>(`/orders/${id}/`);
  const [tab, setTab] = useState("info");
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<null | "detailing" | "next-status" | "go-to-assembly">(null);

  const inv = ["orders", "dashboard", "detailings", "assemblies", "meterings"];
  const run = useAction(
    (path: string) => api.post(`/orders/${id}/${path}/`).then((r) => r.data),
    {
      success: "Готово",
      invalidate: inv,
      onSuccess: (data: any) => {
        setConfirm(null);
        if (data?.assembly_id) navigate(`/production/assembly?open=${data.assembly_id}`);
      },
    },
  );

  if (isLoading || !o) return <PageLoader />;
  const a = o.actions;
  const p = o.production;
  const CONFIRM_TEXT = {
    detailing: ["Отправить в деталировку?", "Сотрудники деталировки получат уведомление."],
    "next-status": [`Перевести в «${a.next_status_label}»?`, "Ответственные получат SMS/Telegram уведомление."],
    "go-to-assembly": ["Отправить в сборку?", "Заказ перейдёт в статус «Сборка»."],
  } as const;

  return (
    <div>
      <PageHeader
        back={<BackLink to="/orders">Заказы</BackLink>}
        title={`Заказ №${o.order_number}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <OrderStatusBadge status={o.status} label={o.status_label} />
            <DeadlinePill deadline={o.deadline} />
          </span>
        }
        actions={
          <>
            <FolderButton folderId={o.folder} />
            {a.edit && (
              <Button variant="outline" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>
                Изменить
              </Button>
            )}
            {a.detailing && (
              <Button variant="success" icon={<BookOpen className="h-4 w-4" />} onClick={() => setConfirm("detailing")}>
                В деталировку
              </Button>
            )}
            {a.go_to_assembly && (
              <Button variant="success" icon={<Hammer className="h-4 w-4" />} onClick={() => setConfirm("go-to-assembly")}>
                В сборку
              </Button>
            )}
            {a.next_status && !a.detailing && !a.go_to_assembly && (
              <Button icon={<ArrowRight className="h-4 w-4" />} onClick={() => setConfirm("next-status")}>
                {a.next_status_label}
              </Button>
            )}
          </>
        }
      />

      <ProgressBar status={o.status} />

      <Segmented
        className="mb-4"
        value={tab}
        onChange={setTab}
        options={[
          { value: "info", label: "Информация" },
          { value: "production", label: "Производство" },
          ...(can("accounting.view_expense") ? [{ value: "expenses", label: "Расходы" }] : []),
          { value: "history", label: "История" },
        ]}
      />

      {tab === "info" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Заказ" className="lg:col-span-2">
            <KV
              items={[
                ["Клиент", o.client ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(o.client.phone)}`}>{o.client.fio}</Link> : "—"],
                ["Телефон", <PhoneLink value={o.client?.phone} />],
                ["Адрес", <AddressLink address={o.address} link={o.address_link} />],
                ["Завод", o.factory.name],
                ["Дата приёма", date(o.reception_date)],
                ["Дата сдачи", date(o.end_date, "не указана")],
                ["Дизайн", o.design_type?.name ?? "—"],
                ["Замер", o.metering ? <Link className="text-brand-700 hover:underline" to={`/meterings/${o.metering}`}>Открыть →</Link> : "—"],
              ]}
            />
            {o.desc && <p className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/50">{o.desc}</p>}
          </Card>
          {"price" in o && (
            <Card title="Оплата">
              <div className="space-y-3">
                <div>
                  <div className="muted text-xs">Итого (со скидкой {num(o.discount)}%)</div>
                  <div className="text-2xl font-semibold tabular-nums">{money(o.total_price)}</div>
                </div>
                <KV
                  items={[
                    ["Сумма", money(o.price)],
                    ["Получено", money(o.lost_money)],
                    ["Остаток", <span className="text-base font-semibold">{money(o.money_left)}</span>],
                  ]}
                />
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === "production" && (
        <div className="grid gap-4 md:grid-cols-2">
          <ProdCard
            title="Деталировка"
            to={p.detailing ? `/production/detailing?open=${p.detailing.id}` : undefined}
            folder={p.detailing?.folder}
            rows={p.detailing && [
              ["Площадь", num(p.detailing.square)],
              ["Площадь покраски", num(p.detailing.painter_square)],
              ["Площадь ровера", num(p.detailing.rover_square)],
              ["Выполнено", <Check ok={p.detailing.done} />],
            ]}
          />
          <ProdCard
            title="Ровер"
            to={p.rover ? `/production/rover?open=${p.rover.id}` : undefined}
            folder={p.rover?.folder}
            rows={p.rover && [
              ["Площадь", num(p.rover.square)],
              ...(p.rover.price ? ([["Цена", money(p.rover.price)]] as [string, string][]) : []),
              ["Выполнено", <Check ok={p.rover.done} />],
            ]}
          />
          <ProdCard
            title="Моляр"
            to={p.painter ? `/production/painter?open=${p.painter.id}` : undefined}
            folder={p.painter?.folder}
            rows={p.painter && [
              ["Тип", p.painter.type ?? "не назначен"],
              ["Площадь", num(p.painter.square)],
              ...(p.painter.price ? ([["Цена", money(p.painter.price)]] as [string, string][]) : []),
              ["Выполнено", <Check ok={p.painter.done} />],
            ]}
          />
          <ProdCard
            title="Сборка / Установка"
            to={p.assembly ? `/production/assembly?open=${p.assembly.id}` : undefined}
            folder={p.assembly?.folder}
            rows={p.assembly && [
              ["Сборщик", p.assembly.user ? p.assembly.user.name || phone(p.assembly.user.phone) : "не назначен"],
              ["Площадь", num(p.assembly.square)],
              ...(p.assembly.price ? ([["Цена", money(p.assembly.price)]] as [string, string][]) : []),
              ["Сборка", <Check ok={p.assembly.done} />],
              ["Установка", <Check ok={p.assembly.installing_done} />],
            ]}
          />
        </div>
      )}

      {tab === "expenses" && <OrderExpenses orderId={o.id} canAdd={a.add_expense} />}
      {tab === "history" && <OrderHistory orderId={o.id} />}

      {editing && <OrderEditModal order={o} onClose={() => setEditing(false)} />}
      <Confirm
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={confirm ? CONFIRM_TEXT[confirm][0] : ""}
        text={confirm ? CONFIRM_TEXT[confirm][1] : ""}
        loading={run.isPending}
        onConfirm={() => confirm && run.mutate(confirm)}
      />
    </div>
  );
}

const FLOW = ["waiting", "created", "detailing", "working", "assembly", "installing", "done"];

function ProgressBar({ status }: { status: string }) {
  const { data: meta } = useMeta();
  const idx = FLOW.indexOf(status);
  return (
    <div className="scrollbar-thin mb-5 overflow-x-auto">
      <ol className="flex min-w-[640px] items-center">
        {FLOW.map((s, i) => {
          const label = meta?.order_statuses.find((x) => x.value === s)?.label ?? s;
          const done = i < idx || status === "done";
          const current = i === idx && status !== "done";
          return (
            <li key={s} className="flex flex-1 items-center">
              <div className="flex flex-col items-center gap-1.5">
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold",
                    done && "bg-emerald-500 text-white",
                    current && "bg-brand-600 text-white ring-4 ring-brand-500/20",
                    !done && !current && "bg-slate-200 text-slate-500 dark:bg-slate-800",
                  )}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span className={cn("whitespace-nowrap text-[11px]", current ? "font-semibold text-brand-700 dark:text-brand-300" : "muted")}>
                  {label}
                </span>
              </div>
              {i < FLOW.length - 1 && <div className={cn("mx-1 mb-5 h-0.5 flex-1", i < idx ? "bg-emerald-500" : "bg-slate-200 dark:bg-slate-800")} />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ProdCard({
  title,
  rows,
  to,
  folder,
}: {
  title: string;
  rows: [React.ReactNode, React.ReactNode][] | null;
  to?: string;
  folder?: number | null;
}) {
  return (
    <Card
      title={title}
      actions={
        rows && (
          <>
            <FolderButton folderId={folder} />
            {to && (
              <Link to={to} className="text-sm text-brand-700 hover:underline dark:text-brand-300">
                Открыть →
              </Link>
            )}
          </>
        )
      }
    >
      {rows ? <KV items={rows} /> : <p className="muted text-sm">Ещё не создано</p>}
    </Card>
  );
}

function OrderExpenses({ orderId, canAdd }: { orderId: number; canAdd: boolean }) {
  const { data: meta } = useMeta();
  const { data, refetch } = useGet<MoneyRecord[]>(`/orders/${orderId}/expenses/`);
  const { data: categories } = useAll<Category>("expense-categories", {}, canAdd);
  const [form, setForm] = useState<{ category: string; desc: string; cost: { amount: number | string; currency: string } } | null>(null);
  const add = useAction(() => api.post(`/orders/${orderId}/expenses/`, { ...form, category: Number(form?.category) }), {
    success: "Расход добавлен",
    invalidate: ["expenses"],
    onSuccess: () => {
      setForm(null);
      refetch();
    },
  });
  const total = (data ?? []).reduce<Record<string, number>>((acc, e) => {
    acc[e.cost.currency] = (acc[e.cost.currency] ?? 0) + e.cost.amount;
    return acc;
  }, {});
  return (
    <Card
      title="Расходы по заказу"
      padded={false}
      actions={
        canAdd && (
          <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setForm({ category: "", desc: "", cost: { amount: "", currency: meta?.default_currency ?? "USD" } })}>
            Расход
          </Button>
        )
      }
    >
      <DataTable
        rows={data}
        rowKey={(r) => r.id}
        empty={<Empty title="Расходов нет" />}
        columns={[
          { key: "cat", header: "Категория", cell: (r) => r.category_name },
          { key: "desc", header: "Описание", cell: (r) => r.desc || "—" },
          { key: "cost", header: "Сумма", cell: (r) => <span className="font-medium tabular-nums">{money(r.cost)}</span> },
          { key: "who", header: "Кто", cell: (r) => r.user_detail?.name || phone(r.user_detail?.phone) },
          { key: "when", header: "Дата", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
        ]}
      />
      {Object.keys(total).length > 0 && (
        <div className="border-t border-slate-100 px-5 py-3 text-right text-sm dark:border-slate-800">
          Итого: {Object.entries(total).map(([c, v]) => <b key={c} className="ml-2">{money({ amount: v, currency: c })}</b>)}
        </div>
      )}
      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title="Новый расход"
        size="sm"
        footer={<Button loading={add.isPending} disabled={!form?.category} onClick={() => add.mutate()}>Добавить</Button>}
      >
        {form && (
          <div className="space-y-4">
            <Field label="Категория">
              <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">— выберите —</option>
                {categories?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="Сумма">
              <MoneyInput value={form.cost} currencies={meta?.currencies} onChange={(cost) => setForm({ ...form, cost })} />
            </Field>
            <Field label="Описание">
              <Textarea value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
            </Field>
          </div>
        )}
      </Modal>
    </Card>
  );
}

function OrderHistory({ orderId }: { orderId: number }) {
  const { data } = useGet<HistoryEntry[]>(`/orders/${orderId}/history/`);
  if (!data) return <PageLoader />;
  return (
    <Card title="История изменений">
      {!data.length && <Empty title="Нет записей" />}
      <ol className="relative space-y-5 border-l border-slate-200 pl-5 dark:border-slate-800">
        {data.map((h, i) => (
          <li key={i} className="relative">
            <span className={cn("absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-white dark:ring-slate-900", h.type === "created" ? "bg-emerald-500" : "bg-brand-500")} />
            <div className="text-sm">
              <span className="font-medium">{h.user ? h.user.name || phone(h.user.phone) : "Система"}</span>
              <span className="muted"> · {h.type === "created" ? "создал заказ" : "изменил"} · {dateTime(h.date)}</span>
            </div>
            {h.changes.length > 0 && (
              <ul className="mt-1.5 space-y-1 text-sm">
                {h.changes.map((c, j) => (
                  <li key={j} className="rounded-lg bg-slate-50 px-3 py-1.5 dark:bg-slate-800/50">
                    <span className="muted">{c.field}: </span>
                    <span className="line-through opacity-60">{c.old ?? "—"}</span> → <b>{c.new ?? "—"}</b>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function OrderEditModal({ order, onClose }: { order: OrderDetail; onClose: () => void }) {
  const { data: meta } = useMeta();
  const { data: factories } = useAll<Factory>("factories");
  const canPrice = order.actions.edit_price;
  const [form, setForm] = useState({
    order_number: String(order.order_number),
    factory: String(order.factory.id),
    desc: order.desc ?? "",
    reception_date: order.reception_date,
    end_date: order.end_date ?? "",
    price: (order.price ?? { amount: 0, currency: "USD" }) as { amount: number | string; currency: string },
    lost_money: (order.lost_money ?? { amount: 0, currency: "USD" }) as { amount: number | string; currency: string },
    discount: String(order.discount ?? 0),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api.patch(`/orders/${order.id}/`, {
        order_number: Number(form.order_number),
        factory: Number(form.factory),
        desc: form.desc,
        reception_date: form.reception_date,
        end_date: form.end_date || null,
        ...(canPrice ? { price: form.price, lost_money: form.lost_money, discount: Number(form.discount || 0) } : {}),
      }),
    { success: "Заказ сохранён", invalidate: ["orders", "dashboard"], onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={`Изменить заказ №${order.order_number}`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Сохранить</Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Номер заказа" error={errors.order_number}>
          <Input type="number" value={form.order_number} onChange={(e) => setForm({ ...form, order_number: e.target.value })} />
        </Field>
        <Field label="Завод" error={errors.factory}>
          <Select value={form.factory} onChange={(e) => setForm({ ...form, factory: e.target.value })}>
            {factories?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </Select>
        </Field>
        <Field label="Дата приёма" error={errors.reception_date}>
          <Input type="date" value={form.reception_date} onChange={(e) => setForm({ ...form, reception_date: e.target.value })} />
        </Field>
        <Field label="Дата сдачи" error={errors.end_date} hint="Заказ выходит из «Ожидания», когда указана дата сдачи">
          <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </Field>
        <Field label="Описание" className="sm:col-span-2">
          <Textarea value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
        </Field>
        {canPrice && (
          <>
            <Field label="Вся сумма" error={errors.price}>
              <MoneyInput value={form.price} currencies={meta?.currencies} onChange={(price) => setForm({ ...form, price })} />
            </Field>
            <Field label="Полученная сумма" error={errors.lost_money}>
              <MoneyInput value={form.lost_money} currencies={meta?.currencies} onChange={(lost_money) => setForm({ ...form, lost_money })} />
            </Field>
            <Field label="Скидка, %" error={errors.discount}>
              <Input type="number" value={form.discount} onChange={(e) => setForm({ ...form, discount: e.target.value })} />
            </Field>
          </>
        )}
      </div>
    </Modal>
  );
}

/* ---------------------------------------------------------------- Create */

export function OrderCreatePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const meteringId = params.get("metering");
  const designId = params.get("design");
  const { data: metering } = useGet<Metering>(meteringId ? `/meterings/${meteringId}/` : null);
  const { data: design } = useGet<Design>(designId ? `/designs/${designId}/` : null);
  const { data: price } = useGet<{ price: { amount: number; currency: string } | null }>(
    metering?.price ? `/prices/${metering.price.id}/` : null,
  );
  const { data: factories } = useAll<Factory>("factories");
  const canPrice = can("order.view_order_price");

  const [form, setForm] = useState({
    client_phone: "+998",
    client_fio: "",
    factory: "",
    desc: "",
    reception_date: todayISO(),
    count_days: "",
    design_type: "",
    address: "",
    address_link: "",
    price: { amount: 0 as number | string, currency: "USD" },
    lost_money: { amount: 0 as number | string, currency: "USD" },
    discount: "0",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (metering)
      setForm((f) => ({ ...f, address: metering.address ?? "", address_link: metering.address_link ?? "" }));
  }, [metering]);
  useEffect(() => {
    if (design?.types.length) setForm((f) => ({ ...f, design_type: String(design.types[0].id) }));
  }, [design]);
  useEffect(() => {
    if (price?.price) setForm((f) => ({ ...f, price: price.price! }));
  }, [price]);
  useEffect(() => {
    const def = factories?.find((f) => f.name === "Ser-mebel") ?? factories?.[0];
    if (def) setForm((f) => (f.factory ? f : { ...f, factory: String(def.id) }));
  }, [factories]);

  const endDate = useMemo(() => {
    if (!form.count_days || !form.reception_date) return null;
    const d = new Date(form.reception_date + "T00:00:00");
    d.setDate(d.getDate() + Number(form.count_days));
    return d.toISOString().slice(0, 10);
  }, [form.count_days, form.reception_date]);

  const create = useAction(
    () =>
      api
        .post<OrderDetail>("/orders/", {
          ...(metering ? { metering: metering.id } : { client_phone: form.client_phone, client_fio: form.client_fio }),
          design_type: form.design_type ? Number(form.design_type) : null,
          factory: form.factory ? Number(form.factory) : null,
          desc: form.desc,
          reception_date: form.reception_date,
          count_days: form.count_days ? Number(form.count_days) : null,
          address: form.address,
          address_link: form.address_link || null,
          ...(canPrice ? { price: form.price, lost_money: form.lost_money, discount: Number(form.discount || 0) } : {}),
        })
        .then((r) => r.data),
    {
      success: "Заказ создан",
      invalidate: ["orders", "meterings", "designs", "invoices", "dashboard"],
      onSuccess: (o) => navigate(`/orders/${o.id}`, { replace: true }),
    },
  );

  if ((meteringId && !metering) || (designId && !design)) return <PageLoader />;
  const upd = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader back={<BackLink to={design ? `/designs/${design.id}` : "/orders"}>Назад</BackLink>} title="Новый заказ" subtitle={metering ? `По замеру клиента ${metering.client.fio}` : "Заказ без замера"} />
      <div className="space-y-4">
        <Card title="Клиент">
          {metering ? (
            <KV items={[["Клиент", metering.client.fio], ["Телефон", <PhoneLink value={metering.client.phone} />]]} />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Телефон" error={errors.client_phone}>
                <Input inputMode="tel" value={form.client_phone} onChange={upd("client_phone")} />
              </Field>
              <Field label="ФИО (если новый клиент)" error={errors.client_fio}>
                <Input value={form.client_fio} onChange={upd("client_fio")} />
              </Field>
            </div>
          )}
        </Card>
        <Card title="Заказ">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Завод" error={errors.factory}>
              <Select value={form.factory} onChange={upd("factory")}>
                {factories?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </Select>
            </Field>
            {design && (
              <Field label="Вариант дизайна" error={errors.design_type}>
                <Select value={form.design_type} onChange={upd("design_type")}>
                  {design.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </Select>
              </Field>
            )}
            <Field label="Дата приёма" error={errors.reception_date}>
              <Input type="date" value={form.reception_date} onChange={upd("reception_date")} />
            </Field>
            <Field
              label="Срок, дней"
              error={errors.count_days}
              hint={endDate ? `Сдача: ${date(endDate)}` : "Без срока заказ будет в «Ожидании»"}
            >
              <Input type="number" min={1} max={365} value={form.count_days} onChange={upd("count_days")} />
            </Field>
            <Field label="Описание" className="sm:col-span-2">
              <Textarea value={form.desc} onChange={upd("desc")} />
            </Field>
          </div>
        </Card>
        <Card title="Адрес">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Адрес" error={errors.address}>
              <Input value={form.address} onChange={upd("address")} />
            </Field>
            <Field label="Ссылка на карту" error={errors.address_link}>
              <Input type="url" value={form.address_link} onChange={upd("address_link")} />
            </Field>
          </div>
        </Card>
        {canPrice && (
          <Card title="Цена">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Вся сумма" error={errors.price}>
                <MoneyInput value={form.price} currencies={meta?.currencies} onChange={(price) => setForm({ ...form, price })} />
              </Field>
              <Field label="Получено" error={errors.lost_money}>
                <MoneyInput value={form.lost_money} currencies={meta?.currencies} onChange={(lost_money) => setForm({ ...form, lost_money })} />
              </Field>
              <Field label="Скидка, %" error={errors.discount}>
                <Input type="number" value={form.discount} onChange={upd("discount")} />
              </Field>
            </div>
          </Card>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => navigate(-1)}>Отмена</Button>
          <Button size="lg" loading={create.isPending} onClick={() => create.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Создать заказ
          </Button>
        </div>
      </div>
    </div>
  );
}
