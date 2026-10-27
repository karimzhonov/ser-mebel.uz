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
  Design,
  Factory,
  HistoryEntry,
  Metering,
  Money,
  Order,
  OrderDetail,
  StatusStats,
} from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { OrderFinance } from "@/pages/finance/Wallets";
import {
  AddressLink,
  BackLink,
  DeadlinePill,
  FolderButton,
  MoneyLeft,
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
import { date, dateTime, leftPercent, money, num, phone, todayISO } from "@/lib/format";
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
        title="Buyurtmalar"
        subtitle={`Jami: ${stats?.total ?? "…"}`}
        actions={
          can("order.add_order") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/orders/new")}>
              Yangi buyurtma
            </Button>
          )
        }
      />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile
          label="Kechikkan"
          value={warn.danger ?? "…"}
          tone="danger"
          icon={<AlertTriangle className="h-5 w-5" />}
          active={state.warning === "danger"}
          onClick={() => set({ warning: state.warning === "danger" ? "" : "danger" })}
        />
        <StatTile
          label={`${meta?.warning_order_days ?? 7} kundan kam`}
          value={warn.warning ?? "…"}
          tone="warn"
          icon={<Clock className="h-5 w-5" />}
          active={state.warning === "warning"}
          onClick={() => set({ warning: state.warning === "warning" ? "" : "warning" })}
        />
        <StatTile
          label="Muddatida"
          value={warn.success ?? "…"}
          tone="ok"
          icon={<CheckCircle2 className="h-5 w-5" />}
          active={state.warning === "success"}
          onClick={() => set({ warning: state.warning === "success" ? "" : "success" })}
        />
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <Chip active={!selected.length} onClick={() => set({ status: "" })}>
          Barchasi · {stats?.total ?? "…"}
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
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="№, mijoz, telefon, manzil" />
          <Select className="lg:w-48" value={state.factory} onChange={(e) => set({ factory: e.target.value })}>
            <option value="">Barcha zavodlar</option>
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
              header: "Mijoz",
              cell: (r) => (
                <div>
                  <div className="font-medium">{r.client?.fio ?? "—"}</div>
                  <PhoneLink value={r.client?.phone} />
                </div>
              ),
            },
            { key: "factory", header: "Zavod", cell: (r) => r.factory.name, hideOnMobile: true },
            { key: "address", header: "Manzil", cell: (r) => <span className="line-clamp-1 max-w-[200px]">{r.address}</span>, hideOnMobile: true },
            { key: "status", header: "Holat", cell: (r) => <OrderStatusBadge status={r.status} label={r.status_label} /> },
            { key: "dates", header: "Qabul / topshirish", cell: (r) => <span className="whitespace-nowrap text-xs">{date(r.reception_date)}<br />{date(r.end_date)}</span> },
            { key: "deadline", header: "Muddat", cell: (r) => <DeadlinePill deadline={r.deadline} /> },
            ...(showMoney
              ? [
                  { key: "total", header: "Jami", cell: (r: Order) => <span className="tabular-nums">{money(r.total_price)}</span> },
                  { key: "left", header: "Qoldiq", cell: (r: Order) => <MoneyLeft left={r.money_left} total={r.total_price} /> },
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
                {showMoney && <MoneyLeft className="text-sm" left={r.money_left} total={r.total_price} />}
              </div>
            </div>
          )}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      <Card title="Qabul sanasi bo'yicha buyurtmalar" className="mt-4">
        <TimelineChart data={stats?.timeline} height={200} />
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- Detail */

