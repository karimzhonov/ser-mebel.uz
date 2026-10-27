import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGet } from "@/api/hooks";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Badge, Card, DataTable, Modal, PageHeader, SearchInput, Segmented, StatTile } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { CatLabel, inCur, som, useCategories } from "./shared";
import type { FinOrder, WalletRow } from "./types";

export function FinanceWalletsPage() {
  const nav = useNavigate();
  const { state, set } = useUrlState({ date_from: monthStartISO(), date_to: iso(new Date()) });
  const { data, isFetching } = useGet<{ results: WalletRow[]; staff_total: number }>("/finance/wallets/", state);
  return (
    <div>
      <PageHeader title="Hamyonlar" subtitle="Har bir xodim qo'lidagi pul (Telegram botdagi «👛 Hamyonlar»)" />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <StatTile label="💰 Xodimlar qo'lida jami" value={som(data?.staff_total ?? 0)} tone="primary" />
      </div>
      <Card padded={false}>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.member.id}
          onRowClick={(r) => nav(`/finance/operations?member=${r.member.id}&date_from=${state.date_from}&date_to=${state.date_to}`)}
          rowClassName={(r) => (r.balance < 0 && r.member.role !== "admin" ? "bg-rose-50/60 dark:bg-rose-500/5" : undefined)}
          columns={[
            {
              key: "n",
              header: "Xodim",
              cell: (r) => (
                <span className="font-medium">
                  {r.member.role === "admin" ? "💼 " : "👤 "}
                  {r.member.name}
                </span>
              ),
            },
            {
              key: "b",
              header: "Hamyonda",
              cell: (r) =>
                r.member.role === "admin" ? (
                  <span className="muted">kassa</span>
                ) : (
                  <span className={`font-semibold tabular-nums ${r.balance < 0 ? "text-rose-600" : ""}`}>{som(r.balance)}</span>
                ),
            },
            { key: "i", header: "Davrda berildi", cell: (r) => <span className="tabular-nums">{som(r.period_income)}</span> },
            { key: "e", header: "Davrda sarfladi", cell: (r) => <span className="tabular-nums">{som(r.period_expense)}</span> },
            { key: "l", header: "Oxirgi yozuv", cell: (r) => date(r.last_day), hideOnMobile: true },
            {
              key: "r",
              header: "Oylik hisob",
              cell: (r) =>
                r.member.role === "admin" ? "—" : <Badge tone={r.report_submitted ? "ok" : "warn"}>{r.report_submitted ? "topshirdi" : "yo'q"} · {r.report_month}</Badge>,
              hideOnMobile: true,
            },
          ]}
        />
      </Card>
    </div>
  );
}

const BUCKETS = [
  { value: "jarayonda,yangi,kutish,yakun", label: "Faol" },
  { value: "jarayonda", label: "🧾 Ishda" },
  { value: "yangi", label: "🆕 Деталировка" },
  { value: "kutish", label: "⏳ Ожидание" },
  { value: "yakun", label: "✅ Готов (qoldiq)" },
  { value: "tugadi", label: "📁 Tugagan" },
];

