import { useState } from "react";
import { Check as CheckIcon, X } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Card, DataTable, Empty, Field, Input, Modal, PageHeader, Pagination, Segmented, Select, Textarea } from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { inCur, som, useFinMe, useMembers, usd } from "./shared";
import type { Bonus, Feedback, Issue, MoneyRequest, MonthReport, Operation, SiteEntry, Warranty } from "./types";

/* ------------------------------------------------------------------ requests */
export function FinanceRequestsPage() {
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ status: "pending" });
  const { data, isFetching } = useList<MoneyRequest>("finance/requests", { ...state, page });
  const [give, setGive] = useState<MoneyRequest | null>(null);
  const reject = useAction((id: number) => api.post(`/finance/requests/${id}/reject/`), { success: "Rad etildi", invalidate: ["finance"] });
  const canAnswer = can("accounting.change_moneyrequest", "accounting.view_all_operations");
  return (
    <div>
      <PageHeader title="Pul so'rovlari" subtitle="Xodimlar botdagi «🙏 Rahbardan pul so'rash» orqali yuborgan so'rovlar" />
      <div className="mb-4">
        <Segmented
          value={state.status}
          onChange={(status) => set({ status })}
          options={[
            { value: "pending", label: "⏳ Kutmoqda" },
            { value: "given", label: "✅ Berildi" },
            { value: "rejected", label: "❌ Rad etildi" },
            { value: "", label: "Hammasi" },
          ]}
        />
      </div>
      <Card padded={false}>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "n", header: "№", cell: (r) => `#${r.number}` },
            { key: "m", header: "Xodim", cell: (r) => r.member_detail.name },
            { key: "a", header: "Summa", cell: (r) => <span className="font-semibold tabular-nums">{r.currency === "USD" ? `${usd(r.orig_amount)} (≈ ${som(r.amount)})` : som(r.amount)}</span> },
            { key: "r", header: "Sabab", cell: (r) => r.reason || "—" },
            { key: "d", header: "Sana", cell: (r) => dateTime(r.created_at), hideOnMobile: true },
            {
              key: "s",
              header: "Holat",
              cell: (r) => (
                <Badge tone={r.status === "given" ? "ok" : r.status === "rejected" ? "danger" : "warn"}>
                  {r.status === "pending" ? r.status_label : r.answer || r.status_label}
                  {r.answered_by_detail && ` · ${r.answered_by_detail.name}`}
                </Badge>
              ),
            },
            {
              key: "x",
              header: "",
              cell: (r) =>
                r.status === "pending" && canAnswer ? (
                  <div className="flex justify-end gap-2">
                    <Button size="sm" icon={<CheckIcon className="h-4 w-4" />} onClick={() => setGive(r)}>
                      Berdim
                    </Button>
                    <Button size="sm" variant="outline" icon={<X className="h-4 w-4" />} onClick={() => confirm(`#${r.number} rad etilsinmi?`) && reject.mutate(r.id)}>
                      Rad
                    </Button>
                  </div>
                ) : null,
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {give && <GiveModal req={give} onClose={() => setGive(null)} />}
    </div>
  );
}

function GiveModal({ req, onClose }: { req: MoneyRequest; onClose: () => void }) {
  const [amount, setAmount] = useState("");
  const save = useAction(() => api.post(`/finance/requests/${req.id}/give/`, { amount }), { success: "Hamyoniga yozildi", invalidate: ["finance"], onSuccess: onClose });
  return (
    <Modal
      open
      onClose={onClose}
      title={`So'rov #${req.number} — ${req.member_detail.name}`}
      size="sm"
      footer={<Button loading={save.isPending} onClick={() => save.mutate()}>Berdim</Button>}
    >
      <Field label="Qancha berdingiz?" hint={`Bo'sh qoldirsangiz — so'ralgan summa: ${req.currency === "USD" ? usd(req.orig_amount) : som(req.amount)}. Dollar: 300$`}>
        <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="500000 yoki 300$" />
      </Field>
    </Modal>
  );
}

