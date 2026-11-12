import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import type { PainterPart, PainterType } from "@/api/types";
import { Button, Input, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { money, num } from "@/lib/format";

interface Row {
  key: number;
  id: number | null;
  type: string;
  square: string;
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/**
 * «Jamoalar»: the production head splits a Molyar job between teams by m². Done parts are
 * frozen (read-only rows); the open ones are edited and saved together
 * (POST /painters/{id}/parts/). The sum may be below the job's m² (the rest is given later)
 * but never above it; the job closes only when the parts cover the whole square.
 */
export function PainterParts({
  painterId,
  total,
  parts,
  types,
  startOpen,
  invalidate,
}: {
  painterId: number;
  total: number;
  parts: PainterPart[];
  types: PainterType[];
  startOpen?: boolean;
  invalidate: string[];
}) {
  const done = parts.filter((p) => p.done);
  const open = parts.filter((p) => !p.done);
  const fromServer = useMemo<Row[]>(
    () => open.map((p, i) => ({ key: i, id: p.id, type: String(p.type), square: String(p.square) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(open.map((p) => [p.id, p.type, p.square]))],
  );
  const [rows, setRows] = useState<Row[]>(fromServer);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [seq, setSeq] = useState(1000);
  useEffect(() => setRows(fromServer), [fromServer]);

  const doneTypes = new Set(done.map((p) => p.type));
  const doneSum = done.reduce((s, p) => s + p.square, 0);
  const sum = round2(doneSum + rows.reduce((s, r) => s + (Number(r.square) || 0), 0));
  const left = round2(total - sum);
  const over = left < 0;
  const invalid = rows.some((r) => !r.type || !(Number(r.square) > 0));
  const dirty = JSON.stringify(rows.map((r) => [r.id, r.type, Number(r.square)])) !== JSON.stringify(fromServer.map((r) => [r.id, r.type, Number(r.square)]));
  // every part done and nothing left to give (or detailing shrank the square): the job only
  // needs a save to close
  const closable = rows.length === 0 && done.length > 0 && left <= 0;
  const usable = types.filter((t) => t.user);

  const save = useAction(
    () =>
      api.post(`/painters/${painterId}/parts/`, {
        parts: rows.map((r) => ({ id: r.id, type: Number(r.type), square: Number(r.square) })),
      }),
    { success: "Jamoalar saqlandi", invalidate },
  );
  const patch = (key: number, p: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  const takenElsewhere = (key: number) => new Set(rows.filter((r) => r.key !== key && r.type).map((r) => Number(r.type)));

  return (
    <div className={cn("rounded-xl border border-slate-200 p-3 dark:border-slate-700", startOpen && "ring-2 ring-brand-500/40")}>
      <div className="mb-2 text-sm font-semibold">Jamoalar</div>
      <div className="space-y-2">
        {done.map((p) => (
          <div key={p.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>✅ {p.type_detail.name}</span>
            <span className="tabular-nums">{num(p.square)} m²</span>
            {p.note && <span className="muted truncate">· {p.note}</span>}
          </div>
        ))}
        {rows.map((r) => {
          const taken = takenElsewhere(r.key);
          return (
            <div key={r.key} className="flex flex-wrap items-center gap-2">
              <Select className="min-w-[10rem] flex-1" value={r.type} onChange={(e) => patch(r.key, { type: e.target.value })}>
                <option value="">— jamoa —</option>
                {usable
                  .filter((t) => !doneTypes.has(t.id) && (!taken.has(t.id) || String(t.id) === r.type))
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} — {money(t.price)}/m²
                    </option>
                  ))}
              </Select>
              <Input
                className="w-28"
                type="number"
                step="0.01"
                min="0"
                placeholder="m²"
                value={r.square}
                onChange={(e) => patch(r.key, { square: e.target.value })}
              />
              <span className="muted text-sm">m²</span>
              <button type="button" aria-label="Olib tashlash" className="rounded p-1 text-slate-400 hover:text-rose-600" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setRows((rs) => [...rs, { key: seq, id: null, type: "", square: left > 0 ? String(left) : "" }]);
            setSeq(seq + 1);
          }}
        >
          Jamoa qo'shish
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={open.length === 0 && done.length > 0}
          onClick={() => {
            const remaining = round2(total - doneSum);
            setRows((rs) => [{ key: rs[0]?.key ?? seq, id: rs[0]?.id ?? null, type: rs[0]?.type ?? "", square: String(remaining) }]);
            setSeq(seq + 1);
          }}
        >
          Hammasi bitta jamoaga
        </Button>
      </div>
      <div className={cn("mt-3 text-sm tabular-nums", over || left > 0 ? "font-semibold text-rose-600 dark:text-rose-400" : "muted")}>
        Umumiy: {num(total)} m² · Taqsimlandi: {num(sum)} m² · Qoldi: {num(left)} m²
        {over && " — umumiy maydondan katta!"}
        {!over && left > 0 && " — ish qolgan maydon berilmaguncha yopilmaydi"}
      </div>
      {errors.parts && <div className="mt-1 text-sm text-rose-600">{errors.parts}</div>}
      <div className="mt-3 flex justify-end">
        <Button
          loading={save.isPending}
          disabled={invalid || (!dirty && !closable)}
          onClick={() => save.mutateAsync().then(() => setErrors({})).catch((e) => setErrors(fieldErrors(e)))}
        >
          {closable && !dirty ? "Yopish / qayta hisoblash" : "Saqlash"}
        </Button>
      </div>
    </div>
  );
}
