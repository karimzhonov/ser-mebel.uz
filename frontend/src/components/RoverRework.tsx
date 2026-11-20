import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import type { Paginated, RoverRework, RoverReworkOrder } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import { Button, Confirm, DataTable, Field, Input, Modal, Pagination, SearchInput, StatTile, Textarea } from "@/components/ui";
import { date, num, phone } from "@/lib/format";

/** "150 000 so'm + $20" — both parts of an amount entered in so'm and $. */
export function twoCurrencies(uzs: number | string | null | undefined, usd: number | string | null | undefined) {
  const parts: string[] = [];
  if (Number(uzs) > 0) parts.push(`${num(Number(uzs))} so'm`);
  if (Number(usd) > 0) parts.push(`$${num(Number(usd))}`);
  return parts.length ? parts.join(" + ") : "—";
}

export type Amount = { amount: number | string; currency: "UZS" | "USD" };

/** One amount with a so'm / $ switch (the rover enters either, not both). */
export function AmountInput({ value, onChange }: { value: Amount; onChange: (v: Amount) => void }) {
  return (
    <div className="flex">
      <input
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        className="input rounded-r-none"
        value={value.amount}
        onChange={(e) => onChange({ ...value, amount: e.target.value })}
      />
      <select
        className="input w-24 rounded-l-none border-l-0"
        value={value.currency}
        onChange={(e) => onChange({ ...value, currency: e.target.value as Amount["currency"] })}
      >
        <option value="UZS">so'm</option>
        <option value="USD">$</option>
      </select>
    </div>
  );
}

type ReworkList =Paginated<RoverRework> & { totals?: { square: number; price_uzs: number; price_usd: number } };

/** «Mijoz peredelkasi»: the rover worker's client rework log (order/client, m², so'm and $). */
export function RoverReworkModal({ onClose }: { onClose: () => void }) {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [range, setRange] = useState({ date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<RoverRework | null>(null);
  const { data, isFetching } = useList<RoverRework>("rover-reworks", { search, ...range, page });
  const list = data as ReworkList | undefined;
  const remove = useAction((id: number) => api.delete(`/rover-reworks/${id}/`), {
    success: "O'chirildi",
    invalidate: ["rover-reworks"],
    onSuccess: () => setRemoving(null),
  });

  return (
    <Modal open onClose={onClose} title="Mijoz peredelkasi" size="xl">
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="Jami maydon, m²" value={num(list?.totals?.square ?? 0)} tone="primary" />
          <StatTile label="So'm" value={num(Number(list?.totals?.price_uzs ?? 0))} tone="ok" />
          <StatTile label="$" value={num(Number(list?.totals?.price_usd ?? 0))} tone="ok" />
        </div>
        <div className="flex flex-col gap-3 lg:flex-row">
          <SearchInput
            className="flex-1"
            value={search}
            onChange={(v) => {
              setSearch(v);
              setPage(1);
            }}
            placeholder="Buyurtma №, mijoz, izoh"
          />
          <DateRangeFilter
            from={range.date_from}
            to={range.date_to}
            onChange={(date_from, date_to) => {
              setRange({ date_from, date_to });
              setPage(1);
            }}
          />
          {can("rover.change_rover") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>
              Peredelka qo'shish
            </Button>
          )}
        </div>
        <DataTable
          rows={list?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "date", header: "Sana", cell: (r) => date(r.created_at) },
            {
              key: "order",
              header: "Mijoz",
              cell: (r) => (
                <span>
                  <span className="font-semibold">№{r.order_detail.order_number}</span> · {r.order_detail.client_fio || "—"}
                </span>
              ),
            },
            { key: "square", header: "Maydon, m²", cell: (r) => <span className="tabular-nums">{num(r.square)}</span> },
            { key: "sum", header: "Summa", cell: (r) => <span className="tabular-nums">{twoCurrencies(r.price_uzs, r.price_usd)}</span> },
            { key: "note", header: "Izoh", cell: (r) => <span className="whitespace-pre-wrap">{r.note || <span className="muted">—</span>}</span> },
            {
              key: "by",
              header: "Kiritdi",
              cell: (r) => r.created_by_detail?.name || (r.created_by_detail ? phone(r.created_by_detail.phone) : "—"),
            },
            {
              key: "x",
              header: "",
              cell: (r) =>
                r.can_delete ? (
                  <button type="button" className="text-rose-600 hover:text-rose-700" title="O'chirish" onClick={() => setRemoving(r)}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                ) : null,
            },
          ]}
          mobileCard={(r) => (
            <div className="space-y-1 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-semibold">
                  №{r.order_detail.order_number} · {r.order_detail.client_fio}
                </span>
                <span className="muted">{date(r.created_at)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="tabular-nums">{num(r.square)} m²</span>
                <span className="tabular-nums font-semibold">{twoCurrencies(r.price_uzs, r.price_usd)}</span>
              </div>
              {r.note && <div className="muted whitespace-pre-wrap">{r.note}</div>}
              {r.can_delete && (
                <button type="button" className="text-xs text-rose-600" onClick={() => setRemoving(r)}>
                  O'chirish
                </button>
              )}
            </div>
          )}
          empty={<div className="muted p-6 text-center text-sm">Hali peredelka kiritilmagan</div>}
        />
        <Pagination page={page} count={list?.count ?? 0} onPage={setPage} />
      </div>
      {adding && <ReworkForm onClose={() => setAdding(false)} />}
      <Confirm
        open={!!removing}
        onClose={() => setRemoving(null)}
        title="Peredelkani o'chirish"
        text={removing ? `№${removing.order_detail.order_number} · ${removing.order_detail.client_fio} — ${num(removing.square)} m²` : ""}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </Modal>
  );
}