/* ------------------------------------------------------------------ month reports */
export function FinanceReportsPage() {
  const { can } = useAuth();
  const { data: me } = useFinMe();
  const { data: members } = useMembers({ role: "staff" }, !!me?.view_all);
  const { state, page, set } = useUrlState({ month: "" });
  const { data, isFetching } = useList<MonthReport>("finance/month-reports", { ...state, page });
  const [submit, setSubmit] = useState(false);
  return (
    <div>
      <PageHeader
        title="Oylik hisob"
        subtitle="Xodimlar oy oxirida hisobini tasdiqlab topshiradi"
        actions={can("accounting.add_monthreport") && <Button onClick={() => setSubmit(true)}>📤 Hisob topshirish</Button>}
      />
      <div className="mb-4">
        <Input type="month" className="w-48" value={state.month} onChange={(e) => set({ month: e.target.value })} />
      </div>
      <Card padded={false}>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "m", header: "Oy", cell: (r) => r.month },
            { key: "x", header: "Xodim", cell: (r) => r.member_detail.name },
            { key: "b", header: "Oy oxiriga qoldiq", cell: (r) => <span className="tabular-nums">{som(r.balance)}</span> },
            { key: "s", header: "Topshirildi", cell: (r) => dateTime(r.submitted_at) },
            { key: "n", header: "Izoh", cell: (r) => r.note || "—", hideOnMobile: true },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {submit && <SubmitModal members={me?.view_all ? members?.filter((m) => m.has_wallet) ?? [] : []} self={me?.member?.id} onClose={() => setSubmit(false)} />}
    </div>
  );
}

