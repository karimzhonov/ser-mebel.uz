import { useId } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useGet } from "@/api/hooks";
import { Button, Field, IconButton, Input } from "@/components/ui";
import { inCur } from "./shared";
import type { Debt, DebtAllocation } from "./types";

/** Same limit as the backend's MAX_DEBT_ALLOCATIONS. */
export const MAX_ALLOCATIONS = 10;

/** "12.50" -> 1250. null for anything that is not a non-negative amount with at most two
 * meaningful decimals. Parsed as text, so no float rounding reaches the money. */
export function toCents(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const m = /^(\d+)(?:\.(\d*))?$/.exec(String(v).trim());
  if (!m) return null;
  const frac = m[2] ?? "";
  if (/[1-9]/.test(frac.slice(2))) return null;
  const cents = Number(m[1]) * 100 + Number(frac.slice(0, 2).padEnd(2, "0"));
  return Number.isSafeInteger(cents) ? cents : null;
}

/** 1250 -> "12.50", 1200 -> "12". */
export function fromCents(c: number): string {
  const rest = c % 100;
  const whole = (c - rest) / 100;
  return rest ? `${whole}.${String(rest).padStart(2, "0")}` : String(whole);
}

/** `som()` rounds to whole so'm, which would hide a remainder of a few tiyin. */
export function centsLabel(c: number, currency: string): string {
  return currency !== "USD" && c % 100 !== 0 ? `${fromCents(c)} so'm` : inCur(fromCents(c), currency);
}

/** Rows of an old response (no `allocations`) count as one order. */
export function debtAllocations(d: Pick<Debt, "allocations">): DebtAllocation[] {
  return Array.isArray(d.allocations) ? d.allocations : [];
}

export function isSplitDebt(d: Pick<Debt, "allocations">): boolean {
  return debtAllocations(d).length > 1;
}

export interface AllocationRow {
  key: number;
  ref: string;
  amount: string;
}

let nextKey = 1;
export const newRow = (ref = "", amount = ""): AllocationRow => ({ key: nextKey++, ref, amount });

