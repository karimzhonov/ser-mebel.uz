import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookX, ListChecks, Pencil, Plus, Trash2, Wallet } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { iso } from "@/components/DateRangeFilter";
import { Badge, Button, Card, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, Pagination, SearchInput, Segmented, Select, StatTile, Textarea } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import {
  allocationsPayload,
  centsLabel,
  checkAllocations,
  cleanAllocationError,
  debtAllocations,
  DebtAllocationsEditor,
  fromCents,
  isSplitDebt,
  newRow,
  toCents,
  type AllocationRow,
} from "./DebtAllocationsEditor";
import { CatLabel, inCur, som, useFinMe, useFinOptions, usd } from "./shared";
import type { Debt, DebtStats } from "./types";

function DaysBadge({ d }: { d: Debt }) {
  if (d.status === "closed") {
    const closed = d.closed_at ? ` · yopildi ${date(d.closed_at).slice(0, 5)}` : "";
    return <Badge tone="idle">{`${d.days} kun${closed}`}</Badge>;
  }
  return <Badge tone={d.days <= 7 ? "ok" : d.days <= 30 ? "warn" : "danger"}>{d.days} kun</Badge>;
}

/** A split debt's orders with their shares; ✓ = that order's share is paid. */
function DebtShares({ d }: { d: Debt }) {
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5">
      {debtAllocations(d).map((a) => (
        <span key={a.id} title={a.client} className="whitespace-nowrap">
          <span className="font-medium">🧾 {a.order_ref}</span>: {inCur(a.amount, d.currency)}
          {(toCents(a.remaining) ?? 0) === 0 && <span className="text-emerald-600"> ✓</span>}
        </span>
      ))}
    </span>
  );
}