function SubmitModal({ members, self, onClose }: { members: { id: number; name: string }[]; self?: number; onClose: () => void }) {
  const [member, setMember] = useState(self ? String(self) : "");
  const [month, setMonth] = useState("");
  const [note, setNote] = useState("");
  const { data: pv } = useGet<{ month: string; opening: number; income: number; expense: number; closing: number; count: number }>(
    member ? "/finance/month-reports/preview/" : null,
    { member, month },
  );
  const save = useAction(() => api.post("/finance/month-reports/submit/", { member: Number(member), month: month || pv?.month, note }), {
    success: "Topshirildi",
    invalidate: ["finance"],
    onSuccess: onClose,
  });
  return (
    <Modal open onClose={onClose} title="📤 Oylik hisob" size="sm" footer={<Button disabled={!member} loading={save.isPending} onClick={() => save.mutate()}>Tasdiqlayman</Button>}>
      <div className="space-y-4">
        {members.length > 0 && (
          <Field label="Xodim">
            <Select value={member} onChange={(e) => setMember(e.target.value)}>
              <option value="">—</option>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Oy">
          <Input type="month" value={month || pv?.month || ""} onChange={(e) => setMonth(e.target.value)} />
        </Field>
        {pv && (
          <ul className="space-y-1 text-sm">
            <li className="flex justify-between"><span>Oy boshida</span><span className="tabular-nums">{som(pv.opening)}</span></li>
            <li className="flex justify-between"><span>🟢 Kirim</span><span className="tabular-nums">{som(pv.income)}</span></li>
            <li className="flex justify-between"><span>🔴 Chiqim</span><span className="tabular-nums">{som(pv.expense)}</span></li>
            <li className="flex justify-between font-semibold"><span>👛 Oy oxiriga qoldiq</span><span className="tabular-nums">{som(pv.closing)}</span></li>
            <li className="muted">Amallar soni: {pv.count}</li>
          </ul>
        )}
        <Field label="Izoh (ixtiyoriy)">
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ follow-up (Готов) */
type Tab = "bonus" | "handover" | "warranty" | "site" | "feedback";

export function FinanceFollowupPage() {
  const { state, set } = useUrlState({ tab: "bonus" as Tab });
  return (
    <div>
      <PageHeader title="Готов zakazlar" subtitle="Bonus, rahbarga topshirish, kafolat xati, saytga kiritish va mijoz fikri" />
      <div className="mb-4">
        <Segmented
          value={state.tab as Tab}
          onChange={(tab) => set({ tab })}
          options={[
            { value: "bonus", label: "🎁 Bonuslar" },
            { value: "handover", label: "💵 Topshiruv" },
            { value: "warranty", label: "📜 Kafolat" },
            { value: "site", label: "🌐 Saytga kiritish" },
            { value: "feedback", label: "💬 Mijoz fikri" },
          ]}
        />
      </div>
      {state.tab === "bonus" && <BonusTab />}
      {state.tab === "handover" && <HandoverTab />}
      {state.tab === "warranty" && <WarrantyTab />}
      {state.tab === "site" && <SiteTab />}
      {state.tab === "feedback" && <FeedbackTab />}
    </div>
  );
}

function BonusTab() {
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ status: "waiting", search: "" });
  const { data, isFetching } = useList<Bonus>("finance/bonuses", { ...state, page });
  const close = useAction((id: number) => api.post(`/finance/bonuses/${id}/close/`), { success: "Yopildi", invalidate: ["finance"] });
  return (
    <Card padded={false}>
      <div className="border-b border-slate-100 p-4 dark:border-slate-800">
        <Segmented
          value={state.status}
          onChange={(status) => set({ status })}
          options={[
            { value: "waiting", label: "⏳ Kutilmoqda" },
            { value: "done", label: "✅ Olindi" },
            { value: "expired", label: "❌ 30 kundan o'tdi" },
            { value: "", label: "Hammasi" },
          ]}
        />
      </div>
      <DataTable
        rows={data?.results}
        loading={isFetching}
        rowKey={(r) => r.id}
        columns={[
          { key: "o", header: "Zakaz", cell: (r) => <span><b>{r.order_ref}</b> · {r.client}</span> },
          { key: "r", header: "Готов", cell: (r) => date(r.ready_date) },
          { key: "t", header: "Umumiy", cell: (r) => <span className="tabular-nums">{inCur(r.total, r.currency)}</span> },
          { key: "q", header: "Qoldiq", cell: (r) => <span className="tabular-nums">{r.rest === null ? "—" : inCur(r.rest, r.currency)}</span> },
          {
            key: "b",
            header: "Bonus",
            cell: (r) => (r.status === "waiting" ? <Badge tone="warn">{r.status_label}</Badge> : <span className="tabular-nums">{r.percent}% = {som(r.bonus)} <span className="muted">({r.days} kun)</span></span>),
          },
          { key: "n", header: "Izoh", cell: (r) => <span className="text-sm">{r.note || r.got_text || "—"}</span>, hideOnMobile: true },
          {
            key: "x",
            header: "",
            cell: (r) =>
              r.status === "waiting" && can("accounting.change_orderbonus") ? (
                <Button size="sm" variant="outline" onClick={() => confirm(`${r.order_ref} yopilsinmi? (qoldiq 0 bo'lishi kerak)`) && close.mutate(r.id)}>
                  Yopish
                </Button>
              ) : null,
          },
        ]}
      />
      <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
    </Card>
  );
}

function HandoverTab() {
  const { data, isFetching } = useGet<Operation[]>("/finance/handover/");
  const act = useAction((v: { operation: number; action: "accept" | "drop" }) => api.post("/finance/handover/", v), { success: "Belgilandi", invalidate: ["finance"] });
  return (
    <Card padded={false}>
      <p className="muted border-b border-slate-100 p-4 text-sm dark:border-slate-800">
        Xodim mijozdan olgan, lekin rahbarga hali topshirilmagan pullar. «Qabul qildim» — xodim balansidan yechiladi va rahbar kassasiga o'tadi.
      </p>
      <DataTable
        rows={data}
        loading={isFetching}
        rowKey={(r) => r.id}
        empty={<Empty title="Topshirilmagan pul yo'q" />}
        columns={[
          { key: "n", header: "№", cell: (r) => `#${r.number}` },
          { key: "d", header: "Sana", cell: (r) => date(r.date) },
          { key: "m", header: "Kim", cell: (r) => r.member_detail.name },
          { key: "o", header: "Zakaz", cell: (r) => r.order_ref },
          { key: "a", header: "Summa", cell: (r) => <span className="font-semibold tabular-nums">{r.currency === "USD" ? `${usd(r.orig_amount)} (${som(r.amount)})` : som(r.amount)}</span> },
          {
            key: "x",
            header: "",
            cell: (r) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" onClick={() => act.mutate({ operation: r.id, action: "accept" })}>Qabul qildim</Button>
                <Button size="sm" variant="outline" onClick={() => confirm("Bu yozuv o'chirilsinmi (alohida kiritilgan)?") && act.mutate({ operation: r.id, action: "drop" })}>
                  Alohida kiritilgan
                </Button>
              </div>
            ),
          },
        ]}
      />
    </Card>
  );
}

function WarrantyTab() {
  const { state, page, set } = useUrlState({ given: "0", search: "" });
  const { data, isFetching } = useList<Warranty>("finance/warranty", { ...state, page });
  const give = useAction((id: number) => api.post(`/finance/warranty/${id}/give/`), { success: "Berildi", invalidate: ["finance"] });
  return (
    <Card padded={false}>
      <div className="border-b border-slate-100 p-4 dark:border-slate-800">
        <Segmented value={state.given} onChange={(given) => set({ given })} options={[{ value: "0", label: "❌ Berilmagan" }, { value: "1", label: "✅ Berilgan" }, { value: "", label: "Hammasi" }]} />
      </div>
      <DataTable
        rows={data?.results}
        loading={isFetching}
        rowKey={(r) => r.id}
        columns={[
          { key: "o", header: "Zakaz", cell: (r) => <span><b>{r.order_ref}</b> · {r.client}</span> },
          { key: "r", header: "Готов", cell: (r) => date(r.ready_date) },
          { key: "g", header: "Holat", cell: (r) => (r.given ? <Badge tone="ok">Berildi · {date(r.given_at)} · {r.given_by}</Badge> : <Badge tone="warn">Berilmagan</Badge>) },
          { key: "x", header: "", cell: (r) => (!r.given ? <Button size="sm" variant="outline" onClick={() => give.mutate(r.id)}>📜 Berildi</Button> : null) },
        ]}
      />
      <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
    </Card>
  );
}

function SiteTab() {
  const { state, page, set } = useUrlState({ done: "0" });
  const { data, isFetching } = useList<SiteEntry>("finance/site-entry", { ...state, page });
  const done = useAction((id: number) => api.post(`/finance/site-entry/${id}/done/`), { success: "Belgilandi", invalidate: ["finance"] });
  return (
    <Card padded={false}>
      <div className="border-b border-slate-100 p-4 dark:border-slate-800">
        <Segmented value={state.done} onChange={(v) => set({ done: v })} options={[{ value: "0", label: "⏳ Kiritilmagan" }, { value: "1", label: "✅ Kiritilgan" }, { value: "", label: "Hammasi" }]} />
      </div>
      <DataTable
        rows={data?.results}
        loading={isFetching}
        rowKey={(r) => r.id}
        columns={[
          { key: "d", header: "Sana", cell: (r) => date(r.date) },
          { key: "o", header: "Zakaz", cell: (r) => <span><b>{r.order_ref}</b> · {r.client}</span> },
          { key: "s", header: "Olingan", cell: (r) => `${r.sum_text} (${r.taken_by})` },
          { key: "q", header: "Yangi qoldiq", cell: (r) => r.rest_text },
          { key: "x", header: "", cell: (r) => (r.is_done ? <span className="muted text-sm">✅ {date(r.done_at)} · {r.done_by}</span> : <Button size="sm" onClick={() => done.mutate(r.id)}>Saytga kiritdim</Button>) },
        ]}
      />
      <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
    </Card>
  );
}

/** Opens the picture inside the panel (never a new tab on /media/: a missing file
 * there is redirected to the Django admin by the server). */
function Screenshot({ url, onClose }: { url: string; onClose: () => void }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="fixed inset-0 z-[60] flex animate-fade-in items-center justify-center bg-black/80 p-4" onClick={onClose}>
      {broken ? (
        <p className="max-w-sm rounded-xl bg-white/10 p-4 text-center text-sm text-rose-200">⚠️ Skrinshot serverda topilmadi.</p>
      ) : (
        <img src={url} alt="Skrinshot" className="max-h-full max-w-full rounded-xl" onError={() => setBroken(true)} />
      )}
    </div>
  );
}