export function FinanceOrdersPage() {
  const { state, set } = useUrlState({ bucket: BUCKETS[0].value, search: "" });
  const { data, isFetching } = useGet<{ results: FinOrder[] }>("/finance/orders/", { ...state, with_ops: "1" });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <PageHeader title="Buyurtmalar bo'yicha moliya" subtitle="Har bir zakazga sarflangan pul, mijozdan olingan, foyda va qoldiq" />
      <div className="mb-4">
        <Segmented value={state.bucket} onChange={(bucket) => set({ bucket })} options={BUCKETS} />
      </div>
      <Card padded={false}>
        <div className="border-b border-slate-100 p-4 dark:border-slate-800">
          <SearchInput value={state.search} onChange={(search) => set({ search })} placeholder="ID yoki mijoz" />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.ref}
          onRowClick={(r) => setOpen(r.ref)}
          columns={[
            {
              key: "r",
              header: "Zakaz",
              cell: (r) => (
                <span>
                  <span className="font-semibold">{r.ref}</span> · {r.client}
                  {r.manual && <Badge className="ml-1">qo'lda</Badge>}
                </span>
              ),
            },
            { key: "st", header: "Holat", cell: (r) => <span className="text-sm">{r.status_label}</span>, hideOnMobile: true },
            { key: "t", header: "Shartnoma", cell: (r) => <span className="tabular-nums">{r.total ? inCur(r.total, r.currency) : "—"}</span> },
            { key: "rest", header: "Mijoz qoldig'i", cell: (r) => <span className="tabular-nums">{r.rest === null ? "—" : inCur(r.rest, r.currency)}</span> },
            {
              key: "s",
              header: "Sarflandi",
              cell: (r) => (
                <span className="tabular-nums">
                  {som(r.spent)}
                  {r.spent_percent !== null && <span className={`ml-1 text-xs ${r.spent_percent > 80 ? "text-rose-600" : "muted"}`}>{r.spent_percent}%</span>}
                </span>
              ),
            },
            {
              key: "p",
              header: "Foyda",
              cell: (r) => (r.profit === null ? "—" : <span className={`font-semibold tabular-nums ${r.profit < 0 ? "text-rose-600" : "text-emerald-600"}`}>{som(r.profit)}</span>),
            },
          ]}
        />
      </Card>
      {open && <OrderModal refId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function OrderModal({ refId, onClose }: { refId: string; onClose: () => void }) {
  const { data: o } = useGet<FinOrder>(`/finance/orders/${encodeURIComponent(refId)}/`);
  return (
    <Modal open onClose={onClose} title={o ? `🧾 ${o.ref} — ${o.client}` : refId} size="lg">
      {o && <OrderFinanceBody o={o} />}
    </Modal>
  );
}

/** The order's «Moliya» tab: same money picture as «Buyurtmalar moliyasi». */
export function OrderFinance({ orderNumber }: { orderNumber: number }) {
  const { data: o, isLoading } = useGet<FinOrder>(`/finance/orders/${orderNumber}/`);
  return (
    <Card title="Buyurtma moliyasi">
      {o ? <OrderFinanceBody o={o} /> : !isLoading && <p className="muted text-sm">Ma'lumot yo'q</p>}
    </Card>
  );
}

function OrderFinanceBody({ o }: { o: FinOrder }) {
  const { data: cats } = useCategories();
  const byCode = Object.fromEntries((cats ?? []).map((c) => [c.code, c]));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Shartnoma" value={o.total ? inCur(o.total, o.currency) : "—"} tone="primary" hint={o.currency === "USD" ? `≈ ${som(o.price_uzs)}` : undefined} />
        <StatTile label="Saytda olingan" value={o.paid === null ? "—" : inCur(o.paid, o.currency)} tone="ok" hint={o.rest !== null ? `qoldiq ${inCur(o.rest, o.currency)}` : undefined} />
        <StatTile label="Sarflandi" value={som(o.spent)} tone="danger" hint={o.spent_percent !== null ? `${o.spent_percent}%` : undefined} />
        <StatTile label={o.profit !== null && o.profit < 0 ? "Zarar" : "Foyda"} value={o.profit === null ? "—" : som(o.profit)} tone={o.profit !== null && o.profit < 0 ? "danger" : "ok"} />
      </div>
      {o.bonus && (
        <p className="text-sm">
          🎁 Bonus: <b>{o.bonus.status_label}</b> · Готов {date(o.bonus.ready_date)}
          {o.bonus.bonus && <> · {o.bonus.percent}% = {som(o.bonus.bonus)}</>}
        </p>
      )}
      {o.by_category.length > 0 && (
        <ul className="space-y-1 text-sm">
          {o.by_category.map((c) => (
            <li key={c.code} className="flex justify-between">
              <CatLabel c={byCode[c.code]} />
              <span className="tabular-nums">{som(c.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
        {o.operations?.map((t) => (
          <div key={t.id} className="flex justify-between gap-3 py-2">
            <span>
              <span className="muted">#{t.number} · {date(t.date)}</span> · {t.member_detail.name} · {t.category_detail.emoji} {t.category_detail.name}
              {t.comment && <span className="muted"> — {t.comment}</span>}
            </span>
            <span className={`whitespace-nowrap tabular-nums ${t.kind === "income" ? "text-emerald-600" : "text-rose-600"}`}>
              {som(t.kind === "income" ? t.amount : -Number(t.amount), true)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
