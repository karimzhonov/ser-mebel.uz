import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { date as fmtDate } from "@/lib/format";
import { Button, Input } from "./ui";

/** YYYY-MM-DD in local time. */
export function iso(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
export function monthStartISO() {
  const d = new Date();
  return iso(new Date(d.getFullYear(), d.getMonth(), 1));
}

function presets(): { label: string; from: string; to: string }[] {
  const t = new Date();
  const y = t.getFullYear();
  const m = t.getMonth();
  const q = Math.floor(m / 3) * 3;
  return [
    { label: "Bugun", from: iso(t), to: iso(t) },
    { label: "Kecha", from: iso(addDays(t, -1)), to: iso(addDays(t, -1)) },
    { label: "7 kun", from: iso(addDays(t, -6)), to: iso(t) },
    { label: "30 kun", from: iso(addDays(t, -29)), to: iso(t) },
    { label: "Shu oy", from: iso(new Date(y, m, 1)), to: iso(t) },
    { label: "O'tgan oy", from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0)) },
    { label: "Chorak", from: iso(new Date(y, q, 1)), to: iso(t) },
    { label: "Shu yil", from: iso(new Date(y, 0, 1)), to: iso(t) },
    { label: "Butun davr", from: "", to: "" },
  ];
}

export function rangeLabel(from: string, to: string) {
  if (!from && !to) return "Butun davr";
  const match = presets().find((p) => p.from === from && p.to === to);
  if (match) return match.label;
  if (from && to) return from === to ? fmtDate(from) : `${fmtDate(from)} — ${fmtDate(to)}`;
  return from ? `${fmtDate(from)} dan` : `${fmtDate(to)} gacha`;
}

/** "From — to" period picker with quick presets. Values are YYYY-MM-DD or "". */
export function DateRangeFilter({
  from,
  to,
  onChange,
  className,
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ from, to });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft({ from, to }), [from, to, open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  const invalid = !!draft.from && !!draft.to && draft.from > draft.to;
  const apply = (f: string, t: string) => {
    onChange(f, t);
    setOpen(false);
  };
  const active = !!(from || to);

  return (
    <div ref={ref} className={cn("relative", className)}>
      <div className="flex">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={cn(
            "input flex h-10 items-center gap-2 whitespace-nowrap pr-3 text-left",
            active && "rounded-r-none border-brand-300 dark:border-brand-600",
          )}
        >
          <CalendarDays className="h-4 w-4 shrink-0 text-slate-400" />
          <span className="font-medium">{rangeLabel(from, to)}</span>
          <ChevronDown className={cn("h-4 w-4 text-slate-400 transition", open && "rotate-180")} />
        </button>
        {active && (
          <button
            type="button"
            title="Butun davr uchun ko'rsatish"
            onClick={() => onChange("", "")}
            className="input flex h-10 w-10 items-center justify-center rounded-l-none border-l-0 border-brand-300 p-0 text-slate-400 hover:text-slate-700 dark:border-brand-600"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[min(92vw,420px)] animate-slide-up rounded-2xl border border-slate-200 bg-white p-4 shadow-pop dark:border-slate-700 dark:bg-slate-900 sm:left-auto">
          <div className="grid grid-cols-3 gap-1.5">
            {presets().map((p) => {
              const selected = p.from === from && p.to === to;
              return (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => apply(p.from, p.to)}
                  className={cn(
                    "rounded-lg px-2 py-1.5 text-xs font-medium transition",
                    selected
                      ? "bg-brand-800 text-white dark:bg-accent-200 dark:text-brand-900"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200",
                  )}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <label>
              <span className="label">Sanadan</span>
              <Input type="date" value={draft.from} max={draft.to || undefined} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
            </label>
            <label>
              <span className="label">Sanagacha</span>
              <Input type="date" value={draft.to} min={draft.from || undefined} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
            </label>
          </div>
          {invalid && <p className="mt-2 text-xs text-rose-600">Boshlanish sanasi tugash sanasidan keyin</p>}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Bekor qilish
            </Button>
            <Button size="sm" disabled={invalid} onClick={() => apply(draft.from, draft.to)}>
              Qo'llash
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