export function OrderDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: o, isLoading } = useGet<OrderDetail>(`/orders/${id}/`);
  const [tab, setTab] = useState("info");
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<null | "detailing" | "next-status" | "go-to-assembly">(null);

  const inv = ["orders", "dashboard", "detailings", "assemblies", "meterings"];
  const run = useAction(
    (path: string) => api.post(`/orders/${id}/${path}/`).then((r) => r.data),
    {
      success: "Tayyor",
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
    detailing: ["Detalirovkaga yuborilsinmi?", "Detalirovka xodimlariga xabar boradi."],
    "next-status": [`«${a.next_status_label}» holatiga o'tkazilsinmi?`, "Mas'ullarga SMS/Telegram xabari boradi."],
    "go-to-assembly": ["Yig'ishga yuborilsinmi?", "Buyurtma «Yig'ish» holatiga o'tadi."],
  } as const;

  return (
    <div>
      <PageHeader
        back={<BackLink to="/orders">Buyurtmalar</BackLink>}
        title={`Buyurtma №${o.order_number}`}
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
                Tahrirlash
              </Button>
            )}
            {a.detailing && (
              <Button variant="success" icon={<BookOpen className="h-4 w-4" />} onClick={() => setConfirm("detailing")}>
                Detalirovkaga
              </Button>
            )}
            {a.go_to_assembly && (
              <Button variant="success" icon={<Hammer className="h-4 w-4" />} onClick={() => setConfirm("go-to-assembly")}>
                Yig'ishga
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
          { value: "info", label: "Ma'lumot" },
          { value: "production", label: "Ishlab chiqarish" },
          ...(a.finance && o.order_number ? [{ value: "finance", label: "Moliya" }] : []),
          { value: "history", label: "Tarix" },
        ]}
      />

      {tab === "info" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Buyurtma" className="lg:col-span-2">
            <KV
              items={[
                ["Mijoz", o.client ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(o.client.phone)}`}>{o.client.fio}</Link> : "—"],
                ["Telefon", <PhoneLink value={o.client?.phone} />],
                ["Manzil", <AddressLink address={o.address} link={o.address_link} />],
                ["Zavod", o.factory.name],
                ["Qabul sanasi", date(o.reception_date)],
                ["Topshirish sanasi", date(o.end_date, "ko'rsatilmagan")],
                ["Dizayn", o.design_type?.name ?? "—"],
                ["O'lchov", o.metering ? <Link className="text-brand-700 hover:underline" to={`/meterings/${o.metering}`}>Ochish →</Link> : "—"],
              ]}
            />
            {o.desc && <p className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/50">{o.desc}</p>}
          </Card>
          {"price" in o && (
            <Card title="To'lov">
              <div className="space-y-3">
                <div>
                  <div className="muted text-xs">Jami ({num(o.discount)}% chegirma bilan)</div>
                  <div className="text-2xl font-semibold tabular-nums">{money(o.total_price)}</div>
                </div>
                <KV
                  items={[
                    ["Summa", money(o.price)],
                    ["Olingan", money(o.lost_money)],
                    ["Qoldiq", <MoneyLeft className="text-base" left={o.money_left} total={o.total_price} />],
                  ]}
                />
                <PaidBar left={o.money_left} total={o.total_price} />
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === "production" && (
        <div className="grid gap-4 md:grid-cols-2">
          <ProdCard
            title="Detalirovka"
            to={p.detailing ? `/production/detailing?open=${p.detailing.id}` : undefined}
            folder={p.detailing?.folder}
            rows={p.detailing && [
              ["Maydon", num(p.detailing.square)],
              ["Bo'yash maydoni", num(p.detailing.painter_square)],
              ["Rover maydoni", num(p.detailing.rover_square)],
              ["Bajarildi", <Check ok={p.detailing.done} />],
            ]}
          />
          <ProdCard
            title="Rover"
            to={p.rover ? `/production/rover?open=${p.rover.id}` : undefined}
            folder={p.rover?.folder}
            rows={p.rover && [
              ["Maydon", num(p.rover.square)],
              ...(p.rover.price ? ([["Narx", money(p.rover.price)]] as [string, string][]) : []),
              ["Bajarildi", <Check ok={p.rover.done} />],
            ]}
          />
          <ProdCard
            title="Molyar"
            to={p.painter ? `/production/painter?open=${p.painter.id}` : undefined}
            folder={p.painter?.folder}
            rows={p.painter && [
              ["Tur", p.painter.waiting_rover ? <span className="text-amber-600">rover tugashini kutmoqda</span> : p.painter.type ?? "tayinlanmagan"],
              ["Maydon", num(p.painter.square)],
              ...(p.painter.price ? ([["Narx", money(p.painter.price)]] as [string, string][]) : []),
              ["Bajarildi", <Check ok={p.painter.done} />],
            ]}
          />
          <ProdCard
            title="Yig'ish / O'rnatish"
            to={p.assembly && !BEFORE_ASSEMBLY.includes(o.status) ? `/production/assembly?open=${p.assembly.id}` : undefined}
            folder={p.assembly?.folder}
            rows={p.assembly && [
              ["Yig'uvchi", p.assembly.user ? p.assembly.user.name || phone(p.assembly.user.phone) : "tayinlanmagan"],
              ["Maydon", num(p.assembly.square)],
              ...(p.assembly.price ? ([["Narx", money(p.assembly.price)]] as [string, string][]) : []),
              ...(BEFORE_ASSEMBLY.includes(o.status)
                ? ([["Navbat", <span className="text-amber-600">detalirovkadan keyin</span>]] as [string, JSX.Element][])
                : []),
              ["Yig'ish", <Check ok={p.assembly.done} />],
              ["O'rnatish", <Check ok={p.assembly.installing_done} />],
            ]}
          />
        </div>
      )}

      {tab === "finance" && o.order_number && <OrderFinance orderNumber={o.order_number} />}
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

// Assembly work starts after detailing (backend: order/assembly/services.py).
const BEFORE_ASSEMBLY = ["waiting", "created", "detailing"];

function PaidBar({ left, total }: { left?: Money | null; total?: Money | null }) {
  const pct = leftPercent(left, total);
  if (pct === null) return null;
  const paid = 100 - pct;
  return (
    <div className="mt-1">
      <div className="mb-1 flex justify-between text-xs">
        <span className="muted">To'langan {paid}%</span>
        <span className="muted">Qoldiq {pct}%</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-rose-100 dark:bg-rose-500/20">
        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${paid}%` }} />
      </div>
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
                Ochish →
              </Link>
            )}
          </>
        )
      }
    >
      {rows ? <KV items={rows} /> : <p className="muted text-sm">Hali yaratilmagan</p>}
    </Card>
  );
}