function ReworkForm({ onClose }: { onClose: () => void }) {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [picked, setPicked] = useState<RoverReworkOrder | null>(null);
  const [form, setForm] = useState({ square: "", note: "" });
  const [amount, setAmount] = useState<Amount>({ amount: "", currency: "UZS" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    const t = setTimeout(() => setDebounced(term.trim()), 300);
    return () => clearTimeout(t);
  }, [term]);
  const { data: options, isFetching } = useGet<RoverReworkOrder[]>(picked ? null : "/rover-reworks/orders/", { search: debounced });
  const save = useAction(
    () =>
      api.post("/rover-reworks/", {
        order: picked?.id,
        square: Number(form.square),
        price_uzs: amount.currency === "UZS" ? Number(amount.amount || 0) : 0,
        price_usd: amount.currency === "USD" ? Number(amount.amount || 0) : 0,
        note: form.note.trim(),
      }),
    { success: "Peredelka saqlandi", invalidate: ["rover-reworks"], onSuccess: onClose },
  );
  const ready = !!picked && Number(form.square) > 0 && Number(amount.amount) > 0;

  return (
    <Modal open onClose={onClose} title="Mijoz peredelkasi qo'shish" size="md">
      <div className="space-y-4">
        {/* not a <Field>: that is a <label>, and a label swallows clicks on the result buttons */}
        <div>
          <span className="label">Mijoz (buyurtma № yoki ism)</span>
          {picked ? (
            <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
              <span>
                <span className="font-semibold">№{picked.order_number}</span> · {picked.client_fio || "—"}
              </span>
              <button type="button" className="text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => setPicked(null)}>
                o'zgartirish
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <Input autoFocus value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Masalan: 1250 yoki Aliyev" />
              <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-700">
                {(options ?? []).map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    className="flex w-full items-center gap-2 border-b border-slate-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800"
                    onClick={() => setPicked(o)}
                  >
                    <span className="font-semibold tabular-nums">№{o.order_number}</span>
                    <span>{o.client_fio || "—"}</span>
                  </button>
                ))}
                {!isFetching && !(options ?? []).length && <div className="muted px-3 py-2 text-sm">Topilmadi</div>}
                {isFetching && <div className="muted px-3 py-2 text-sm">Qidirilmoqda…</div>}
              </div>
            </div>
          )}
          {errors.order && <span className="mt-1 block text-xs text-rose-600">{errors.order}</span>}
        </div>
        <Field label="Maydon (m²)" error={errors.square}>
          <Input type="number" min="0" step="0.01" value={form.square} onChange={(e) => setForm({ ...form, square: e.target.value })} />
        </Field>
        <Field label="Summa (so'm yoki $)" error={errors.price_uzs || errors.price_usd}>
          <AmountInput value={amount} onChange={setAmount} />
        </Field>
        <Field label="Izoh (nima qilindi)" error={errors.note}>
          <Textarea value={form.note} maxLength={2000} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          <Button
            variant="success"
            loading={save.isPending}
            disabled={!ready}
            onClick={() => {
              setErrors({});
              save.mutateAsync().catch((e) => setErrors(fieldErrors(e)));
            }}
          >
            Saqlash
          </Button>
        </div>
      </div>
    </Modal>
  );
}
