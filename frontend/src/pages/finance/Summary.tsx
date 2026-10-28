import { useState } from "react";
import { Download, Minus, Plus } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useGet } from "@/api/hooks";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Button, Card, Empty, PageHeader, Select, StatTile } from "@/components/ui";
import { useUrlState } from "@/lib/useUrlState";
import { CatLabel, downloadFile, OperationModal, som, useFinMe, useMembers } from "./shared";
import type { CatItem, Summary } from "./types";

function CategoryList({ items, tone }: { items: CatItem[]; tone: "danger" | "ok" }) {
  const total = items.reduce((s, i) => s + i.amount, 0) || 1;
  if (!items.length) return <Empty title="Bu davrda yo'q" />;
  return (
    <ul className="space-y-3">
      {items.map((i) => (
        <li key={i.code}>
          <div className="mb-1 flex justify-between gap-2 text-sm">
            <CatLabel c={i} />
            <span className="whitespace-nowrap font-medium tabular-nums">
              {som(tone === "danger" ? -i.amount : i.amount)} · {Math.round((i.amount * 100) / total)}%
              <span className="muted ml-1 font-normal">({i.count})</span>
            </span>
          </div>
          <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-2 rounded-full" style={{ width: `${(i.amount * 100) / total}%`, background: i.color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function FinanceSummaryPage() {
  const { data: me } = useFinMe();
  const { state, set } = useUrlState({ date_from: monthStartISO(), date_to: iso(new Date()), member: "" });
  const { data: members } = useMembers({}, !!me?.view_all);
  const { data: s, isFetching } = useGet<Summary>("/finance/summary/", state);
  const [form, setForm] = useState<"income" | "expense" | null>(null);
  const [exporting, setExporting] = useState(false);

  return (
    <div>
      <PageHeader
        title="Moliya — Xulosa"
        subtitle={s?.member ? `👤 ${s.member.name}` : "🏢 Ser mebel (hammasi)"}
        actions={
          <>
            {me?.view_all && (
              <Button
                variant="outline"
                icon={<Download className="h-4 w-4" />}
                loading={exporting}
                onClick={() => {
                  setExporting(true);
                  downloadFile("/finance/export/", { date_from: state.date_from, date_to: state.date_to }, "SerMebel.xlsx").finally(() => setExporting(false));
                }}
              >
                Excel
              </Button>
            )}
            {(me?.view_all || me?.member) && (
              <>
                <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setForm("income")}>
                  Kirim
                </Button>
                <Button icon={<Minus className="h-4 w-4" />} onClick={() => setForm("expense")}>
                  Chiqim
                </Button>
              </>
            )}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        {me?.view_all && (
          <Select className="w-56" value={state.member} onChange={(e) => set({ member: e.target.value })}>
            <option value="">🏢 Hammasi</option>
            {members?.filter((m) => m.has_wallet).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        )}
      </div>
      <div className={`mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6 ${isFetching ? "opacity-70" : ""}`}>
        <StatTile label="🔴 Xarajatlar" value={som(-(s?.expense ?? 0))} tone="danger" hint={`${s?.count ?? 0} ta amal`} />
        <StatTile label="🟢 Daromadlar" value={som(s?.income ?? 0)} tone="ok" />
        <StatTile label="💠 Balans" value={som(s?.balance ?? 0)} tone={(s?.balance ?? 0) < 0 ? "danger" : "primary"} />
        {s?.member ? (
          <StatTile label="👛 Hamyonda hozir" value={som(s.wallet_balance ?? 0)} tone={(s.wallet_balance ?? 0) < 0 ? "danger" : "info"} />
        ) : (
          <>
            <StatTile label="💸 Xodimlarga berildi" value={som(s?.given_to_staff ?? 0)} tone="info" hint="daromad emas" />
            <StatTile label="👔 Rahbarga (shaxsiy)" value={som(s?.boss_personal ?? 0)} tone="idle" />
            <StatTile label="🏠 Uy uchun (shaxsiy)" value={som(s?.home ?? 0)} tone="idle" />
          </>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Xarajatlar turlari bo'yicha">
          <CategoryList items={s?.expense_by_category ?? []} tone="danger" />
        </Card>
        <Card title="Daromadlar turlari bo'yicha">
          <CategoryList items={s?.income_by_category ?? []} tone="ok" />
        </Card>
        <Card title="Oylar bo'yicha (12 oy)" className="lg:col-span-2">
          {s?.months?.length ? (
            <div style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={s.months} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
                  <YAxis tickLine={false} axisLine={false} fontSize={11} tickFormatter={(v: number) => `${(v / 1e6).toFixed(1).replace(".0", "")}M`} />
                  <Tooltip formatter={(v: number) => som(v)} contentStyle={{ borderRadius: 12, fontSize: 12 }} />
                  <Legend />
                  <Bar dataKey="income" name="Daromad" fill="#34a26f" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expense" name="Xarajat" fill="#e5677a" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty title="Ma'lumot yo'q" />
          )}
        </Card>
        <Card title="👷 Oylik — kimga">
          {s?.salary_by_worker?.length ? (
            <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
              {s.salary_by_worker.map((w) => (
                <li key={w.name} className="flex justify-between py-2">
                  <span>{w.name}</span>
                  <span className="font-medium tabular-nums">{som(w.amount)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="Bu davrda oylik yo'q" />
          )}
        </Card>
        {!s?.member && (
          <Card title="Ichki harakatlar">
            <ul className="space-y-2 text-sm">
              <li className="flex justify-between">
                <span>🔄 Xodimlar o'rtasida o'tkazildi</span>
                <span className="font-medium tabular-nums">{som(s?.transfers ?? 0)}</span>
              </li>
              <li className="flex justify-between">
                <span>💱 Dollar kursi</span>
                <span className="font-medium tabular-nums">{som(s?.usd_rate ?? 0)}</span>
              </li>
            </ul>
            <p className="muted mt-3 text-xs">O'tkazmalar, rahbardan olingan pul va shaxsiy xarajatlar kompaniya xarajati/daromadiga kirmaydi.</p>
          </Card>
        )}
      </div>
      {form && <OperationModal defaultKind={form} defaultMember={state.member ? Number(state.member) : me?.member?.id} onClose={() => setForm(null)} />}
    </div>
  );
}