function OrderHistory({ orderId }: { orderId: number }) {
  const { data } = useGet<HistoryEntry[]>(`/orders/${orderId}/history/`);
  if (!data) return <PageLoader />;
  return (
    <Card title="O'zgarishlar tarixi">
      {!data.length && <Empty title="Yozuvlar yo'q" />}
      <ol className="relative space-y-5 border-l border-slate-200 pl-5 dark:border-slate-800">
        {data.map((h, i) => (
          <li key={i} className="relative">
            <span className={cn("absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-white dark:ring-slate-900", h.type === "created" ? "bg-emerald-500" : "bg-brand-500")} />
            <div className="text-sm">
              <span className="font-medium">{h.user ? h.user.name || phone(h.user.phone) : "Tizim"}</span>
              <span className="muted"> · {h.type === "created" ? "buyurtma yaratdi" : "o'zgartirdi"} · {dateTime(h.date)}</span>
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
    { success: "Buyurtma saqlandi", invalidate: ["orders", "dashboard"], onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={`Buyurtma №${order.order_number} ni tahrirlash`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Buyurtma raqami" error={errors.order_number}>
          <Input type="number" value={form.order_number} onChange={(e) => setForm({ ...form, order_number: e.target.value })} />
        </Field>
        <Field label="Zavod" error={errors.factory}>
          <Select value={form.factory} onChange={(e) => setForm({ ...form, factory: e.target.value })}>
            {factories?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </Select>
        </Field>
        <Field label="Qabul sanasi" error={errors.reception_date}>
          <Input type="date" value={form.reception_date} onChange={(e) => setForm({ ...form, reception_date: e.target.value })} />
        </Field>
        <Field label="Topshirish sanasi" error={errors.end_date} hint="Topshirish sanasi ko'rsatilgach, buyurtma «Kutilmoqda» holatidan chiqadi">
          <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </Field>
        <Field label="Tavsif" className="sm:col-span-2">
          <Textarea value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
        </Field>
        {canPrice && (
          <>
            <Field label="Umumiy summa" error={errors.price}>
              <MoneyInput value={form.price} currencies={meta?.currencies} onChange={(price) => setForm({ ...form, price })} />
            </Field>
            <Field label="Olingan summa" error={errors.lost_money}>
              <MoneyInput value={form.lost_money} currencies={meta?.currencies} onChange={(lost_money) => setForm({ ...form, lost_money })} />
            </Field>
            <Field label="Chegirma, %" error={errors.discount}>
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
      success: "Buyurtma yaratildi",
      invalidate: ["orders", "meterings", "designs", "invoices", "dashboard"],
      onSuccess: (o) => navigate(`/orders/${o.id}`, { replace: true }),
    },
  );

  if ((meteringId && !metering) || (designId && !design)) return <PageLoader />;
  const upd = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader back={<BackLink to={design ? `/designs/${design.id}` : "/orders"}>Orqaga</BackLink>} title="Yangi buyurtma" subtitle={metering ? `Mijoz ${metering.client.fio} o'lchovi bo'yicha` : "O'lchovsiz buyurtma"} />
      <div className="space-y-4">
        <Card title="Mijoz">
          {metering ? (
            <KV items={[["Mijoz", metering.client.fio], ["Telefon", <PhoneLink value={metering.client.phone} />]]} />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Telefon" error={errors.client_phone}>
                <Input inputMode="tel" value={form.client_phone} onChange={upd("client_phone")} />
              </Field>
              <Field label="F.I.Sh. (agar yangi mijoz bo'lsa)" error={errors.client_fio}>
                <Input value={form.client_fio} onChange={upd("client_fio")} />
              </Field>
            </div>
          )}
        </Card>
        <Card title="Buyurtma">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Zavod" error={errors.factory}>
              <Select value={form.factory} onChange={upd("factory")}>
                {factories?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </Select>
            </Field>
            {design && (
              <Field label="Dizayn varianti" error={errors.design_type}>
                <Select value={form.design_type} onChange={upd("design_type")}>
                  {design.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </Select>
              </Field>
            )}
            <Field label="Qabul sanasi" error={errors.reception_date}>
              <Input type="date" value={form.reception_date} onChange={upd("reception_date")} />
            </Field>
            <Field
              label="Muddat, kun"
              error={errors.count_days}
              hint={endDate ? `Topshirish: ${date(endDate)}` : "Muddat ko'rsatilmasa, buyurtma «Kutilmoqda» holatida bo'ladi"}
            >
              <Input type="number" min={1} max={365} value={form.count_days} onChange={upd("count_days")} />
            </Field>
            <Field label="Tavsif" className="sm:col-span-2">
              <Textarea value={form.desc} onChange={upd("desc")} />
            </Field>
          </div>
        </Card>
        <Card title="Manzil">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Manzil" error={errors.address}>
              <Input value={form.address} onChange={upd("address")} />
            </Field>
            <Field label="Xarita havolasi" error={errors.address_link}>
              <Input type="url" value={form.address_link} onChange={upd("address_link")} />
            </Field>
          </div>
        </Card>
        {canPrice && (
          <Card title="Narx">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Umumiy summa" error={errors.price}>
                <MoneyInput value={form.price} currencies={meta?.currencies} onChange={(price) => setForm({ ...form, price })} />
              </Field>
              <Field label="Olingan" error={errors.lost_money}>
                <MoneyInput value={form.lost_money} currencies={meta?.currencies} onChange={(lost_money) => setForm({ ...form, lost_money })} />
              </Field>
              <Field label="Chegirma, %" error={errors.discount}>
                <Input type="number" value={form.discount} onChange={upd("discount")} />
              </Field>
            </div>
          </Card>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => navigate(-1)}>Bekor qilish</Button>
          <Button size="lg" loading={create.isPending} onClick={() => create.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Buyurtma yaratish
          </Button>
        </div>
      </div>
    </div>
  );
}