function FeedbackTab() {
  const { state, page, set } = useUrlState({ status: "asked" });
  const [shot, setShot] = useState<string | null>(null);
  const { data, isFetching } = useList<Feedback>("finance/feedback", { ...state, page });
  return (
    <Card padded={false}>
      <div className="border-b border-slate-100 p-4 dark:border-slate-800">
        <Segmented
          value={state.status}
          onChange={(status) => set({ status })}
          options={[{ value: "asked", label: "⏳ Kutilmoqda" }, { value: "received", label: "✅ Olindi" }, { value: "scheduled", label: "Rejada" }, { value: "", label: "Hammasi" }]}
        />
      </div>
      <DataTable
        rows={data?.results}
        loading={isFetching}
        rowKey={(r) => r.id}
        columns={[
          { key: "o", header: "Zakaz", cell: (r) => <span><b>{r.order_ref}</b> · {r.client}</span> },
          { key: "p", header: "Telefon", cell: (r) => r.phone || "—", hideOnMobile: true },
          { key: "r", header: "Готов", cell: (r) => date(r.ready_date) },
          { key: "t", header: "Fikr", cell: (r) => <span className="line-clamp-2 max-w-sm text-sm">{r.text || "—"}</span> },
          { key: "b", header: "Kim oldi", cell: (r) => (r.received_by ? `${r.received_by} · ${date(r.received_date)}` : "—"), hideOnMobile: true },
          { key: "s", header: "", cell: (r) => (r.screenshot_url ? <button className="text-brand-600 underline" onClick={() => setShot(r.screenshot_url)}>📷 Skrinshot</button> : null) },
        ]}
      />
      <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      {shot && <Screenshot url={shot} onClose={() => setShot(null)} />}
    </Card>
  );
}

/* ------------------------------------------------------------------ checks */
export function FinanceChecksPage() {
  const { data, isFetching } = useGet<Issue[]>("/finance/checks/");
  const icon = { h: "🔴", m: "🟠", l: "🟡" } as const;
  return (
    <div>
      <PageHeader title="Tekshiruv" subtitle="Kamchiliklar va ularning yechimlari (botdagi «🔍 Tekshiruv»)" />
      {isFetching && !data ? null : !data?.length ? (
        <Card>
          <Empty title="✅ Kamchilik topilmadi" />
        </Card>
      ) : (
        <div className="space-y-3">
          {data.map((i, k) => (
            <Card key={k}>
              <div className="font-semibold">
                {icon[i.level]} {i.title}
              </div>
              <div className="muted mt-1 text-sm">{i.detail}</div>
              <div className="mt-2 text-sm">💡 {i.fix}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
