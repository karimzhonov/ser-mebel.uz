import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, PageLoader, Select, StatTile } from "@/components/ui";
import { cn } from "@/lib/cn";
import { date } from "@/lib/format";
import { som } from "./shared";

/** GET /finance/overhead/ (backend accounting/overhead.py) */
interface OrderRow {
  ref: string;
  client: string;
  ready_date: string;
  price: number;
  spent: number;
  gross: number;
  overhead: number;
  net: number;
}
interface MonthRow {
  month: string;
  label: string;
  counted: boolean;
  total: number;
  allocated: number;
  difference: number;
  sales: number;
  parts: { key: string; label: string; amount: number }[];
  sheets: { sheet: number; worker: string; amount: number }[];
}
interface OverheadReport {
  since: string;
  rate: { months: string[]; overhead: number; sales: number; rate: number };
  months: MonthRow[];
  pool: { gross: number; overhead: number; withdrawn: number; available: number; paid_orders: OrderRow[]; waiting: OrderRow[] };
  can_withdraw: boolean;
  wallets: { id: number; name: string; balance: number }[];
}

const pct = (r: number) => `${(r * 100).toFixed(1)}%`;

/** Stage 3 «Foyda»: umumiy xarajat by month, the rate, the profit that may be taken out. */
export function FinanceProfitPage() {
  const { data, isLoading } = useGet<OverheadReport>("/finance/overhead/", { months: 6 });
  const [withdrawing, setWithdrawing] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  if (isLoading || !data) return <PageLoader />;
  const p = data.pool;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Foyda va umumiy xarajat"
        subtitle={`Umumiy xarajat (ijara, kommunal, ofis, oklad, kompaniya mashinalari, rahbar oyligi) buyurtmalarga shartnoma summasiga qarab bo'linadi. Ulush buyurtma «Готов» bo'lgan kuni oxirgi 3 oy stavkasi bilan qotiriladi. ${date(data.since)} dan boshlab.`}
        actions={
          data.can_withdraw && (
            <Button disabled={p.available <= 0} onClick={() => setWithdrawing(true)}>
              💰 Foyda yechish
            </Button>
          )
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Hozirgi stavka" value={pct(data.rate.rate)} tone="primary" hint={`${data.rate.months[0]} – ${data.rate.months[data.rate.months.length - 1]}: ${som(data.rate.overhead)} ÷ ${som(data.rate.sales)}`} />
        <StatTile label="To'langan buyurtmalar yalpi foydasi" value={som(p.gross)} tone="ok" hint={`${p.paid_orders.length} ta buyurtma: shartnoma − to'g'ridan-to'g'ri xarajat`} />
        <StatTile label={`(−) Umumiy xarajat, ${date(data.since)} dan`} value={som(p.overhead)} tone="danger" hint={`(−) yechilgan: ${som(p.withdrawn)} (rahbar oyligidan ortig'i ham)`} />
        <StatTile label="Yechish mumkin" value={som(p.available)} tone={p.available > 0 ? "ok" : "danger"} />
      </div>

      <Card title="Oylar bo'yicha umumiy xarajat" padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="muted text-left text-xs uppercase">
              <tr>
                <th className="px-4 py-2">Oy</th>
                <th className="px-4 py-2 text-right">Haqiqiy</th>
                <th className="px-4 py-2 text-right">Buyurtmalarga tushgan</th>
                <th className="px-4 py-2 text-right">Farq</th>
                <th className="hidden px-4 py-2 text-right sm:table-cell">Tayyor bo'lganlar summasi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.months.map((m) => (
                <MonthLine key={m.month} m={m} open={open === m.month} onToggle={() => setOpen(open === m.month ? null : m.month)} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted px-4 py-3 text-xs">
          «Farq» musbat bo'lsa — buyurtmalar haqiqiy xarajatdan kamroq ko'tardi (foydadan ayiriladi); manfiy — ko'proq. Stavka oldindan hisoblangani uchun ular hech qachon aniq teng bo'lmaydi.
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <OrdersCard title="To'liq to'langan buyurtmalar (foydaga kiradi)" rows={p.paid_orders} />
        <OrdersCard title="To'lov kutilayotganlar (hali kirmaydi)" rows={p.waiting} muted />
      </div>

      {withdrawing && <WithdrawModal report={data} onClose={() => setWithdrawing(false)} />}
    </div>
  );
}