/** Catches the obvious aliases (`#406`, `0406`, `sm-003`); the backend has the final word. */
function refKey(ref: string): string {
  const s = ref.trim().replace(/^#/, "").toUpperCase();
  return /^\d+$/.test(s) ? s.replace(/^0+(?=\d)/, "") : s;
}

export function checkAllocations(rows: AllocationRow[], total: number | null) {
  const seen = new Map<string, number>();
  rows.forEach((r) => {
    const k = refKey(r.ref);
    if (k) seen.set(k, (seen.get(k) ?? 0) + 1);
  });
  const isDuplicate = (r: AllocationRow) => (seen.get(refKey(r.ref)) ?? 0) > 1;
  const hasDuplicates = rows.some(isDuplicate);
  const allRefs = rows.every((r) => !!refKey(r.ref));
  if (rows.length === 1) {
    // an ordinary debt: the order takes the whole sum, no share is entered
    return { ok: allRefs, left: 0, isDuplicate, hasDuplicates };
  }
  const cents = rows.map((r) => toCents(r.amount));
  const used = cents.reduce<number>((sum, c) => sum + (c ?? 0), 0);
  const left = (total ?? 0) - used;
  const amountsOk = cents.every((c) => c !== null && c > 0);
  const ok = allRefs && amountsOk && !hasDuplicates && rows.length <= MAX_ALLOCATIONS && !!total && left === 0;
  return { ok, left, isDuplicate, hasDuplicates };
}

/** The `allocations` body. A single row always carries the whole total. */
export function allocationsPayload(rows: AllocationRow[], total: number) {
  if (rows.length === 1) return [{ ref: rows[0].ref.trim(), amount: fromCents(total) }];
  return rows.map((r) => ({ ref: r.ref.trim(), amount: fromCents(toCents(r.amount) ?? 0) }));
}

/** fieldErrors() joins a nested DRF list into «[object Object]». */
export function cleanAllocationError(msg?: string): string | undefined {
  return msg?.includes("[object Object]") ? "Buyurtma qatorlarini tekshiring." : msg;
}

/** Order + share rows. With one row it is the plain «Buyurtma ID» field. */
export function DebtAllocationsEditor({
  rows,
  onChange,
  total,
  currency,
  error,
}: {
  rows: AllocationRow[];
  onChange: (rows: AllocationRow[]) => void;
  /** the debt's total in cents; null while the sum is empty or invalid */
  total: number | null;
  currency: "UZS" | "USD";
  error?: string;
}) {
  const listId = useId();
  const { data: orderOpts } = useGet<{ ref: string; client: string }[]>("/finance/order-options/", { bucket: "yangi,jarayonda,kutish,yakun" });
  const { left, isDuplicate } = checkAllocations(rows, total);
  const split = rows.length > 1;
  const allowCents = currency === "USD" || (total !== null && total % 100 !== 0);
  const patch = (key: number, p: Partial<AllocationRow>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...p } : r)));
  // back to one row = an ordinary debt: a leftover share must not come back later
  const remove = (key: number) => {
    const next = rows.filter((r) => r.key !== key);
    onChange(next.length === 1 ? [{ ...next[0], amount: "" }] : next);
  };
  const add = (
    <Button type="button" size="sm" variant="outline" icon={<Plus className="h-4 w-4" />} disabled={rows.length >= MAX_ALLOCATIONS} onClick={() => onChange([...(rows.length === 1 ? [{ ...rows[0], amount: "" }] : rows), newRow()])}>
      ID
    </Button>
  );
  const options = (
    <datalist id={listId}>
      {orderOpts?.map((o) => (
        <option key={o.ref} value={o.ref}>
          {o.client}
        </option>
      ))}
    </datalist>
  );

  if (!split) {
    return (
      <div>
        <Field label="Buyurtma ID" hint="Ro'yxatdan tanlang yoki ID yozing" error={error}>
          <Input list={listId} value={rows[0]?.ref ?? ""} onChange={(e) => patch(rows[0].key, { ref: e.target.value.trim() })} placeholder="406" />
        </Field>
        {options}
        <div className="mt-2">{add}</div>
      </div>
    );
  }

  return (
    <div>
      <span className="label">Buyurtmalar bo'yicha</span>
      <div className="space-y-3">
        {rows.map((r) => {
          const cents = toCents(r.amount);
          const badAmount = r.amount !== "" && (cents === null || cents <= 0);
          const fill = (cents ?? 0) + left;
          return (
            <div key={r.key}>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2">
                <Input aria-label="Buyurtma ID" list={listId} value={r.ref} onChange={(e) => patch(r.key, { ref: e.target.value.trim() })} placeholder="406" />
                <Input
                  aria-label={`Summa (${currency === "USD" ? "$" : "so'm"})`}
                  inputMode={allowCents ? "decimal" : "numeric"}
                  value={r.amount}
                  onChange={(e) => patch(r.key, { amount: e.target.value.replace(allowCents ? /[^\d.]/g : /[^\d]/g, "") })}
                  placeholder={currency === "USD" ? "20" : "500000"}
                />
                <IconButton type="button" label="O'chirish" onClick={() => remove(r.key)}>
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              </div>
              {isDuplicate(r) && <span className="mt-1 block text-xs text-rose-600">Bu ID allaqachon qo'shilgan</span>}
              {badAmount && <span className="mt-1 block text-xs text-rose-600">Summa noto'g'ri</span>}
              {left > 0 && (r.amount === "" || cents !== null) && (
                <button type="button" className="mt-1 text-xs font-medium text-brand-600 hover:underline" onClick={() => patch(r.key, { amount: fromCents(fill) })}>
                  Qolganini shu ID ga
                </button>
              )}
            </div>
          );
        })}
      </div>
      {options}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        {add}
        <span className={`text-sm font-semibold tabular-nums ${left === 0 && total ? "text-emerald-600" : "text-rose-600"}`}>
          {total === null ? "Avval summani kiriting" : left < 0 ? `Ortiqcha: ${centsLabel(-left, currency)}` : `Qoldi: ${centsLabel(left, currency)}`}
        </span>
      </div>
      {error && <span className="mt-1 block text-xs text-rose-600">{error}</span>}
    </div>
  );
}
