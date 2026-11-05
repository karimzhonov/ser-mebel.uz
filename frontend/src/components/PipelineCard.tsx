import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlarmClockOff, Brush, Calculator, Ruler, ShoppingBag } from "lucide-react";
import type { PersonRef, PipelineRole, SalesPipeline, Tone } from "@/api/types";
import { cn } from "@/lib/cn";
import { dateTime } from "@/lib/format";
import { Card, Empty, TONES } from "./ui";

/** Accepts the block under `pipeline`, or under `production` when it carries `counts`
 * (the backend may ship it under either name — the old `production` has `stages`). */
export function pickPipeline(data: Record<string, unknown>): SalesPipeline | null {
  const p = (data.pipeline ?? null) as SalesPipeline | null;
  if (p?.counts) return p;
  const prod = data.production as Partial<SalesPipeline> | null | undefined;
  return prod && "counts" in prod && prod.counts ? (prod as SalesPipeline) : null;
}

const ROLE_LABEL: Record<PipelineRole, string> = {
  zamerchi: "Zamerchilar",
  dizayner: "Dizaynerlar",
  narxchi: "Narx (menejerlar)",
  menejer: "Menejerlar",
};
const ROLES: PipelineRole[] = ["zamerchi", "dizayner", "narxchi", "menejer"];

const KIND: Record<string, { label: string; path: string }> = {
  zamer: { label: "Zamer", path: "meterings" },
  metering: { label: "Zamer", path: "meterings" },
  design: { label: "Dizayn", path: "designs" },
  price: { label: "Narx", path: "prices" },
};

function late(hours: number | null | undefined) {
  if (hours == null) return "";
  if (hours < 1) return "1 soatdan kam";
  if (hours < 48) return `${Math.round(hours)} soat`;
  return `${Math.floor(hours / 24)} kun`;
}

function who(p: string | PersonRef | null | undefined) {
  if (!p) return "tayinlanmagan";
  return typeof p === "string" ? p : p.name || p.phone || `#${p.id}`;
}

function Tile({ to, label, value, tone }: { to: string; label: string; value: number; tone?: Tone }) {
  const hot = !!value && tone;
  return (
    <Link
      to={to}
      className={cn(
        "rounded-xl border px-3 py-2 transition hover:border-brand-300 dark:hover:border-brand-600",
        hot ? cn(TONES[tone!].soft, "border-transparent") : "border-slate-200 dark:border-slate-700",
      )}
    >
      <div className="muted truncate text-xs">{label}</div>
      <div className={cn("text-xl font-semibold tabular-nums", hot ? TONES[tone!].text : "text-slate-900 dark:text-white")}>{value}</div>
    </Link>
  );
}

function Column({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
        {icon} {title}
      </div>
      <div className="grid grid-cols-3 gap-2">{children}</div>
    </div>
  );
}

/** «Zamer · Dizayn · Narx» on the dashboard — for the superuser and «Bosh menejer». */
export function PipelineCard({ p }: { p: SalesPipeline }) {
  const c = p.counts;
  const icon = "h-4 w-4 text-slate-400";
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="Zamer · Dizayn · Narx">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <Column icon={<Ruler className={icon} />} title="Zamer">
              <Tile to="/meterings?tab=today" label="Bugun" value={c.zamer_today} />
              <Tile to="/meterings?tab=today" label="Muddati o'tgan" value={c.zamer_overdue} tone="danger" />
              <Tile to="/meterings?tab=waiting" label="Fayl kutilmoqda" value={c.zamer_waiting} tone="warn" />
            </Column>
            <Column icon={<Brush className={icon} />} title="Dizayn">
              <Tile to="/designs?tab=work" label="Ishda" value={c.design_work} />
              <Tile to="/designs?tab=overdue" label="Muddati o'tgan" value={c.design_overdue} tone="danger" />
              <Tile to="/designs?tab=review" label="Mijozda" value={c.design_review} tone="info" />
            </Column>
            <Column icon={<Calculator className={icon} />} title="Narx">
              <Tile to="/prices?tab=work" label="Ishda" value={c.price_work} />
              <Tile to="/prices?tab=overdue" label="Muddati o'tgan" value={c.price_overdue} tone="danger" />
              <Tile to="/prices?tab=review" label="Mijozda" value={c.price_review} tone="info" />
            </Column>
          </div>
          <Link
            to="/presentations?tab=order_ready"
            className="flex items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-sm transition hover:border-brand-300 dark:border-slate-700 dark:hover:border-brand-600"
          >
            <span className="flex items-center gap-1.5">
              <ShoppingBag className={icon} /> Buyurtmaga tayyor
            </span>
            <b className={cn("tabular-nums", c.order_ready ? TONES.ok.text : "")}>{c.order_ready}</b>
          </Link>
          <div>
            <div className={cn("mb-2 flex items-center gap-1.5 text-sm font-semibold", p.overdue.length ? TONES.danger.text : "")}>
              <AlarmClockOff className="h-4 w-4" /> Kechikkanlar
            </div>
            {!p.overdue.length ? (
              <p className="muted text-sm">Kechikkan ish yo'q</p>
            ) : (
              <ul className="divide-y divide-rose-100 overflow-hidden rounded-xl border border-rose-200 dark:divide-rose-500/20 dark:border-rose-500/30">
                {p.overdue.map((r) => {
                  const k = KIND[r.kind] ?? { label: r.kind, path: "" };
                  const to = r.url && r.url.startsWith("/") ? r.url : k.path ? `/${k.path}/${r.id}` : "";
                  const inner = (
                    <>
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          <span className="muted font-normal">{k.label} · </span>
                          {r.client}
                        </span>
                        <span className="muted block truncate text-xs">
                          {who(r.person)}
                          {r.due_at && ` · muddat ${dateTime(r.due_at)}`}
                        </span>
                      </span>
                      <span className={cn("whitespace-nowrap text-xs font-semibold", TONES.danger.text)}>{late(r.late_hours)}</span>
                    </>
                  );
                  const cls = "flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-rose-50 dark:hover:bg-rose-500/10";
                  return (
                    <li key={`${r.kind}-${r.id}`}>
                      {to ? (
                        <Link to={to} className={cls}>{inner}</Link>
                      ) : r.url ? (
                        <a href={r.url} className={cls}>{inner}</a>
                      ) : (
                        <div className={cls}>{inner}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </Card>
      <Card title="Xodimlar yuklamasi" padded={false}>
        {!p.load.length ? (
          <Empty title="Ochiq ish yo'q" />
        ) : (
          <div className="max-h-[28rem] overflow-y-auto">
            {ROLES.map((role) => {
              const rows = p.load.filter((r) => r.role === role);
              if (!rows.length) return null;
              return (
                <section key={role}>
                  <h4 className="bg-slate-50 px-5 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-800/50">{ROLE_LABEL[role]}</h4>
                  <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                    {rows.map((r, i) => (
                      <li key={r.person?.id ?? `none-${i}`} className="flex items-center justify-between gap-3 px-5 py-2 text-sm">
                        <span className="truncate">{r.person ? r.person.name : <span className="muted">Tayinlanmagan</span>}</span>
                        <span className="whitespace-nowrap tabular-nums">
                          <b>{r.open}</b> <span className="muted">ochiq</span>
                          {r.overdue > 0 && <b className={cn("ml-2", TONES.danger.text)}>{r.overdue} kech</b>}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