function MonthLine({ m, open, onToggle }: { m: MonthRow; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={onToggle}>
        <td className="px-4 py-2">
          {m.label}
          {!m.counted && (
            <Badge tone="idle" className="ml-2">
              eski qoida
            </Badge>
          )}
        </td>
        <td className="px-4 py-2 text-right tabular-nums">{som(m.total)}</td>
        <td className="px-4 py-2 text-right tabular-nums">{som(m.allocated)}</td>
        <td className={cn("px-4 py-2 text-right tabular-nums", m.difference > 0 ? "text-rose-600" : "text-emerald-700 dark:text-emerald-400")}>{som(m.difference)}</td>
        <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{som(m.sales)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="bg-slate-50 px-6 py-3 dark:bg-slate-800/40">
            {m.parts.length === 0 ? (
              <span className="muted">Bu oyda umumiy xarajat yo'q.</span>
            ) : (
              <ul className="space-y-1">
                {m.parts.map((x) => (
                  <li key={x.key} className="flex justify-between gap-3">
                    <span>{x.label}</span>
                    <span className="tabular-nums">{som(x.amount)}</span>
                  </li>
                ))}
                {m.sheets.map((s) => (
                  <li key={s.sheet} className="muted flex justify-between gap-3 pl-4 text-xs">
                    <span>
                      Varaq №{s.sheet} · {s.worker}
                    </span>
                    <span className="tabular-nums">{som(s.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function OrdersCard({ title, rows, muted }: { title: string; rows: OrderRow[]; muted?: boolean }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? (
        <Empty title="Hozircha yo'q" text="Ulush buyurtma «Готов» bo'lgach, bir soat ichida yoziladi." />
      ) : (
        <div className={cn("divide-y divide-slate-100 text-sm dark:divide-slate-800", muted && "opacity-75")}>
          {rows.map((r) => (
            <div key={r.ref} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
              <span>
                <Link to={`/finance/orders?search=${encodeURIComponent(r.ref)}`} className="font-medium hover:underline">
                  ID {r.ref}
                </Link>{" "}
                · {r.client} <span className="muted">· Готов {date(r.ready_date)}</span>
                <span className="muted block text-xs">
                  {som(r.price)} − {som(r.spent)} − ulush {som(r.overhead)}
                </span>
              </span>
              <b className={cn("tabular-nums", r.net < 0 ? "text-rose-600" : "text-emerald-700 dark:text-emerald-400")}>{som(r.net)}</b>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function WithdrawModal({ report, onClose }: { report: OverheadReport; onClose: () => void }) {
  const first = report.wallets.find((w) => w.balance > 0) ?? report.wallets[0];
  const [member, setMember] = useState(first ? String(first.id) : "");
  const [amount, setAmount] = useState("");
  const [comment, setComment] = useState("");
  const wallet = report.wallets.find((w) => String(w.id) === member);
  const limit = Math.min(report.pool.available, wallet?.balance ?? 0);
  const save = useAction(() => api.post("/finance/overhead/withdraw/", { member: Number(member), amount, comment }), {
    success: "Foyda yechildi",
    invalidate: ["/finance/overhead/", "finance"],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="💰 Foyda yechish"
      footer={
        <Button loading={save.isPending} disabled={!member || !Number(amount) || Number(amount) > limit} onClick={() => save.mutate()}>
          Yechish
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          Yechish mumkin: <b>{som(report.pool.available)}</b> — mijoz to'liq to'lagan buyurtmalar foydasidan butun umumiy xarajat ayirilgan, hamyondagi puldan
          ko'p emas. Bu kompaniya xarajati emas va hech bir buyurtmaga yozilmaydi.
        </p>
        <Field label="Qaysi hamyondan">
          <Select value={member} onChange={(e) => setMember(e.target.value)}>
            {report.wallets.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} — {som(w.balance)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Summa (so'm)" hint={`Ko'pi bilan ${som(Math.max(limit, 0))}`}>
          <Input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ""))} />
        </Field>
        <Field label="Izoh">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Foyda yechish" />
        </Field>
      </div>
    </Modal>
  );
}
