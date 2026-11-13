import { useState } from "react";
import { BookX, ListChecks, Plus, Trash2, Wallet } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { iso } from "@/components/DateRangeFilter";
import { Badge, Button, Card, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, Pagination, SearchInput, Segmented, Select, StatTile, Textarea } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { CatLabel, inCur, som, useCategories, useFinMe, useMembers, usd } from "./shared";
import type { Debt, DebtStats } from "./types";

function DaysBadge({ d }: { d: Debt }) {
  if (d.status === "closed") {
    const closed = d.closed_at ? ` · yopildi ${date(d.closed_at).slice(0, 5)}` : "";
    return <Badge tone="idle">{`${d.days} kun${closed}`}</Badge>;
  }
  return <Badge tone={d.days <= 7 ? "ok" : d.days <= 30 ? "warn" : "danger"}>{d.days} kun</Badge>;
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
  const canAdd = can("accounting.add_operation");

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
                </div>
              ),
            },
            {
              key: "o",
              header: "Buyurtma",
              cell: (r) => (
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
                </div>
              ),
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {creating && <DebtModal onClose={() => setCreating(false)} />}
      {paying && <DebtPayModal debt={paying} onClose={() => setPaying(null)} />}
      {payments && <DebtPaymentsModal debt={payments} onClose={() => setPayments(null)} onDelete={(id) => remove.mutateAsync(id).then(() => setPayments(null))} />}
    </div>
  );
}

/** Payments of one debt (detail endpoint) + delete when allowed. */
function DebtPaymentsModal({ debt, onClose, onDelete }: { debt: Debt; onClose: () => void; onDelete: (id: number) => void }) {
  const { data } = useGet<Debt>(`/finance/debts/${debt.id}/`);
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
              </span>
              <span className="font-semibold tabular-nums">{p.currency === "USD" ? usd(p.orig_amount) : som(p.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {data?.can_delete && (
        <div className="mt-4 flex justify-end">
          <Button variant="outline" icon={<Trash2 className="h-4 w-4" />} onClick={() => confirm(`Qarz #${debt.number} o'chirilsinmi?`) && onDelete(debt.id)}>
            Qarzni o'chirish
          </Button>
        </div>
      )}
    </Modal>
  );
}

const NO_DEBT_CATS = ["oylik", "zapravka"];

/** «Yangi qarz»: nothing is booked until a payment is made. */
export function DebtModal({ onClose }: { onClose: () => void }) {
  const { data: me } = useFinMe();
  const { data: cats } = useCategories();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [f, setF] = useState({ date: iso(new Date()), creditor: "", item: "", category_code: "", currency: "UZS" as "UZS" | "USD", amount: "", orig_amount: "", order_ref: "", comment: "" });
  const options = (cats ?? []).filter(
    (c) => c.kind === "expense" && c.is_active && !c.no_order && !c.excluded && !NO_DEBT_CATS.includes(c.code) && (!c.admin_only || me?.view_all),
  );
  const category = f.category_code || (options.find((c) => c.code === "material") ?? options[0])?.code || "";
  const { data: orderOpts } = useGet<{ ref: string; client: string }[]>("/finance/order-options/", { bucket: "yangi,jarayonda,kutish,yakun" });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const save = useAction(
    () => {
      const body: Record<string, unknown> = {
        date: f.date,
        creditor: f.creditor,
        item: f.item,
        category_code: category,
        currency: f.currency,
        order_ref: f.order_ref,
        comment: f.comment,
      };
      if (f.currency === "USD") body.orig_amount = f.orig_amount;
      else body.amount = f.amount;
      return api.post("/finance/debts/", body);
    },
    { success: "Qarz yozildi", invalidate: ["finance"], onSuccess: onClose },
  );
  const sum = f.currency === "USD" ? f.orig_amount : f.amount;
  return (
    <Modal
      open
      onClose={onClose}
      title="📕 Yangi qarz"
      footer={
        <Button loading={save.isPending} disabled={!f.creditor.trim() || !f.item.trim() || !f.order_ref || !Number(sum)} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
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
            <Segmented value={f.currency} onChange={(currency) => set({ currency })} options={[{ value: "UZS", label: "so'm" }, { value: "USD", label: "$" }]} />
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
        <Field label="Buyurtma ID" hint="Ro'yxatdan tanlang yoki ID yozing" error={errors.order_ref}>
          <Input list="debt-orders" value={f.order_ref} onChange={(e) => set({ order_ref: e.target.value.trim() })} placeholder="406" />
          <datalist id="debt-orders">
            {orderOpts?.map((o) => (
              <option key={o.ref} value={o.ref}>
                {o.client}
              </option>
            ))}
          </datalist>
        </Field>
        <Field label="Izoh" error={errors.comment || errors.detail}>
          <Textarea value={f.comment} onChange={(e) => set({ comment: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

/** «To'lash»: an expense in the chosen wallet, on the debt's order. */
export function DebtPayModal({ debt, onClose }: { debt: Debt; onClose: () => void }) {
  const { data: me } = useFinMe();
  const { data: members } = useMembers({}, !!me?.view_all);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [member, setMember] = useState("");
  const [amount, setAmount] = useState(String(Number(debt.remaining)));
  const [day, setDay] = useState(iso(new Date()));
  const wallet = member || (me?.member ? String(me.member.id) : "");
  const wallets = me?.view_all ? (members ?? []).filter((m) => m.has_wallet) : me?.member ? [me.member] : [];
  const save = useAction(
    () => api.post(`/finance/debts/${debt.id}/pay/`, { member: Number(wallet), amount, date: day }),
    { success: "To'landi", invalidate: ["finance"], onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={`💸 Qarz #${debt.number} — to'lash`}
      size="sm"
      footer={
        <Button loading={save.isPending} disabled={!wallet || !Number(amount)} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          To'lash
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          <BookX className="mr-1 inline h-4 w-4" />
          {debt.creditor} — {debt.item}
          <br />
          <span className="font-semibold text-rose-600">Qoldiq: {inCur(debt.remaining, debt.currency)}</span>
        </p>
        <Field label="Hamyon" error={errors.member}>
          <Select value={wallet} onChange={(e) => setMember(e.target.value)} disabled={!me?.view_all}>
            <option value="">— tanlang —</option>
            {wallets.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={`Summa (${debt.currency === "USD" ? "$" : "so'm"})`} error={errors.amount}>
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(debt.currency === "USD" ? /[^\d.]/g : /[^\d]/g, ""))} />
        </Field>
        <Field label="Sana" error={errors.date || errors.detail}>
          <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