export function FinanceDebtsPage() {
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ status: "open", search: "" });
  const { data, isFetching } = useList<Debt>("finance/debts", { ...state, page });
  const { data: stats } = useGet<DebtStats>("/finance/debts/stats/");
  const [creating, setCreating] = useState(false);
  const [paying, setPaying] = useState<Debt | null>(null);
  const [payments, setPayments] = useState<Debt | null>(null);
  const remove = useAction((id: number) => api.delete(`/finance/debts/${id}/`), { success: "O'chirildi", invalidate: ["finance"] });
  const canAdd = can("accounting.add_debt");
  const qc = useQueryClient();

  /** The row and the modal both delete here. The modal closes first, so its detail query
   * is not refetched for a debt that no longer exists. */
  const askDelete = (d: Debt) => {
    if (remove.isPending || !confirm(`Qarz #${d.number} (${d.creditor} — ${d.item}) o'chirilsinmi?`)) return;
    setPayments(null);
    const lastOnPage = data?.results.length === 1 && page > 1;
    remove.mutate(d.id, {
      // an emptied last page would 404 and keep showing the deleted row
      onSuccess: () => lastOnPage && set({ page: page - 1 }),
      // the row was stale (paid or deleted elsewhere): the toast explains, the list refreshes
      onError: () => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes("finance") }),
    });
  };

  return (
    <div>
      <PageHeader
        title="Qarzlar"
        subtitle="Kreditga olingan narsalar — to'languncha shu yerda turadi; to'lov mijoz buyurtmasining chiqimiga yoziladi. Xodim faqat o'zi yozgan qarzlarni ko'radi"
        actions={
          canAdd && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Qarz
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented
          value={state.status}
          onChange={(status) => set({ status })}
          options={[
            { value: "open", label: "📕 Ochiq" },
            { value: "closed", label: "📗 Yopilgan" },
            { value: "all", label: "Hammasi" },
          ]}
        />
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <StatTile label="Ochiq qarzlar soni" value={stats?.open_count ?? 0} tone="warn" />
        <StatTile label="Jami qoldiq (so'm)" value={som(stats?.open_uzs ?? 0)} tone="danger" />
        {Number(stats?.open_usd ?? 0) > 0 && <StatTile label="Jami qoldiq ($)" value={usd(stats?.open_usd)} tone="danger" />}
      </div>
      <Card padded={false}>
        <div className="border-b border-slate-100 p-4 dark:border-slate-800">
          <SearchInput value={state.search} onChange={(v) => set({ search: v })} placeholder="Kimdan, nima, buyurtma ID, izoh…" />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          empty={<Empty title="Qarz yo'q" text="Bu bo'limda qarzlar yo'q." />}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="muted tabular-nums">#{r.number}</span> },
            { key: "d", header: "Olingan sana", cell: (r) => <span className="whitespace-nowrap">{date(r.date)}</span> },
            { key: "c", header: "Kimdan", cell: (r) => r.creditor },
            {
              key: "i",
              header: "Nima olindi",
              cell: (r) => (
                <div className="max-w-xs text-sm">
                  <div className="line-clamp-2">{r.item}</div>
                  <div className="muted text-xs">
                    <CatLabel c={{ ...r.category, color: "#94a3b8" }} />
                  </div>
                  {/* the «Buyurtma» column is hidden on phones */}
                  {isSplitDebt(r) && (
                    <div className="mt-1 text-xs md:hidden">
                      <DebtShares d={r} />
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: "o",
              header: "Buyurtma",
              cell: (r) =>
                isSplitDebt(r) ? (
                  <div className="max-w-xs text-sm">
                    <DebtShares d={r} />
                  </div>
                ) : (
                  <span className="text-sm">
                    <span className="font-medium">🧾 {r.order_ref}</span> {r.client && <span className="muted">· {r.client}</span>}
                  </span>
                ),
              hideOnMobile: true,
            },
            { key: "t", header: "Summa", cell: (r) => <span className="whitespace-nowrap tabular-nums">{inCur(r.total, r.currency)}</span> },
            { key: "p", header: "To'langan", cell: (r) => <span className="whitespace-nowrap tabular-nums">{inCur(r.paid, r.currency)}</span>, hideOnMobile: true },
            {
              key: "r",
              header: "Qoldiq",
              cell: (r) => (
                <span className={`whitespace-nowrap font-semibold tabular-nums ${r.status === "open" ? "text-rose-600" : "muted"}`}>{inCur(r.remaining, r.currency)}</span>
              ),
            },
            { key: "k", header: "Kun", cell: (r) => <DaysBadge d={r} /> },
            {
              key: "x",
              header: "",
              cell: (r) => (
                <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  {r.status === "open" && canAdd && (
                    <Button size="sm" icon={<Wallet className="h-4 w-4" />} onClick={() => setPaying(r)}>
                      To'lash
                    </Button>
                  )}
                  <IconButton label="To'lovlar" onClick={() => setPayments(r)}>
                    <ListChecks className="h-4 w-4" />
                  </IconButton>
                  {r.can_delete && (
                    <IconButton label="O'chirish" disabled={remove.isPending} className="disabled:opacity-50" onClick={() => askDelete(r)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              ),
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {creating && <DebtModal onClose={() => setCreating(false)} />}
      {paying && <DebtPayModal debt={paying} onClose={() => setPaying(null)} />}
      {payments && <DebtPaymentsModal debt={payments} onClose={() => setPayments(null)} onDelete={askDelete} deleting={remove.isPending} />}
    </div>
  );
}

/** Payments of one debt (detail endpoint) + delete when allowed. */
function DebtPaymentsModal({ debt, onClose, onDelete, deleting }: { debt: Debt; onClose: () => void; onDelete: (d: Debt) => void; deleting: boolean }) {
  const { data } = useGet<Debt>(`/finance/debts/${debt.id}/`);
  const [editing, setEditing] = useState(false);
  if (editing && data) return <DebtAllocationsModal debt={data} onClose={() => setEditing(false)} />;
  const split = !!data && isSplitDebt(data);
  // an older backend sends no `allocations` and would ignore the edit
  const canEdit = !!data?.can_change && debtAllocations(data).length > 0;
  const hasPayments = !!data?.payments?.length || (toCents(data?.paid) ?? 0) > 0;
  return (
    <Modal open onClose={onClose} title={`📕 Qarz #${debt.number} — to'lovlar`}>
      <p className="mb-3 text-sm">
        {debt.creditor} — {debt.item}
      </p>
      {!data?.payments?.length ? (
        <Empty title="To'lov yo'q" text="Bu qarz bo'yicha hali to'lov qilinmagan." />
      ) : (
        <ul className="space-y-2">
          {data.payments.map((p) => (
            <li key={p.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800">
              <span>
                <span className="muted">#{p.number}</span> · {date(p.date)} · {p.member_detail.name}
                {split && p.order_ref && <span className="font-medium"> · 🧾 {p.order_ref}</span>}
              </span>
              <span className="font-semibold tabular-nums">{p.currency === "USD" ? usd(p.orig_amount) : som(p.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {canEdit && hasPayments && <p className="muted mt-3 text-xs">To'lov bor — buyurtmalarni o'zgartirish uchun avval to'lovlarni o'chiring.</p>}
      {(canEdit || data?.can_delete) && (
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          {canEdit && (
            <Button variant="outline" icon={<Pencil className="h-4 w-4" />} disabled={hasPayments} onClick={() => setEditing(true)}>
              Buyurtmalarni o'zgartirish
            </Button>
          )}
          {data?.can_delete && (
            <Button variant="outline" icon={<Trash2 className="h-4 w-4" />} disabled={deleting} onClick={() => onDelete(debt)}>
              Qarzni o'chirish
            </Button>
          )}
        </div>
      )}
    </Modal>
  );
}

/** Change which orders share an unpaid debt. The total stays as it is. */
function DebtAllocationsModal({ debt, onClose }: { debt: Debt; onClose: () => void }) {
  const [rows, setRows] = useState<AllocationRow[]>(() => debtAllocations(debt).map((a) => newRow(a.order_ref, fromCents(toCents(a.amount) ?? 0))));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const total = toCents(debt.total);
  const save = useAction(() => api.patch(`/finance/debts/${debt.id}/`, { allocations: allocationsPayload(rows, total ?? 0) }), {
    success: "Saqlandi",
    invalidate: ["finance"],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`📕 Qarz #${debt.number} — buyurtmalar`}
      footer={
        <Button loading={save.isPending} disabled={!total || !checkAllocations(rows, total).ok} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Saqlash
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          {debt.creditor} — {debt.item}
          <br />
          <span className="font-semibold">Summa: {inCur(debt.total, debt.currency)}</span>
        </p>
        <DebtAllocationsEditor rows={rows} onChange={setRows} total={total} currency={debt.currency} error={cleanAllocationError(errors.allocations || errors.order_ref || errors.detail)} />
      </div>
    </Modal>
  );
}

const NO_DEBT_CATS = ["oylik", "zapravka"];

/** «Yangi qarz»: nothing is booked until a payment is made. */
export function DebtModal({ onClose }: { onClose: () => void }) {
  const { data: me } = useFinMe();
  const { data: fin } = useFinOptions();
  const cats = fin?.categories;
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [f, setF] = useState({ date: iso(new Date()), creditor: "", item: "", category_code: "", currency: "UZS" as "UZS" | "USD", amount: "", orig_amount: "", comment: "" });
  const [rows, setRows] = useState<AllocationRow[]>(() => [newRow()]);
  const options = (cats ?? []).filter(
    (c) => c.kind === "expense" && c.is_active && !c.no_order && !c.excluded && !NO_DEBT_CATS.includes(c.code) && (!c.admin_only || me?.view_all),
  );
  const category = f.category_code || (options.find((c) => c.code === "material") ?? options[0])?.code || "";
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const sum = f.currency === "USD" ? f.orig_amount : f.amount;
  const total = toCents(sum);
  const save = useAction(
    () => {
      const body: Record<string, unknown> = {
        date: f.date,
        creditor: f.creditor,
        item: f.item,
        category_code: category,
        currency: f.currency,
        comment: f.comment,
      };
      if (rows.length === 1) body.order_ref = rows[0].ref;
      else body.allocations = allocationsPayload(rows, total ?? 0);
      if (f.currency === "USD") body.orig_amount = f.orig_amount;
      else body.amount = f.amount;
      return api.post("/finance/debts/", body);
    },
    { success: "Qarz yozildi", invalidate: ["finance"], onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title="📕 Yangi qarz"
      footer={
        <Button loading={save.isPending} disabled={!f.creditor.trim() || !f.item.trim() || !checkAllocations(rows, total).ok || !Number(sum)} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Saqlash
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Olingan sana" error={errors.date}>
            <Input type="date" value={f.date} onChange={(e) => set({ date: e.target.value })} />
          </Field>
          <Field label="Kimdan" error={errors.creditor}>
            <Input value={f.creditor} onChange={(e) => set({ creditor: e.target.value })} placeholder="Do'kon / ta'minotchi" />
          </Field>
        </div>
        <Field label="Nima olindi" error={errors.item}>
          <Textarea value={f.item} onChange={(e) => set({ item: e.target.value })} placeholder="LDSP 10 list" />
        </Field>
        <Field label="Kategoriya" error={errors.category_code}>
          <Select value={category} onChange={(e) => set({ category_code: e.target.value })}>
            {options.map((c) => (
              <option key={c.code} value={c.code}>
                {c.emoji} {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
          <Field label="Valyuta">
            <Segmented value={f.currency} onChange={(currency) => {
                // shares typed in the other currency mean nothing in this one
                if (currency !== f.currency) setRows((rs) => rs.map((r) => ({ ...r, amount: "" })));
                set({ currency });
              }} options={[{ value: "UZS", label: "so'm" }, { value: "USD", label: "$" }]} />
          </Field>
          {f.currency === "UZS" ? (
            <Field label="Summa (so'm)" error={errors.amount}>
              <Input inputMode="numeric" value={f.amount} onChange={(e) => set({ amount: e.target.value.replace(/[^\d]/g, "") })} placeholder="5000000" />
            </Field>
          ) : (
            <Field label="Summa ($)" error={errors.orig_amount}>
              <Input inputMode="decimal" value={f.orig_amount} onChange={(e) => set({ orig_amount: e.target.value.replace(/[^\d.]/g, "") })} />
            </Field>
          )}
        </div>
        <DebtAllocationsEditor rows={rows} onChange={setRows} total={total} currency={f.currency} error={cleanAllocationError(errors.allocations || errors.order_ref)} />
        <Field label="Izoh" error={errors.comment || errors.detail}>
          <Textarea value={f.comment} onChange={(e) => set({ comment: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

/** «To'lash»: an expense in the payer's OWN wallet, on the debt's order. On a split debt
 * the payer picks the order each time, or «Hammasi» for the whole remainder. */
export function DebtPayModal({ debt, onClose }: { debt: Debt; onClose: () => void }) {
  const { data: me } = useFinMe();
  const qc = useQueryClient();
  // the list row may be stale: another payment changes what each order still owes
  const { data: fresh } = useGet<Debt>(isSplitDebt(debt) ? `/finance/debts/${debt.id}/` : null);
  const current = fresh ?? debt;
  const split = isSplitDebt(current);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [amount, setAmount] = useState(String(Number(debt.remaining)));
  const [target, setTarget] = useState("");
  const [day, setDay] = useState(iso(new Date()));
  const wallet = me?.member?.has_wallet ? String(me.member.id) : "";
  const unpaid = split ? debtAllocations(current).filter((a) => (toCents(a.remaining) ?? 0) > 0) : [];
  const chosen = unpaid.find((a) => String(a.id) === target);
  const payAll = split && target === "all" && unpaid.length > 0;
  const limit = chosen ? toCents(chosen.remaining) ?? 0 : 0;
  const cents = toCents(amount);
  const overLimit = !!chosen && cents !== null && cents > limit;
  const allowCents = current.currency === "USD" || (!!chosen && limit % 100 !== 0);
  const ready = split ? payAll || (!!chosen && cents !== null && cents > 0 && !overLimit) : !!Number(amount);
  const save = useAction(
    () => {
      const body: Record<string, unknown> = { member: Number(wallet), date: day };
      if (!split) body.amount = amount;
      else if (chosen) {
        body.allocation = chosen.id;
        body.amount = fromCents(cents ?? 0);
      }
      return api.post(`/finance/debts/${debt.id}/pay/`, body);
    },
    { success: "To'landi", invalidate: ["finance"], onSuccess: onClose },
  );
  const pickTarget = (value: string) => {
    setTarget(value);
    setErrors({});
    const a = unpaid.find((x) => String(x.id) === value);
    if (a) setAmount(fromCents(toCents(a.remaining) ?? 0));
  };
  const submit = () =>
    save.mutateAsync().catch((e) => {
      setErrors(fieldErrors(e));
      // a stale choice: reload the remainders so the picker shows the truth
      if (split) qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes("finance") });
    });
  return (
    <Modal
      open
      onClose={onClose}
      title={`💸 Qarz #${debt.number} — to'lash`}
      size="sm"
      footer={
        <Button loading={save.isPending} disabled={!wallet || !ready} onClick={submit}>
          To'lash
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          <BookX className="mr-1 inline h-4 w-4" />
          {debt.creditor} — {debt.item}
          <br />
          <span className="font-semibold text-rose-600">Qoldiq: {inCur(current.remaining, current.currency)}</span>
        </p>
        <Field label="Hamyon" error={errors.member}>
          {wallet ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium dark:border-slate-700 dark:bg-slate-800">{me?.member?.name}</div>
          ) : (
            me && (
              <p className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                {me.member ? "Sizning hamyoningiz yo'q." : "Profilingiz Telegram a'zoga ulanmagan. Qarzni faqat o'z hamyoningizdan to'lash mumkin."}
              </p>
            )
          )}
        </Field>
        {split && (
          <Field label="Buyurtma" error={errors.allocation || (payAll ? errors.amount : undefined)}>
            <Select value={chosen ? target : payAll ? "all" : ""} onChange={(e) => pickTarget(e.target.value)}>
              <option value="">— tanlang —</option>
              {unpaid.map((a) => (
                <option key={a.id} value={a.id}>
                  🧾 {a.order_ref}
                  {a.client ? ` ${a.client}` : ""} — qoldiq {centsLabel(toCents(a.remaining) ?? 0, current.currency)}
                </option>
              ))}
              {unpaid.length > 0 && <option value="all">✅ Hammasi: {centsLabel(toCents(current.remaining) ?? 0, current.currency)}</option>}
            </Select>
          </Field>
        )}
        {(!split || chosen) && (
          <Field
            label={`Summa (${debt.currency === "USD" ? "$" : "so'm"})`}
            error={errors.amount || (overLimit ? `Bu buyurtma qoldig'i: ${centsLabel(limit, current.currency)}` : undefined)}
          >
            <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(allowCents ? /[^\d.]/g : /[^\d]/g, ""))} />
          </Field>
        )}
        {payAll && <p className="text-sm">Har bir to'lanmagan buyurtmaning qoldig'i to'liq yopiladi.</p>}
        <Field label="Sana" error={errors.date || errors.detail}>
          <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
