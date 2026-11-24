import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Check, FileText, Plus, Printer, RotateCcw, Save, Send, Trash2, X } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import type { Tone } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import PdfViewer from "@/components/PdfViewer";
import {
  Badge,
  Button,
  Card,
  DataTable,
  Empty,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Pagination,
  PageLoader,
  SearchInput,
  Segmented,
  Select,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { som, usd } from "./shared";
import type {
  LineCalc,
  LineSection,
  OrderBrief,
  SalarySheet,
  SheetPreview,
  SheetKind,
  SheetListRow,
  SheetOptions,
  SheetStatus,
} from "./salaryTypes";

const BASE = "/finance/salary-sheets/";
const INVALIDATE = ["/finance/salary-sheets", "finance/salary-sheets", "/finance/workers"];

const STATUS_TONE: Record<SheetStatus, Tone> = { draft: "idle", submitted: "warn", approved: "ok" };

function StatusBadge({ status, label }: { status: SheetStatus; label: string }) {
  return <Badge tone={STATUS_TONE[status]}>{label}</Badge>;
}

/* =================================================================== list */

export function FinanceSalaryListPage() {
  const { can } = useAuth();
  const nav = useNavigate();
  const { state, page, set } = useUrlState({ status: "", month: "", search: "" });
  const { data, isFetching } = useList<SheetListRow>("finance/salary-sheets", { ...state, page });
  const [creating, setCreating] = useState(false);
  return (
    <div className="space-y-4">
      <PageHeader
        title="Oylik varaqlari"
        subtitle="Bugalter to'ldiradi va tasdiqlashga yuboradi, rahbar tasdiqlaydi — PDF xodim papkasiga o'zi tushadi. Hamyonga hali hech narsa yozilmaydi."
        actions={
          can("payroll.add_salarysheet") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Yangi varaq
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={state.status}
          onChange={(v) => set({ status: v })}
          options={[
            { value: "", label: "Hammasi" },
            { value: "draft", label: "Qoralama" },
            { value: "submitted", label: "Tasdiqlashda" },
            { value: "approved", label: "Tasdiqlangan" },
          ]}
        />
        <Input type="month" className="w-44" value={state.month} onChange={(e) => set({ month: e.target.value })} />
        <SearchInput value={state.search} onChange={(v) => set({ search: v })} placeholder="Xodim yoki buyurtma ID…" className="w-64" />
      </div>
      <Card className="overflow-hidden p-0">
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={(r) => nav(`/finance/salary/${r.id}`)}
          empty={<Empty title="Varaq yo'q" text="«Yangi varaq» bilan xodim uchun oylik varag'ini oching." />}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="muted tabular-nums">{r.number}</span> },
            {
              key: "w",
              header: "Xodim",
              cell: (r) => (
                <div>
                  <div className="font-medium">{r.worker_name}</div>
                  {r.partners.length > 0 && <div className="muted text-xs">+ {r.partners.join(", ")}</div>}
                </div>
              ),
            },
            { key: "k", header: "Turi", cell: (r) => <span className="text-sm">{r.kind_label}</span>, hideOnMobile: true },
            { key: "m", header: "Oy", cell: (r) => r.month },
            {
              key: "s",
              header: "Holat",
              cell: (r) => (
                <div className="flex flex-wrap items-center gap-1">
                  <StatusBadge status={r.status} label={r.status_label} />
                  {r.returned_note && r.status === "draft" && <Badge tone="danger">Qaytarilgan</Badge>}
                </div>
              ),
            },
            { key: "e", header: "Hisoblangan", className: "text-right", cell: (r) => <span className="tabular-nums">{som(r.earned)}</span>, hideOnMobile: true },
            {
              key: "r",
              header: "Ostatok",
              className: "text-right",
              cell: (r) => <span className={cn("font-semibold tabular-nums", r.rest < 0 && "text-rose-600")}>{som(r.rest)}</span>,
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {creating && <CreateModal onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateModal({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const { data: opts } = useGet<SheetOptions>(`${BASE}options/`);
  const [worker, setWorker] = useState("");
  const [kind, setKind] = useState("");
  const [month, setMonth] = useState("");
  const create = useAction(
    () => api.post<SalarySheet>(BASE, { worker: Number(worker), kind, month }).then((r) => r.data),
    { success: "Varaq ochildi", invalidate: INVALIDATE, onSuccess: (s) => nav(`/finance/salary/${s.id}`) },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title="Yangi oylik varag'i"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Bekor
          </Button>
          <Button loading={create.isPending} disabled={!worker} onClick={() => create.mutate()}>
            Ochish
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Xodim">
          <Select value={worker} onChange={(e) => setWorker(e.target.value)}>
            <option value="">— tanlang —</option>
            {opts?.workers.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
                {w.group ? ` · ${w.group}` : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Varaq turi" hint="Bo'sh — xodimning oldingi varag'idagidek (fiksa, foizlar, sheriklar ham ko'chiriladi)">
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Oldingi varaqdagidek</option>
            {opts?.kinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Oy" hint="Bo'sh — keyingi oylik kuni bo'yicha (davr va avanslar o'zi olinadi)">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

/* =================================================================== the sheet */

interface FormLine {
  key: number;
  section: LineSection;
  order_ref: string;
  title: string;
  on_date: string;
  paid_on: string;
  currency: "UZS" | "USD";
  amount: string;
  rate: string;
}

interface Form {
  kind: SheetKind;
  section: string;
  position: string;
  month: string;
  period_start: string;
  period_end: string;
  usd_rate: string;
  fixed: string;
  bonus_percent: string;
  bonus2_percent: string;
  late_days: string;
  late_rate: string;
  late_dates: string;
  absent_days: string;
  absent_rate: string;
  absent_dates: string;
  instagram_count: string;
  note: string;
  members: { worker: string; share: string }[];
  lines: FormLine[];
}

let seq = 0;
const nextKey = () => ++seq;
const n0 = (v: string | null | undefined) => (v == null ? "" : String(Number(v)));

function toForm(s: SalarySheet): Form {
  return {
    kind: s.kind,
    section: s.section,
    position: s.position,
    month: s.month,
    period_start: s.period_start,
    period_end: s.period_end,
    usd_rate: n0(s.usd_rate),
    fixed: n0(s.fixed),
    bonus_percent: n0(s.bonus_percent),
    bonus2_percent: n0(s.bonus2_percent),
    late_days: String(s.late_days),
    late_rate: n0(s.late_rate),
    late_dates: s.late_dates,
    absent_days: String(s.absent_days),
    absent_rate: n0(s.absent_rate),
    absent_dates: s.absent_dates,
    instagram_count: String(s.instagram_count),
    note: s.note,
    members: s.members.map((m) => ({ worker: String(m.worker_id), share: m.share })),
    lines: s.lines.map((l) => ({
      key: nextKey(),
      section: l.section,
      order_ref: l.order_ref,
      title: l.title,
      on_date: l.on_date ?? "",
      paid_on: l.paid_on ?? "",
      currency: l.currency,
      amount: n0(l.amount),
      rate: l.rate ? n0(l.rate) : "",
    })),
  };
}

function toPayload(f: Form) {
  const num = (v: string) => (v === "" ? "0" : v);
  return {
    kind: f.kind,
    section: f.section,
    position: f.position,
    month: f.month,
    period_start: f.period_start,
    period_end: f.period_end,
    usd_rate: f.usd_rate,
    fixed: num(f.fixed),
    bonus_percent: num(f.bonus_percent),
    bonus2_percent: num(f.bonus2_percent),
    late_days: Number(f.late_days || 0),
    late_rate: num(f.late_rate),
    late_dates: f.late_dates,
    absent_days: Number(f.absent_days || 0),
    absent_rate: num(f.absent_rate),
    absent_dates: f.absent_dates,
    instagram_count: Number(f.instagram_count || 0),
    note: f.note,
    ...(f.kind === "sborka" ? { members: f.members.map((m) => ({ worker: Number(m.worker), share: m.share || "0" })) } : {}),
    lines: f.lines.map((l) => ({
      section: l.section,
      order_ref: l.order_ref,
      title: l.title,
      on_date: l.on_date || null,
      paid_on: l.paid_on || null,
      currency: l.currency,
      amount: l.amount || "0",
      rate: l.rate || null,
    })),
  };
}

type LineInfo = { calc: LineCalc | null; found: boolean | null; order: OrderBrief | null };
/** what the order lookup last put into a row (null = the user's own value, never touched) */
type AutoFilled = { ref: string; title: string | null; amount: string | null; on_date: string | null };

const normRef = (r: string) => r.trim().replace(/^#/, "");
const numStr = (v: string) => String(Number(v));

/** Fill client name / order sum / hand-over date from the typed ID — only into fields
 * that are empty or still hold what an earlier lookup put there (the user's own edits
 * stay). Returns the same object when nothing changes (no render loop). */
function fillFromOrders(f: Form, sent: { key: number; ref: string }[], data: SheetPreview, memo: Record<number, AutoFilled>): Form {
  let changed = false;
  const lines = f.lines.map((l) => {
    const i = sent.findIndex((x) => x.key === l.key);
    const o = i >= 0 ? data.lines[i]?.order : null;
    const ref = normRef(l.order_ref);
    if (!o || !ref || sent[i].ref !== ref) return l;
    const prev = memo[l.key];
    const free = (field: "title" | "amount" | "on_date") => l[field] === "" || (prev?.[field] != null && l[field] === prev[field]);
    const auto: AutoFilled = { ref, title: null, amount: null, on_date: null };
    const next = { ...l };
    if (l.section !== "collect" && free("title")) next.title = auto.title = o.client;
    let amount: string | null = null;
    if ((l.section === "taken" || l.section === "delivered") && o.total_usd) amount = numStr(o.total_usd);
    if (l.section === "collect" && Number(o.total) > 0) amount = numStr(o.total);
    if (amount && free("amount")) {
      next.amount = auto.amount = amount;
      if (l.section === "collect") next.currency = o.currency;
    }
    if (l.section === "collect" && o.ready_date && free("on_date")) next.on_date = auto.on_date = o.ready_date;
    memo[l.key] = auto;
    // idempotent: only a real difference makes a new form (no request loop)
    if (next.title === l.title && next.amount === l.amount && next.on_date === l.on_date && next.currency === l.currency) return l;
    changed = true;
    return next;
  });
  return changed ? { ...f, lines } : f;
}

export function FinanceSalarySheetPage() {
  const { id } = useParams();
  const path = `${BASE}${id}/`;
  const { data: sheet, isLoading } = useGet<SalarySheet>(path);
  const { data: opts } = useGet<SheetOptions>(`${BASE}options/`);
  if (isLoading || !sheet || !opts) return <PageLoader />;
  return <SheetEditor key={`${sheet.id}-${sheet.status}-${sheet.version}`} sheet={sheet} opts={opts} />;
}

function useSheetAction(path: string, name: string, success: string, onSuccess: (s: SalarySheet) => void) {
  return useAction(
    (body: Record<string, string> | void) => api.post<SalarySheet>(`${path}${name}/`, body ?? {}).then((r) => r.data),
    { success, invalidate: INVALIDATE, onSuccess },
  );
}

function SheetEditor({ sheet: initial, opts }: { sheet: SalarySheet; opts: SheetOptions }) {
  const nav = useNavigate();
  const [sheet, setSheet] = useState(initial);
  const [form, setForm] = useState<Form>(() => toForm(initial));
  const [dirty, setDirty] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [returning, setReturning] = useState(false);
  const [preview, setPreview] = useState<{ keys: number[]; data: SheetPreview } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const autoFill = useRef<Record<number, AutoFilled>>({});
  const reqSeq = useRef(0);
  useEffect(() => setSheet(initial), [initial]);

  const edit = sheet.can.edit;
  const kindInfo = opts.kinds.find((k) => k.value === form.kind)!;
  const fields = new Set(kindInfo.fields);
  const path = `${BASE}${sheet.id}/`;

  const apply = (s: SalarySheet) => {
    setSheet(s);
    setForm(toForm(s));
    setDirty(false);
    setPreview(null);
    reqSeq.current++;
  };

  // the unsaved form computed by the server (debounced): live totals + the order
  // behind every typed ID, which fills the client name / sum while they are untouched
  useEffect(() => {
    if (!edit || !dirty) return;
    const id = ++reqSeq.current;
    const sent = form.lines.map((l) => ({ key: l.key, ref: normRef(l.order_ref) }));
    const body = toPayload(form);
    setPreviewing(true);
    const timer = setTimeout(() => {
      api
        .post<SheetPreview>(`${path}preview/`, body)
        .then((r) => {
          if (id !== reqSeq.current) return;
          setPreview({ keys: sent.map((x) => x.key), data: r.data });
          setPreviewing(false);
          setForm((f) => fillFromOrders(f, sent, r.data, autoFill.current));
        })
        .catch(() => id === reqSeq.current && setPreviewing(false));
    }, 400);
    return () => clearTimeout(timer);
  }, [form, dirty, edit, path]);

  const live = dirty && preview ? preview.data : null;
  const stale = dirty && (previewing || !preview);
  const lineInfo = useMemo(() => {
    const m = new Map<number, LineInfo>();
    if (live && preview) preview.keys.forEach((k, i) => m.set(k, preview.data.lines[i]));
    else if (!dirty) form.lines.forEach((l, i) => sheet.lines[i] && m.set(l.key, { calc: sheet.lines[i], found: null, order: null }));
    return m;
  }, [live, preview, dirty, form.lines, sheet.lines]);
  const sectionTotals = live?.sections ?? sheet.sections;
  const shown = live ? { ...sheet, members: live.members, advances: live.advances } : sheet;
  const upd = (patch: Partial<Form>) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };

  const save = useAction(() => api.patch<SalarySheet>(path, toPayload(form)).then((r) => r.data), {
    success: "Saqlandi",
    invalidate: INVALIDATE,
    onSuccess: apply,
  });
  const submit = useSheetAction(path, "submit", "Tasdiqlashga yuborildi", apply);
  const approve = useSheetAction(path, "approve", "Tasdiqlandi — PDF xodim papkasiga saqlandi", apply);
  const ret = useSheetAction(path, "return", "Qoralamaga qaytarildi", apply);
  const remove = useAction(() => api.delete(path), {
    success: "Varaq o'chirildi",
    invalidate: INVALIDATE,
    onSuccess: () => nav("/finance/salary"),
  });

  const t = live?.totals ?? sheet.totals;
  const busy = save.isPending || submit.isPending || approve.isPending || ret.isPending;

  return (
    <div className="space-y-4">
      <PageHeader
        back={
          <Link to="/finance/salary" className="muted mb-1 inline-flex items-center gap-1 text-sm hover:text-brand-600">
            <ArrowLeft className="h-4 w-4" /> Oylik varaqlari
          </Link>
        }
        title={`№${sheet.number} · ${sheet.worker}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={sheet.status} label={sheet.status_label} />
            <span>{sheet.kind_label}</span>
            <span>· {sheet.month_label}</span>
            {sheet.version > 1 && <span>· {sheet.version}-versiya</span>}
            {sheet.approved_by && sheet.status === "approved" && (
              <span>
                · tasdiqladi: {sheet.approved_by}, {date(sheet.approved_at)}
              </span>
            )}
          </span>
        }
        actions={
          <>
            <Button variant="outline" icon={<Printer className="h-4 w-4" />} disabled={dirty} onClick={() => setPrinting(true)}>
              Chop etish
            </Button>
            {sheet.can.delete && (
              <IconButton label="O'chirish" onClick={() => confirm("Varaq o'chirilsinmi?") && remove.mutate()}>
                <Trash2 className="h-5 w-5" />
              </IconButton>
            )}
          </>
        }
      />

      {sheet.returned_note && sheet.status === "draft" && (
        <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-300">
          <b>Rahbar qaytardi:</b> {sheet.returned_note}
        </div>
      )}
      {sheet.warnings.length > 0 && (
        <div className="space-y-1 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
          {sheet.warnings.map((w) => (
            <div key={w} className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {w}
            </div>
          ))}
        </div>
      )}

      <Card className="p-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Varaq turi">
            <Select value={form.kind} disabled={!edit} onChange={(e) => upd({ kind: e.target.value as SheetKind })}>
              {opts.kinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Soha / bo'lim">
            <Input value={form.section} disabled={!edit} onChange={(e) => upd({ section: e.target.value })} />
          </Field>
          <Field label="Lavozim">
            <Input value={form.position} disabled={!edit} onChange={(e) => upd({ position: e.target.value })} />
          </Field>
          <Field label="Oy">
            <Input type="month" value={form.month} disabled={!edit} onChange={(e) => upd({ month: e.target.value })} />
          </Field>
          <Field label="Davr boshi" hint="Avanslar shu davrdan olinadi">
            <Input type="date" value={form.period_start} disabled={!edit} onChange={(e) => upd({ period_start: e.target.value })} />
          </Field>
          <Field label="Davr oxiri">
            <Input type="date" value={form.period_end} disabled={!edit} onChange={(e) => upd({ period_end: e.target.value })} />
          </Field>
          <Field label="1 USD kursi (so'm)">
            <Input type="number" inputMode="decimal" value={form.usd_rate} disabled={!edit} onChange={(e) => upd({ usd_rate: e.target.value })} />
          </Field>
          {fields.has("fixed") && (
            <Field label={form.kind === "ofis" ? "Oklad (so'm)" : "Fiksa (so'm)"}>
              <Input type="number" inputMode="decimal" value={form.fixed} disabled={!edit} onChange={(e) => upd({ fixed: e.target.value })} />
            </Field>
          )}
        </div>
      </Card>

      {form.kind === "sborka" && <MembersCard form={form} opts={opts} sheet={shown} edit={edit} upd={upd} />}

      {kindInfo.sections.map((sec) => (
        <LinesCard
          key={sec}
          section={sec}
          form={form}
          opts={opts}
          edit={edit}
          upd={upd}
          info={lineInfo}
          total={sectionTotals.find((s) => s.key === sec)?.total}
          stale={stale}
        />
      ))}

      {(fields.has("instagram") || fields.has("late") || fields.has("absent")) && (
        <Card className="p-5">
          <div className="grid gap-4 lg:grid-cols-3">
            {fields.has("late") && (
              <DaysBlock
                title="Kech qolgan (shtraf)"
                days={form.late_days}
                rate={form.late_rate}
                dates={form.late_dates}
                edit={edit}
                onChange={(d, r, s) => upd({ late_days: d, late_rate: r, late_dates: s })}
              />
            )}
            {fields.has("absent") && (
              <DaysBlock
                title="Kelmagan kunlar"
                days={form.absent_days}
                rate={form.absent_rate}
                dates={form.absent_dates}
                edit={edit}
                onChange={(d, r, s) => upd({ absent_days: d, absent_rate: r, absent_dates: s })}
              />
            )}
            {fields.has("instagram") && (
              <div className="space-y-2">
                <div className="font-medium">Instagram istoriya bonusi</div>
                <Field
                  label="Qo'yilgan istoriyalar soni"
                  hint={opts.instagram_tiers.map((x) => `${x.from}+ → ${Number(x.usd)}$`).join(" · ")}
                >
                  <Input type="number" min={0} value={form.instagram_count} disabled={!edit} onChange={(e) => upd({ instagram_count: e.target.value })} />
                </Field>
                {t.instagram_usd && (
                  <div className={cn("text-sm", stale && "opacity-50")}>
                    Bonus: <b>{usd(t.instagram_usd)}</b>
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
      )}

      <AdvancesCard sheet={shown} />

      <Card className="p-5">
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 font-semibold">Yakuniy hisob-kitob</h3>
            {dirty && (
              <p className="mb-2 text-xs text-amber-700 dark:text-amber-300">
                {stale ? "Hisoblanmoqda…" : "Hisob yangilandi, lekin hali saqlanmagan — «Saqlash»ni bosing."}
              </p>
            )}
            <div className={cn("divide-y divide-slate-100 text-sm dark:divide-slate-800", stale && "opacity-50")}>
              {t.earned.map((x) => (
                <Row key={x.label} label={x.label} value={som(x.amount)} />
              ))}
              <Row label={<b>Jami hisoblangan</b>} value={<b>{som(t.earned_total)}</b>} />
              {t.minus.map((x) => (
                <Row key={x.label} label={`(−) ${x.label}`} value={som(x.amount)} />
              ))}
              <Row label="(−) Olingan avanslar" value={som(t.advances_total)} />
              <Row
                label={<b className="text-base">{Number(t.rest) >= 0 ? "OSTATOK (berilishi kerak)" : "QARZ (ortiqcha olgan)"}</b>}
                value={
                  <b className={cn("text-base", Number(t.rest) < 0 && "text-rose-600")}>
                    {som(t.rest)}
                    {t.rest_usd && <span className="muted ml-1 text-xs font-normal">({usd(t.rest_usd)})</span>}
                  </b>
                }
              />
              {t.car_total && Number(t.car_total) > 0 && <Row label="Mashina puli (alohida, qoldiqqa kirmaydi)" value={som(t.car_total)} />}
            </div>
          </div>
          <Field label="Izoh">
            <Textarea value={form.note} disabled={!edit} onChange={(e) => upd({ note: e.target.value })} />
          </Field>
        </div>
      </Card>

      <div className="sticky bottom-0 z-20 -mx-1 rounded-2xl border border-slate-200 bg-white/95 px-4 py-3 shadow-pop backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
        <div className="flex flex-wrap items-center justify-end gap-2">
          {dirty && <span className="muted mr-auto text-sm">Saqlanmagan o'zgarishlar bor</span>}
          {edit && (
            <Button variant={dirty ? "primary" : "outline"} icon={<Save className="h-4 w-4" />} loading={save.isPending} disabled={!dirty || busy} onClick={() => save.mutate()}>
              Saqlash
            </Button>
          )}
          {sheet.can.return && (
            <Button variant="outline" icon={<RotateCcw className="h-4 w-4" />} disabled={busy} onClick={() => setReturning(true)}>
              {sheet.status === "approved" ? "Qayta ochish" : "Qaytarish"}
            </Button>
          )}
          {sheet.can.submit && !sheet.can.approve && (
            <Button icon={<Send className="h-4 w-4" />} disabled={dirty || busy} loading={submit.isPending} onClick={() => submit.mutate()}>
              Tasdiqlashga yuborish
            </Button>
          )}
          {sheet.can.approve && (
            <Button
              icon={<Check className="h-4 w-4" />}
              disabled={dirty || busy}
              loading={approve.isPending}
              onClick={() => confirm(`№${sheet.number} — ${som(t.rest)} tasdiqlansinmi? PDF xodim papkasiga saqlanadi.`) && approve.mutate()}
            >
              Tasdiqlash
            </Button>
          )}
        </div>
      </div>

      {printing && (
        <PdfViewer url={`${path}pdf/`} name={`Oylik varaqasi №${sheet.number}`} downloadName={`Oylik_${sheet.month}_${sheet.worker}.pdf`} onClose={() => setPrinting(false)} />
      )}
      {returning && (
        <ReturnModal
          approved={sheet.status === "approved"}
          loading={ret.isPending}
          onClose={() => setReturning(false)}
          onSubmit={(reason) => ret.mutate({ reason }, { onSuccess: () => setReturning(false) })}
        />
      )}
    </div>
  );
}

function Row({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span>{label}</span>
      <span className="whitespace-nowrap tabular-nums">{value}</span>
    </div>
  );
}

function DaysBlock({
  title,
  days,
  rate,
  dates,
  edit,
  onChange,
}: {
  title: string;
  days: string;
  rate: string;
  dates: string;
  edit: boolean;
  onChange: (days: string, rate: string, dates: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="font-medium">{title}</div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Kun soni">
          <Input type="number" min={0} value={days} disabled={!edit} onChange={(e) => onChange(e.target.value, rate, dates)} />
        </Field>
        <Field label="Bir kun (so'm)">
          <Input type="number" min={0} value={rate} disabled={!edit} onChange={(e) => onChange(days, e.target.value, dates)} />
        </Field>
      </div>
      <Field label="Sanalar (ixtiyoriy)">
        <Input value={dates} disabled={!edit} placeholder="3, 12, 19" onChange={(e) => onChange(days, rate, e.target.value)} />
      </Field>
      <div className="muted text-xs">= {som(Number(days || 0) * Number(rate || 0))}</div>
    </div>
  );
}

function MembersCard({
  form,
  opts,
  sheet,
  edit,
  upd,
}: {
  form: Form;
  opts: SheetOptions;
  sheet: SalarySheet;
  edit: boolean;
  upd: (p: Partial<Form>) => void;
}) {
  const members = form.members.length ? form.members : [{ worker: String(sheet.worker_id), share: "100" }];
  const sum = members.reduce((a, m) => a + Number(m.share || 0), 0);
  const set = (i: number, patch: Partial<{ worker: string; share: string }>) =>
    upd({ members: members.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  const computed = new Map(sheet.members.map((m) => [String(m.worker_id), m]));
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold">Ulushlar (xodim + 2 tagacha sherik)</h3>
        <span className={cn("text-sm tabular-nums", Math.abs(sum - 100) > 0.0001 ? "text-rose-600" : "muted")}>Jami: {sum} %</span>
      </div>
      <div className="space-y-2">
        {members.map((m, i) => {
          const c = computed.get(m.worker);
          return (
            <div key={i} className="grid grid-cols-[1fr_90px_auto] items-center gap-2 sm:grid-cols-[1fr_100px_1fr_auto]">
              <Select value={m.worker} disabled={!edit || i === 0} onChange={(e) => set(i, { worker: e.target.value })}>
                <option value="">— sherik —</option>
                {opts.workers.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
                {i === 0 && !opts.workers.some((w) => w.id === sheet.worker_id) && <option value={sheet.worker_id}>{sheet.worker}</option>}
              </Select>
              <div className="relative">
                <Input type="number" min={0} max={100} value={m.share} disabled={!edit} onChange={(e) => set(i, { share: e.target.value })} />
                <span className="muted pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm">%</span>
              </div>
              <div className="muted hidden text-sm sm:block">
                {c && (
                  <>
                    {som(c.amount)} − avans {som(c.advances)} = <b className="text-slate-900 dark:text-white">{som(c.rest)}</b>
                  </>
                )}
              </div>
              {edit && i > 0 ? (
                <IconButton label="Olib tashlash" onClick={() => upd({ members: members.filter((_, j) => j !== i) })}>
                  <X className="h-4 w-4" />
                </IconButton>
              ) : (
                <span />
              )}
            </div>
          );
        })}
      </div>
      {edit && members.length < 3 && (
        <Button variant="ghost" size="sm" className="mt-2" icon={<Plus className="h-4 w-4" />} onClick={() => upd({ members: [...members, { worker: "", share: "" }] })}>
          Sherik qo'shish
        </Button>
      )}
    </Card>
  );
}

const SECTION_HINT: Partial<Record<LineSection, string>> = {
  job: "Har qator — bitta buyurtma ID va shu ish uchun summa (so'm). Mijoz ismi ID dan o'zi olinadi.",
  taken: "Buyurtma summasi dollarda yoziladi — bonus = summa × foiz × kurs.",
  delivered: "Buyurtma summasi dollarda yoziladi — bonus = summa × foiz × kurs.",
  collect: "Topshirilgan va pul yechilgan sana — kunlar bo'yicha foiz o'zi hisoblanadi.",
  deduction: "Beydjik va boshqa ushlanmalar. Avanslar bu yerga yozilmaydi — ular «Amallar»dan o'zi olinadi.",
  car: "Mashina puli alohida ko'rsatiladi va qoldiqqa qo'shilmaydi (Excel'dagidek).",
};

function LinesCard({
  section,
  form,
  opts,
  edit,
  upd,
  info,
  total,
  stale,
}: {
  section: LineSection;
  form: Form;
  opts: SheetOptions;
  edit: boolean;
  upd: (p: Partial<Form>) => void;
  info: Map<number, LineInfo>;
  total: string | undefined;
  stale: boolean;
}) {
  const rows = form.lines.filter((l) => l.section === section);
  const hasRef = section === "job" || section === "taken" || section === "delivered" || section === "collect";
  const pct = section === "taken" ? "bonus_percent" : section === "delivered" ? "bonus2_percent" : null;

  const setLine = (key: number, patch: Partial<FormLine>) =>
    upd({ lines: form.lines.map((l) => (l.key === key ? { ...l, ...patch } : l)) });
  const add = () =>
    upd({
      lines: [
        ...form.lines,
        {
          key: nextKey(),
          section,
          order_ref: "",
          title: "",
          on_date: "",
          paid_on: "",
          currency: section === "taken" || section === "delivered" || section === "collect" ? "USD" : "UZS",
          amount: "",
          rate: "",
        },
      ],
    });

  return (
    <Card className="p-5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{opts.section_titles[section]}</h3>
        {pct && (
          <label className="flex items-center gap-2 text-sm">
            Bonus foizi
            <Input
              type="number"
              inputMode="decimal"
              className="w-24"
              value={form[pct]}
              disabled={!edit}
              onChange={(e) => upd({ [pct]: e.target.value } as Partial<Form>)}
            />
            %
          </label>
        )}
      </div>
      <p className="muted mb-3 text-xs">
        {SECTION_HINT[section]}
        {section === "collect" && " " + opts.collect_tiers.map((x) => `≤${x.days} kun → ${Number(x.percent)}%`).join(" · ") + ", undan keyin 0"}
      </p>
      {rows.length === 0 ? (
        <p className="muted py-2 text-sm">Qator yo'q.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="w-8 py-1">№</th>
                {hasRef && <th className="w-28 py-1">ID</th>}
                {(section === "collect" || section === "deduction") && <th className="w-36 py-1">{section === "collect" ? "Topshirildi" : "Sana"}</th>}
                {section === "collect" && <th className="w-36 py-1">Pul yechildi</th>}
                {section !== "collect" && <th className="py-1">{section === "car" ? "Izoh (oy)" : hasRef ? "Mijoz / ish nomi" : "Nomi / izoh"}</th>}
                {(section === "collect" || section === "deduction") && <th className="w-24 py-1">Valyuta</th>}
                <th className="w-36 py-1 text-right">{section === "taken" || section === "delivered" ? "Summa ($)" : "Summa"}</th>
                {section === "deduction" && <th className="w-28 py-1 text-right">Kurs</th>}
                {section !== "job" && section !== "car" && <th className="w-32 py-1 text-right">So'mda</th>}
                {edit && <th className="w-8" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((l, i) => {
                const li = info.get(l.key);
                const s = li?.calc;
                return (
                  <tr key={l.key} className="border-t border-slate-100 align-top dark:border-slate-800">
                    <td className="muted py-3">{i + 1}</td>
                    {hasRef && (
                      <td className="py-1.5 pr-2">
                        <Input value={l.order_ref} disabled={!edit} placeholder="406" onChange={(e) => setLine(l.key, { order_ref: e.target.value })} />
                        {li?.found === false && normRef(l.order_ref) && <div className="mt-0.5 text-xs text-rose-600">ID topilmadi</div>}
                        {li?.order && (
                          <div className="muted mt-0.5 max-w-[11rem] truncate text-xs" title={`${li.order.client} · ${li.order.status}`}>
                            {section === "collect" ? li.order.client : li.order.status}
                            {li.order.total_usd && ` · ${usd(li.order.total_usd)}`}
                          </div>
                        )}
                      </td>
                    )}
                    {(section === "collect" || section === "deduction") && (
                      <td className="py-1.5 pr-2">
                        <Input type="date" value={l.on_date} disabled={!edit} onChange={(e) => setLine(l.key, { on_date: e.target.value })} />
                      </td>
                    )}
                    {section === "collect" && (
                      <td className="py-1.5 pr-2">
                        <Input type="date" value={l.paid_on} disabled={!edit} onChange={(e) => setLine(l.key, { paid_on: e.target.value })} />
                      </td>
                    )}
                    {section !== "collect" && (
                      <td className="py-1.5 pr-2">
                        <Input value={l.title} disabled={!edit} placeholder={hasRef ? "ID dan o'zi olinadi" : ""} onChange={(e) => setLine(l.key, { title: e.target.value })} />
                      </td>
                    )}
                    {(section === "collect" || section === "deduction") && (
                      <td className="py-1.5 pr-2">
                        <Select value={l.currency} disabled={!edit} onChange={(e) => setLine(l.key, { currency: e.target.value as "UZS" | "USD" })}>
                          <option value="USD">USD</option>
                          <option value="UZS">UZS</option>
                        </Select>
                      </td>
                    )}
                    <td className="py-1.5 pr-2">
                      <Input type="number" inputMode="decimal" className="text-right" value={l.amount} disabled={!edit} onChange={(e) => setLine(l.key, { amount: e.target.value })} />
                    </td>
                    {section === "deduction" && (
                      <td className="py-1.5 pr-2">
                        <Input
                          type="number"
                          inputMode="decimal"
                          className="text-right"
                          value={l.rate}
                          disabled={!edit || l.currency !== "USD"}
                          placeholder={l.currency === "USD" ? "umumiy" : ""}
                          onChange={(e) => setLine(l.key, { rate: e.target.value })}
                        />
                      </td>
                    )}
                    {section !== "job" && section !== "car" && (
                      <td className={cn("py-3 text-right tabular-nums", stale && "opacity-50")}>
                        {s ? (
                          <span title={s.days != null ? `${s.days} kun · ${Number(s.percent ?? 0)}%` : undefined}>
                            {som(s.value)}
                            {s.days != null && <span className="muted block text-xs">{s.days} kun · {Number(s.percent ?? 0)}%</span>}
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    )}
                    {edit && (
                      <td className="py-1.5 text-right">
                        <IconButton label="Qatorni o'chirish" onClick={() => upd({ lines: form.lines.filter((x) => x.key !== l.key) })}>
                          <X className="h-4 w-4" />
                        </IconButton>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        {edit ? (
          <Button variant="ghost" size="sm" icon={<Plus className="h-4 w-4" />} onClick={add}>
            Qator qo'shish
          </Button>
        ) : (
          <span />
        )}
        {total !== undefined && (
          <span className={cn("text-sm", stale && "opacity-50")}>
            Jami: <b className="tabular-nums">{som(total)}</b>
          </span>
        )}
      </div>
    </Card>
  );
}

function AdvancesCard({ sheet }: { sheet: SalarySheet }) {
  const many = sheet.kind === "sborka" && sheet.members.length > 1;
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-semibold">Olingan avanslar</h3>
        <span className="text-sm">
          Jami: <b className="tabular-nums">{som(sheet.totals.advances_total)}</b>
        </span>
      </div>
      <p className="muted mb-2 text-xs">
        {sheet.status === "approved"
          ? "Tasdiqlangan paytdagi holat — keyin yozilgan avanslar bu varaqni o'zgartirmaydi."
          : "«Amallar»dagi «Avans» turidagi oyliklar, davr bo'yicha o'zi olinadi" + (many ? " (sheriklarniki ham)." : ".")}
      </p>
      {sheet.advances.length === 0 ? (
        <p className="muted text-sm">Bu davrda avans berilmagan.</p>
      ) : (
        <div className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {sheet.advances.map((a) => (
            <div key={a.id} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
              <span>
                <span className="muted">{date(a.date)}</span>
                {many && <b> · {a.worker}</b>}
                <span className="muted"> · berdi: {a.given_by}</span>
                {a.comment && <span className="muted"> · {a.comment}</span>}
              </span>
              <span className="tabular-nums">
                {som(a.amount)}
                {a.currency === "USD" && a.orig_amount && <span className="muted ml-1 text-xs">({usd(a.orig_amount)})</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ReturnModal({
  approved,
  loading,
  onClose,
  onSubmit,
}: {
  approved: boolean;
  loading: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Modal
      open
      onClose={onClose}
      title={approved ? "Tasdiqlangan varaqni qayta ochish" : "Varaqni qoralamaga qaytarish"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Bekor
          </Button>
          <Button loading={loading} disabled={approved && !reason.trim()} onClick={() => onSubmit(reason)}>
            Qaytarish
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {approved && (
          <p className="text-sm">
            Avval saqlangan PDF papkada qoladi. Qayta tasdiqlanganda yangi versiya (v2, v3…) alohida saqlanadi.
          </p>
        )}
        <Field label={approved ? "Sabab (majburiy)" : "Sabab (bugalterga ko'rinadi)"}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

/** «Ishchi kartasi» → this worker's sheets on the site. */
export function WorkerSheetsLink({ workerId }: { workerId: number }) {
  const { can } = useAuth();
  const { data } = useList<SheetListRow>("finance/salary-sheets", { worker: workerId }, can("payroll.view_salarysheet"));
  const last = useMemo(() => data?.results?.[0], [data]);
  if (!can("payroll.view_salarysheet")) return null;
  return (
    <Link to={last ? `/finance/salary/${last.id}` : `/finance/salary`} className="inline-flex">
      <Button variant="outline" icon={<FileText className="h-4 w-4" />}>
        {last ? `Oylik varag'i (${last.month})` : "Oylik varaqlari"}
      </Button>
    </Link>
  );
}
