import { useMemo, useState } from "react";
import { FileSpreadsheet, HardHat, Search } from "lucide-react";
import { useGet } from "@/api/hooks";
import { DateRangeFilter, iso, monthStartISO, rangeLabel } from "@/components/DateRangeFilter";
import { Badge, Button, Card, Empty, Input, PageHeader, Select, Skeleton, StatTile } from "@/components/ui";
import { cn } from "@/lib/cn";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { SalaryModal } from "./SalaryModal";
import { som, usd } from "./shared";
import type { WorkerCard, WorkerCardResponse, WorkerListItem } from "./types";

const NO_GROUP = "Ro'yxatda yo'q (qo'lda yozilgan)";

function initials(name: string) {
  const parts = name.replace(/[^\p{L}\s]/gu, " ").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

/* ------------------------------------------------------------------ the worker list */
function WorkerList({
  workers,
  selected,
  onSelect,
}: {
  workers: WorkerListItem[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const map = new Map<string, WorkerListItem[]>();
    for (const w of workers) {
      if (needle && !`${w.name} ${w.position} ${w.group}`.toLowerCase().includes(needle)) continue;
      const g = w.in_catalog ? w.group || "Boshqa" : NO_GROUP;
      map.set(g, [...(map.get(g) ?? []), w]);
    }
    return [...map.entries()];
  }, [workers, q]);

  return (
    <div className="flex max-h-[calc(100vh-220px)] flex-col">
      <div className="relative border-b border-slate-100 p-3 dark:border-slate-800">
        <Search className="pointer-events-none absolute left-6 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <Input className="pl-9" placeholder="Ism, bo'lim, lavozim…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {!groups.length && <Empty title="Topilmadi" />}
        {groups.map(([group, items]) => (
          <div key={group} className="mb-2">
            <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{group}</div>
            {items.map((w) => (
              <button
                key={w.name}
                onClick={() => onSelect(w.name)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition",
                  selected === w.name
                    ? "bg-brand-50 ring-1 ring-brand-200 dark:bg-brand-500/10 dark:ring-brand-500/30"
                    : "hover:bg-slate-50 dark:hover:bg-slate-800/60",
                  !w.is_active && "opacity-60",
                )}
              >
                <span
                  className={cn(
                    "grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold",
                    selected === w.name ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
                  )}
                >
                  {initials(w.name)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{w.name}</span>
                  {w.position && <span className="muted block truncate text-xs">{w.position}</span>}
                </span>
                <span className={cn("whitespace-nowrap text-xs tabular-nums", w.total ? "font-semibold" : "muted")}>
                  {w.total ? som(w.total).replace(" so'm", "") : "—"}
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ spreadsheet-like grid */
const th = "sticky top-0 z-10 whitespace-nowrap border-b border-r border-emerald-200 bg-emerald-50 px-3 py-2 text-left text-xs font-semibold text-emerald-900 last:border-r-0 dark:border-emerald-900/60 dark:bg-emerald-950 dark:text-emerald-200";
const td = "whitespace-nowrap border-b border-r border-slate-200 px-3 py-1.5 last:border-r-0 dark:border-slate-800";
const rowNo = "w-10 select-none border-b border-r border-slate-200 bg-slate-50 px-2 py-1.5 text-center text-[11px] text-slate-400 dark:border-slate-800 dark:bg-slate-900/60";

function PaymentsSheet({ card }: { card: WorkerCard }) {
  if (!card.rows.length) return <Empty title="Bu davrda oylik yo'q" text="Davrni o'zgartirib ko'ring." />;
  return (
    <div className="max-h-[60vh] overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className={cn(th, "w-10 text-center")}>#</th>
            <th className={th}>Sana</th>
            <th className={th}>Vaqt</th>
            <th className={cn(th, "text-right")}>Summa (so'm)</th>
            <th className={cn(th, "text-right")}>Dollarda</th>
            <th className={th}>Kim berdi</th>
            <th className={th}>Izoh (nima uchun)</th>
            <th className={th}>Turi</th>
          </tr>
        </thead>
        <tbody>
          {card.rows.map((r, i) => (
            <tr key={r.id} className="even:bg-slate-50/60 hover:bg-brand-50/60 dark:even:bg-slate-800/20 dark:hover:bg-brand-500/5">
              <td className={rowNo}>{i + 1}</td>
              <td className={td}>{date(r.date)}</td>
              <td className={cn(td, "muted tabular-nums")}>{r.time || "—"}</td>
              <td className={cn(td, "text-right font-medium tabular-nums")}>{som(r.amount).replace(" so'm", "")}</td>
              <td className={cn(td, "text-right tabular-nums")}>{r.currency === "USD" && r.orig_amount != null ? usd(r.orig_amount) : ""}</td>
              <td className={td}>{r.member}</td>
              <td className={cn(td, "min-w-[200px] max-w-[360px] whitespace-normal")}>{r.comment || <span className="muted">—</span>}</td>
              <td className={td}>
                {r.pay_type === "Oylik" ? (
                  <Badge tone="ok">🧾 Oylik</Badge>
                ) : r.pay_type === "Avans" ? (
                  <Badge tone="warn">💵 Avans</Badge>
                ) : (
                  <Badge tone="idle">—</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-semibold">
            <td className={cn(rowNo, "border-b-0 bg-slate-100 dark:bg-slate-800")}>Σ</td>
            <td colSpan={2} className="border-r border-slate-200 bg-slate-100 px-3 py-2 dark:border-slate-800 dark:bg-slate-800">
              Jami · {card.count} ta
            </td>
            <td className="border-r border-slate-200 bg-slate-100 px-3 py-2 text-right tabular-nums dark:border-slate-800 dark:bg-slate-800">
              {som(card.total).replace(" so'm", "")}
            </td>
            <td colSpan={4} className="bg-slate-100 px-3 py-2 dark:bg-slate-800" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function GiversTable({ card }: { card: WorkerCard }) {
  if (!card.by_giver.length) return <Empty title="—" />;
  return (
    <table className="w-full border-separate border-spacing-0 text-sm">
      <thead>
        <tr>
          <th className={th}>Kim bergan</th>
          <th className={cn(th, "text-right")}>Summa</th>
          <th className={cn(th, "text-right")}>Soni</th>
        </tr>
      </thead>
      <tbody>
        {card.by_giver.map((g) => (
          <tr key={g.name} className="even:bg-slate-50/60 dark:even:bg-slate-800/20">
            <td className={td}>{g.name}</td>
            <td className={cn(td, "text-right font-medium tabular-nums")}>{som(g.amount).replace(" so'm", "")}</td>
            <td className={cn(td, "text-right tabular-nums")}>{g.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ one worker */
function CardView({ card, period }: { card: WorkerCard; period: string }) {
  const [salary, setSalary] = useState(false);
  return (
    <div className="space-y-4">
      {salary && <SalaryModal card={card} onClose={() => setSalary(false)} />}
      <div className="card flex flex-wrap items-center gap-4 p-5">
        <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-brand-500 text-lg font-bold text-white">{initials(card.name)}</div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-lg font-semibold text-slate-900 dark:text-white">{card.name}</h2>
          <p className="muted text-sm">
            {[card.group, card.position].filter(Boolean).join(" · ") || "Bo'lim / lavozim ko'rsatilmagan"}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 text-right">
          {!card.in_catalog && <Badge tone="warn">«Ishchilar» ro'yxatida yo'q</Badge>}
          <span className="muted text-xs">📅 {period}</span>
          <span className="muted text-xs">Butun davr: {som(card.all_time)}</span>
          {card.pay_day && <span className="muted text-xs">🗓 Oylik kuni: har oyning {card.pay_day}-sanasi</span>}
        </div>
        {card.worker_id && (
          <Button icon={<FileSpreadsheet className="h-4 w-4" />} onClick={() => setSalary(true)}>
            Oylik chiqarish
          </Button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile tone="warn" label="💵 Avans (shu davrda)" value={som(card.advance)} />
        <StatTile tone="ok" label="🧾 Oylik (shu davrda)" value={som(card.salary)} hint={card.other ? `Turi yozilmagan: ${som(card.other)}` : undefined} />
        <StatTile tone="primary" label="💰 Jami (shu davrda)" value={som(card.total)} />
        <StatTile tone="info" label="📝 Necha marta · oxirgi" value={`${card.count} marta`} hint={card.last_date ? `oxirgi: ${date(card.last_date)}` : "hali berilmagan"} />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[300px_1fr]">
        <Card title="👤 Kim bergan" padded={false} className="self-start overflow-hidden">
          <GiversTable card={card} />
        </Card>
        <Card title="📋 Har bir oylik (yangisi tepada)" padded={false} className="overflow-hidden">
          <PaymentsSheet card={card} />
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ page */
export default function WorkerCardPage() {
  const { state, set } = useUrlState({ date_from: monthStartISO(), date_to: iso(new Date()), worker: "" });
  const { data, isFetching } = useGet<WorkerCardResponse>("/finance/worker-card/", state);
  const workers = data?.workers ?? [];
  const period = rangeLabel(state.date_from, state.date_to);

  return (
    <div>
      <PageHeader title="👷 Ishchi kartasi" subtitle="Kim qancha oylik olgan, qachon va nima uchun" />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        {/* phones: a plain picker instead of the side list */}
        <Select className="w-full sm:w-64 lg:hidden" value={state.worker} onChange={(e) => set({ worker: e.target.value })}>
          <option value="">Ishchini tanlang…</option>
          {workers.map((w) => (
            <option key={w.name} value={w.name}>
              {w.name}
              {w.total ? ` — ${som(w.total)}` : ""}
            </option>
          ))}
        </Select>
        {isFetching && <span className="muted text-xs">Yuklanmoqda…</span>}
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card padded={false} className="hidden self-start overflow-hidden lg:block">
          {data ? (
            <WorkerList workers={workers} selected={state.worker} onSelect={(worker) => set({ worker })} />
          ) : (
            <div className="space-y-2 p-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          )}
        </Card>
        <div className={cn("min-w-0", isFetching && "opacity-70 transition-opacity")}>
          {data?.card ? (
            <CardView card={data.card} period={period} />
          ) : (
            <Card>
              <Empty
                icon={<HardHat className="h-8 w-8" />}
                title="Ishchini tanlang"
                text="Chapdagi ro'yxatdan ishchini bosing — shu davrdagi avans, oylik va har bir to'lov chiqadi."
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
