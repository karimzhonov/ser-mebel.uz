import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Banknote,
  CalendarClock,
  Factory,
  Hammer,
  Package,
  PhoneCall,
  Ruler,
  TrendingUp,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useGet, useMeta } from "@/api/hooks";
import type { Money, Overview, Tone } from "@/api/types";
import { cn } from "@/lib/cn";
import { dateTime, money, num, phone } from "@/lib/format";
import { DeadlinePill } from "./domain";
import { Card, Empty, PageLoader, TONES } from "./ui";

const SERIES: Record<string, { label: string; color: string }> = {
  invoices: { label: "Arizalar", color: "#f59684" },
  meterings: { label: "O'lchovlar", color: "#6fb4ba" },
  orders: { label: "Buyurtmalar", color: "#1f747d" },
};

function moneyList(items: Money[] | undefined) {
  if (!items?.length) return money({ amount: 0, currency: "USD" });
  return items.map((m) => money(m)).join(" + ");
}

/** The overview tab of the dashboard. `from`/`to` are YYYY-MM-DD or "". */
export function OverviewPanel({ from, to }: { from: string; to: string }) {
  const { data, isLoading } = useGet<Overview>("/dashboard/overview/", { date_from: from, date_to: to });
  if (isLoading || !data) return <PageLoader />;
  const { funnel, orders, money: cash, accounting, production, meterings, call_center } = data;
  const count = (key: string) => funnel?.steps.find((s) => s.key === key)?.count;
  const range = from || to ? "davr uchun" : "butun davr";

  return (
    <div className="space-y-4">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {count("invoices") !== undefined && (
          <Kpi
            to="/call-center"
            icon={<PhoneCall className="h-5 w-5" />}
            tone="primary"
            label={`Arizalar ${range}`}
            value={count("invoices")}
            hint={call_center ? `javobsiz: ${call_center.unanswered}` : undefined}
            alert={!!call_center?.unanswered}
          />
        )}
        {count("meterings") !== undefined && (
          <Kpi
            to="/meterings"
            icon={<Ruler className="h-5 w-5" />}
            tone="info"
            label={`O'lchovlar ${range}`}
            value={count("meterings")}
            hint={meterings ? `bugun: ${meterings.today} · o'tkazib yuborilgan: ${meterings.missed}` : undefined}
            alert={!!meterings?.missed}
          />
        )}
        {orders && (
          <>
            <Kpi
              to="/orders"
              icon={<Package className="h-5 w-5" />}
              tone="ok"
              label={`Yangi buyurtmalar ${range}`}
              value={orders.new}
              hint={`topshirildi: ${orders.done}`}
            />
            <Kpi
              to="/orders?warning=danger"
              icon={<AlertTriangle className="h-5 w-5" />}
              tone={orders.overdue ? "danger" : "idle"}
              label="Hozir ishda"
              value={orders.active}
              hint={`kechikkan: ${orders.overdue} · yaqin: ${orders.due_soon}`}
              alert={!!orders.overdue}
            />
          </>
        )}
        {cash && (
          <Kpi
            to="/orders"
            icon={<Banknote className="h-5 w-5" />}
            tone="warn"
            label="Mijozlar qarzi"
            value={moneyList(cash.debt)}
            hint={`${cash.debtors} ta buyurtma to'lanmagan`}
            small
          />
        )}
        {accounting && accounting.profit !== null && (
          <Kpi
            to="/accounting/income"
            icon={<TrendingUp className="h-5 w-5" />}
            tone={accounting.profit >= 0 ? "ok" : "danger"}
            label={`Foyda ${range}`}
            value={money({ amount: accounting.profit, currency: accounting.currency })}
            hint={`kirim ${money({ amount: accounting.income ?? 0, currency: accounting.currency })}`}
            small
          />
        )}
      </div>

      {/* Funnel + pipeline */}
      <div className="grid gap-4 xl:grid-cols-5">
        {funnel && (
          <Card
            className="xl:col-span-3"
            title="Sotuv voronkasi"
            actions={
              funnel.total_conversion !== null && (
                <span className="text-sm">
                  O'lchov → buyurtma: <b className="text-brand-700 dark:text-accent-200">{funnel.total_conversion}%</b>
                </span>
              )
            }
          >
            <Funnel steps={funnel.steps} />
            {!!funnel.cancelled && (
              <p className="muted mt-3 text-xs">Davr ichida bekor qilingan o'lchovlar: {funnel.cancelled}</p>
            )}
          </Card>
        )}
        {orders && (
          <Card className={funnel ? "xl:col-span-2" : "xl:col-span-5"} title="Bosqichlar bo'yicha buyurtmalar" padded={false}>
            <OrderPipeline byStatus={orders.by_status} />
          </Card>
        )}
      </div>

      {/* Chart + money */}
      <div className="grid gap-4 xl:grid-cols-3">
        {data.timeline.series.length > 0 && (
          <Card className={cash || accounting ? "xl:col-span-2" : "xl:col-span-3"} title={`Dinamika ${data.monthly ? "oylar bo'yicha" : "kunlar bo'yicha"}`}>
            <MultiChart series={data.timeline.series} points={data.timeline.points} monthly={data.monthly} />
          </Card>
        )}
        {(cash || accounting) && (
          <Card title="Pul">
            <dl className="space-y-4">
              {cash && (
                <>
                  <MoneyRow label={`Shartnomalar summasi ${range}`} value={moneyList(cash.contracts)} />
                  <MoneyRow label={`Ular bo'yicha olingan`} value={moneyList(cash.paid)} />
                  <MoneyRow label="Mijozlar qarzi (barcha faol)" value={moneyList(cash.debt)} tone="warn" />
                </>
              )}
              {accounting && (
                <div className="grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
                  {accounting.income !== null && (
                    <MoneyRow label="Kirim" value={money({ amount: accounting.income, currency: accounting.currency })} tone="ok" />
                  )}
                  {accounting.expense !== null && (
                    <MoneyRow label="Chiqim" value={money({ amount: accounting.expense, currency: accounting.currency })} tone="danger" />
                  )}
                </div>
              )}
            </dl>
          </Card>
        )}
      </div>

      {/* Production */}
      {production && (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card className={production.assemblers ? "xl:col-span-2" : "xl:col-span-3"} title="Ishlab chiqarish — hozirgi navbat">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {production.stages.map((s) => (
                <Link
                  key={s.key}
                  to={`${s.link}`}
                  className="group rounded-2xl border border-slate-200 p-4 transition hover:border-brand-300 hover:shadow-card dark:border-slate-700 dark:hover:border-brand-600"
                >
                  <div className="muted text-xs font-medium">{s.label}</div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900 dark:text-white">{s.count}</div>
                  <div className="muted text-xs tabular-nums">{num(s.square)} m²</div>
                </Link>
              ))}
            </div>
          </Card>
          {production.assemblers && (
            <Card title="Yig'uvchilar yuklamasi" padded={false}>
              {!production.assemblers.length && <Empty title="Faol yig'ishlar yo'q" />}
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {production.assemblers.map((a, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                    <span className="flex items-center gap-2 truncate">
                      <Hammer className="h-4 w-4 shrink-0 text-slate-400" />
                      {a.user ? a.user.name || phone(a.user.phone) : <span className="muted">Tayinlanmagan</span>}
                    </span>
                    <span className="whitespace-nowrap tabular-nums">
                      <b>{a.count}</b> <span className="muted">· {num(a.square)} m²</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {/* Lists */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {orders && (
          <Card title="Yaqin topshirish muddatlari" padded={false} actions={<MoreLink to="/orders" />}>
            {!orders.deadlines.length && <Empty title="Muddatli buyurtmalar yo'q" />}
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {orders.deadlines.map((o) => (
                <li key={o.id}>
                  <Link to={`/orders/${o.id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="min-w-0 truncate">
                      <b>№{o.number}</b> · {o.client}
                    </span>
                    <DeadlinePill deadline={o.deadline} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {meterings && (
          <Card title="Yaqin o'lchovlar" padded={false} actions={<MoreLink to="/meterings" />}>
            {!meterings.upcoming.length && <Empty title="Rejalashtirilgan o'lchov yo'q" />}
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {meterings.upcoming.map((m) => (
                <li key={m.id}>
                  <Link to={`/meterings/${m.id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{m.client}</span>
                      <span className="muted block truncate text-xs">{m.address || phone(m.phone)}</span>
                    </span>
                    <span className="flex items-center gap-1 whitespace-nowrap text-xs font-medium text-brand-700 dark:text-accent-200">
                      <CalendarClock className="h-3.5 w-3.5" /> {dateTime(m.when)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {orders && orders.factories.length > 0 && (
          <Card title="Zavodlar yuklamasi" padded={false}>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {orders.factories.map((f) => {
                const max = Math.max(...orders.factories.map((x) => x.count), 1);
                return (
                  <li key={f.name} className="px-5 py-3 text-sm">
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <Factory className="h-4 w-4 text-slate-400" /> {f.name}
                      </span>
                      <b className="tabular-nums">{f.count}</b>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
                      <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${(f.count / max) * 100}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}

function Kpi({
  to,
  icon,
  tone,
  label,
  value,
  hint,
  alert,
  small,
}: {
  to: string;
  icon: ReactNode;
  tone: Tone;
  label: string;
  value: ReactNode;
  hint?: string;
  alert?: boolean;
  small?: boolean;
}) {
  return (
    <Link to={to} className="card group relative flex flex-col gap-3 p-4 transition hover:-translate-y-0.5 hover:shadow-pop">
      <div className="flex items-center justify-between">
        <div className={cn("rounded-xl p-2", TONES[tone].soft, TONES[tone].text)}>{icon}</div>
        {alert && <span className="h-2 w-2 animate-pulse rounded-full bg-rose-500" />}
      </div>
      <div className="min-w-0">
        <div className="muted truncate text-xs font-medium">{label}</div>
        <div className={cn("truncate font-semibold tabular-nums text-slate-900 dark:text-white", small ? "text-lg" : "text-2xl")}>
          {value ?? "—"}
        </div>
        {hint && <div className="muted mt-0.5 truncate text-xs">{hint}</div>}
      </div>
    </Link>
  );
}

function Funnel({ steps }: { steps: { key: string; label: string; count: number; conversion: number | null }[] }) {
  const max = Math.max(...steps.map((s) => s.count), 1);
  return (
    <ol className="space-y-2.5">
      {steps.map((s, i) => (
        <li key={s.key} className="grid grid-cols-[minmax(110px,160px)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate">{s.label}</span>
          <div className="h-7 rounded-lg bg-slate-100 dark:bg-slate-800">
            <div
              className="flex h-7 items-center justify-end rounded-lg px-2 text-xs font-semibold text-white transition-all"
              style={{
                width: `${Math.max((s.count / max) * 100, s.count ? 6 : 0)}%`,
                background: `linear-gradient(90deg, #053c43, ${i % 2 ? "#1f747d" : "#105e67"})`,
              }}
            >
              {s.count > 0 && s.count}
            </div>
          </div>
          <span className={cn("w-12 text-right text-xs tabular-nums", s.conversion === null ? "muted" : "font-semibold")}>
            {s.conversion === null ? (s.count === 0 ? "0" : "") : `${s.conversion}%`}
          </span>
        </li>
      ))}
    </ol>
  );
}

function OrderPipeline({ byStatus }: { byStatus: { key: string; count: number }[] }) {
  const { data: meta } = useMeta();
  const navigate = useNavigate();
  const total = byStatus.reduce((a, b) => a + b.count, 0) || 1;
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {byStatus.map((s) => {
        const item = meta?.order_statuses.find((x) => x.value === s.key);
        const tone = item?.tone ?? "idle";
        return (
          <li key={s.key}>
            <button
              onClick={() => navigate(`/orders?status=${s.key}`)}
              className="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <span className={cn("h-2 w-2 shrink-0 rounded-full", TONES[tone].dot)} />
              <span className="flex-1 truncate">{item?.label ?? s.key}</span>
              <span className="hidden h-1.5 w-24 rounded-full bg-slate-100 sm:block dark:bg-slate-800">
                <span className={cn("block h-1.5 rounded-full", TONES[tone].dot)} style={{ width: `${(s.count / total) * 100}%` }} />
              </span>
              <b className="w-8 text-right tabular-nums">{s.count}</b>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function MultiChart({
  series,
  points,
  monthly,
}: {
  series: string[];
  points: Record<string, number | string>[];
  monthly: boolean;
}) {
  if (!points.length) return <Empty title="Davr uchun ma'lumot yo'q" />;
  const fmt = (d: string) => {
    if (!d) return "";
    const [y, m, day] = d.split("-");
    return monthly ? `${m}.${y.slice(2)}` : `${day}.${m}`;
  };
  return (
    <div className="h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <defs>
            {series.map((s) => (
              <linearGradient key={s} id={`g-${s}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={SERIES[s]?.color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={SERIES[s]?.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-800" vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmt} tickLine={false} axisLine={false} fontSize={11} stroke="currentColor" className="text-slate-400" minTickGap={20} />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={11} stroke="currentColor" className="text-slate-400" />
          <Tooltip
            labelFormatter={(d: string) => fmt(d)}
            formatter={(v: number, name: string) => [v, SERIES[name]?.label ?? name]}
            contentStyle={{ borderRadius: 12, border: "1px solid rgb(226 232 240)", fontSize: 12 }}
          />
          <Legend formatter={(name: string) => SERIES[name]?.label ?? name} iconType="circle" wrapperStyle={{ fontSize: 12 }} />
          {series.map((s) => (
            <Area key={s} type="monotone" dataKey={s} stroke={SERIES[s]?.color} strokeWidth={2} fill={`url(#g-${s})`} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function MoneyRow({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div>
      <dt className="muted text-xs">{label}</dt>
      <dd className={cn("text-lg font-semibold tabular-nums", tone ? TONES[tone].text : "text-slate-900 dark:text-white")}>{value}</dd>
    </div>
  );
}

function MoreLink({ to }: { to: string }) {
  return (
    <Link to={to} className="flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline dark:text-accent-200">
      Barchasi <ArrowRight className="h-3.5 w-3.5" />
    </Link>
  );
}
