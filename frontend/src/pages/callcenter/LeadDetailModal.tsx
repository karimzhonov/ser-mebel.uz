import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRightLeft,
  CheckCircle2,
  ClipboardList,
  MessageSquare,
  Package,
  PhoneCall,
  Plus,
  Ruler,
  Sparkles,
  Tag,
  UserRound,
} from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useMeta } from "@/api/hooks";
import type { Invoice, InvoiceTask, Metering, Order, TimelineEntry } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { MeteringStatusBadge, OrderStatusBadge, PhoneLink, SolutionBadge } from "@/components/domain";
import { Button, Empty, Field, Input, KV, Modal, Select, Spinner, Textarea, TONES } from "@/components/ui";
import { cn } from "@/lib/cn";
import { dateTime } from "@/lib/format";
import { MeteringCreateModal } from "../Meterings";
import { LeadCreateModal } from "./LeadCreateModal";
import {
  AssigneeSelect,
  CRM_INVALIDATE,
  DuePicker,
  dueLabel,
  GO_FOR_MEASURED,
  SOLD_OUT,
  TaskRow,
  useAssignees,
  useLeadSources,
  userName,
} from "./shared";

export function LeadDetailModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { data: invoice } = useGet<Invoice>(`/invoices/${id}/`);
  const [metering, setMetering] = useState(false);
  const [another, setAnother] = useState(false);
  const canChange = can("call_center.change_invoice");

  const setSolution = useAction((solution: number) => api.post(`/invoices/${id}/solution/`, { solution }), {
    success: "Javob kodi saqlandi",
    invalidate: CRM_INVALIDATE,
  });

  if (!invoice)
    return (
      <Modal open onClose={onClose} title={`Ariza #${id}`} size="xl">
        <div className="flex h-40 items-center justify-center">
          <Spinner />
        </div>
      </Modal>
    );

  const served = invoice.solution === GO_FOR_MEASURED || invoice.solution === SOLD_OUT;

  return (
    <Modal open onClose={onClose} title={`Ariza #${invoice.id} · ${invoice.client.fio}`} size="xl">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* left: who / what / what next */}
        <div className="space-y-5">
          <LeadInfo invoice={invoice} canChange={canChange} />

          {canChange && !served && (
            <div>
              <div className="label">Qo'ng'iroq natijasi</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {meta?.solutions
                  .filter((s) => s.value !== SOLD_OUT)
                  .map((s) =>
                    s.value === GO_FOR_MEASURED ? (
                      can("metering.add_metering") && (
                        <button
                          key={s.value}
                          onClick={() => setMetering(true)}
                          className={cn(
                            "flex items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-medium ring-1 ring-inset transition hover:brightness-95",
                            TONES.ok.badge,
                          )}
                        >
                          <Ruler className="h-4 w-4" /> {s.label} → o'lchov yaratish
                        </button>
                      )
                    ) : (
                      <button
                        key={s.value}
                        disabled={setSolution.isPending}
                        onClick={() => setSolution.mutate(Number(s.value))}
                        className={cn(
                          "flex items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-medium ring-1 ring-inset transition hover:brightness-95",
                          TONES[s.tone].badge,
                          invoice.solution === s.value && "ring-2",
                        )}
                      >
                        <PhoneCall className="h-4 w-4" /> {s.label}
                      </button>
                    ),
                  )}
              </div>
            </div>
          )}

          <TasksBlock invoice={invoice} canChange={canChange} />
          <ClientHistory invoice={invoice} onAnother={can("call_center.add_invoice") ? () => setAnother(true) : undefined} />
        </div>

        {/* right: notes + history */}
        <div className="space-y-4">
          {canChange && <NoteBox invoiceId={invoice.id} />}
          <Timeline invoiceId={invoice.id} />
        </div>
      </div>

      {metering && (
        <MeteringCreateModal
          initial={{ client_phone: invoice.client.phone, client_fio: invoice.client.fio, invoice: invoice.id }}
          onClose={() => setMetering(false)}
          onCreated={onClose}
        />
      )}
      {another && (
        <LeadCreateModal
          initial={{ phone: invoice.client.phone, fio: invoice.client.fio, source: invoice.source }}
          onClose={() => setAnother(false)}
        />
      )}
    </Modal>
  );
}

/* ------------------------------------------------------------- info */

function LeadInfo({ invoice, canChange }: { invoice: Invoice; canChange: boolean }) {
  const sources = useLeadSources();
  const assignees = useAssignees(canChange);
  const update = useAction((body: { assigned_to?: number | null; source?: string }) => api.post(`/invoices/${invoice.id}/assign/`, body), {
    success: "Saqlandi",
    invalidate: CRM_INVALIDATE,
  });
  const assigneeKnown = !invoice.assigned_to || assignees.some((a) => a.id === invoice.assigned_to?.id);

  return (
    <KV
      items={[
        [
          "Mijoz",
          <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(invoice.client.phone)}`}>
            {invoice.client.fio}
          </Link>,
        ],
        ["Telefon", <PhoneLink value={invoice.client.phone} />],
        [
          "Manba",
          canChange ? (
            <Select
              className="h-8 w-auto min-w-[180px] py-0 text-sm"
              value={invoice.source ?? ""}
              disabled={update.isPending}
              onChange={(e) => e.target.value && update.mutate({ source: e.target.value })}
            >
              {!invoice.source && <option value="">— tanlang —</option>}
              {sources.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          ) : (
            invoice.source_label || "—"
          ),
        ],
        [
          "Mas'ul",
          canChange && assignees.length ? (
            <AssigneeSelect
              className="h-8 w-auto min-w-[180px] py-0 text-sm"
              value={assigneeKnown ? invoice.assigned_to?.id : ""}
              emptyLabel={assigneeKnown ? "— tanlang —" : userName(invoice.assigned_to)}
              assignees={assignees}
              disabled={update.isPending}
              onChange={(id) => id && update.mutate({ assigned_to: id })}
            />
          ) : (
            userName(invoice.assigned_to)
          ),
        ],
        ["Javob kodi", <SolutionBadge solution={invoice.solution} label={invoice.solution_label} />],
        ["Yaratilgan", `${dateTime(invoice.create_date)}${invoice.created_by ? " · " + invoice.created_by.name : ""}`],
        ...(invoice.metering_id
          ? ([
              [
                "O'lchov",
                <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/meterings/${invoice.metering_id}`}>
                  O'lchovni ochish →
                </Link>,
              ],
            ] as [string, JSX.Element][])
          : []),
      ]}
    />
  );
}

/* ------------------------------------------------------------ tasks */

function TasksBlock({ invoice, canChange }: { invoice: Invoice; canChange: boolean }) {
  const { data } = useGet<InvoiceTask[]>(`/invoices/${invoice.id}/tasks/`);
  const tasks = data ?? [];
  const open = tasks.filter((t) => !t.is_done).sort((a, b) => a.due_at.localeCompare(b.due_at));
  const done = tasks.filter((t) => t.is_done);
  const [adding, setAdding] = useState(false);
  const [showDone, setShowDone] = useState(false);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="label mb-0 flex items-center gap-1.5">
          <ClipboardList className="h-4 w-4" /> Vazifalar
        </div>
        {canChange && !adding && (
          <Button size="sm" variant="outline" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>
            Vazifa qo'shish
          </Button>
        )}
      </div>
      {invoice.needs_task && !adding && (
        <div className="mb-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300">
          Bu mijoz bo'yicha keyingi qadam belgilanmagan — qachon qo'ng'iroq qilishni qo'shing.
        </div>
      )}
      {adding && <TaskForm invoice={invoice} onDone={() => setAdding(false)} />}
      <div className="space-y-2">
        {open.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
        {!open.length && !invoice.needs_task && !adding && <p className="muted text-sm">Ochiq vazifa yo'q</p>}
        {done.length > 0 && (
          <button className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => setShowDone(!showDone)}>
            {showDone ? "Bajarilganlarni yashirish" : `Bajarilgan vazifalar · ${done.length}`}
          </button>
        )}
        {showDone && done.map((t) => <TaskRow key={t.id} task={t} />)}
      </div>
    </div>
  );
}

function TaskForm({ invoice, onDone }: { invoice: Invoice; onDone: () => void }) {
  const assignees = useAssignees();
  const [text, setText] = useState("Mijozga qo'ng'iroq qilish");
  const [due, setDue] = useState("");
  const [assignee, setAssignee] = useState<number | null>(invoice.assigned_to?.id ?? null);
  const create = useAction(
    () =>
      api.post(`/invoices/${invoice.id}/tasks/`, {
        text: text.trim(),
        due_at: due,
        ...(assignee ? { assigned_to: assignee } : {}),
      }),
    { success: "Vazifa qo'shildi", invalidate: CRM_INVALIDATE, onSuccess: onDone },
  );
  return (
    <div className="mb-2 space-y-3 rounded-xl border border-brand-200 bg-brand-50/40 p-3 dark:border-brand-500/30 dark:bg-brand-500/5">
      <Field label="Nima qilish kerak">
        <Input autoFocus value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <div>
        <span className="label">Qachon</span>
        <DuePicker value={due} onChange={setDue} />
      </div>
      {assignees.length > 0 && (
        <Field label="Kim bajaradi">
          <AssigneeSelect value={assignee} onChange={setAssignee} assignees={assignees} emptyLabel="Ariza mas'uli" />
        </Field>
      )}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Bekor qilish
        </Button>
        <Button size="sm" disabled={!due} loading={create.isPending} onClick={() => create.mutate()}>
          Qo'shish
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ notes */

function NoteBox({ invoiceId }: { invoiceId: number }) {
  const [text, setText] = useState("");
  const add = useAction(() => api.post(`/invoices/${invoiceId}/notes/`, { text: text.trim() }), {
    success: "Izoh qo'shildi",
    invalidate: CRM_INVALIDATE,
    onSuccess: () => setText(""),
  });
  return (
    <div className="space-y-2">
      <Textarea
        placeholder="Izoh yozing: nima gaplashildi, mijoz nima dedi…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) add.mutate();
        }}
      />
      <div className="flex justify-end">
        <Button size="sm" icon={<MessageSquare className="h-3.5 w-3.5" />} disabled={!text.trim()} loading={add.isPending} onClick={() => add.mutate()}>
          Izoh qo'shish
        </Button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------- timeline */

type Look = { icon: typeof MessageSquare; tone: keyof typeof TONES; title: string };

/** icon + headline of one history line; `kind` matters for type=note only */
function look(e: TimelineEntry): Look {
  if (e.type === "note") {
    if (e.kind === "solution") return { icon: PhoneCall, tone: "warn", title: "Javob kodi" };
    if (e.kind === "assigned") return { icon: UserRound, tone: "idle", title: "Mas'ul o'zgardi" };
    if (e.kind === "source") return { icon: Tag, tone: "idle", title: "Manba o'zgardi" };
    return { icon: MessageSquare, tone: "info", title: "Izoh" };
  }
  if (e.type === "created") return { icon: Sparkles, tone: "primary", title: "Ariza yaratildi" };
  if (e.type === "task_created") return { icon: ClipboardList, tone: "idle", title: "Vazifa qo'yildi" };
  if (e.type === "task_done") return { icon: CheckCircle2, tone: "ok", title: "Vazifa bajarildi" };
  if (e.type === "metering") return { icon: Ruler, tone: "ok", title: "O'lchov yaratildi" };
  if (e.type === "order") return { icon: Package, tone: "ok", title: "Buyurtma" };
  return { icon: ArrowRightLeft, tone: "idle", title: e.type };
}

function Timeline({ invoiceId }: { invoiceId: number }) {
  const { data, isLoading } = useGet<TimelineEntry[]>(`/invoices/${invoiceId}/timeline/`);
  const entries = data ?? [];
  return (
    <div>
      <div className="label">Tarix</div>
      {isLoading && <Spinner />}
      {!isLoading && !entries.length && <Empty title="Hali hech narsa yo'q" />}
      <ol className="relative ml-2.5 space-y-3 border-l border-slate-200 pl-5 dark:border-slate-700">
        {entries.map((e, i) => {
          const l = look(e);
          const Icon = l.icon;
          const isNote = e.type === "note" && (e.kind === "note" || !e.kind);
          const href = e.link ? (e.link.kind === "order" ? `/orders/${e.link.id}` : `/meterings/${e.link.id}`) : null;
          return (
            <li key={i} className="relative">
              <span
                className={cn(
                  "absolute -left-[31px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white dark:ring-slate-900",
                  TONES[l.tone].soft,
                  TONES[l.tone].text,
                )}
              >
                <Icon className="h-3 w-3" />
              </span>
              <div className="muted text-xs">
                <span className="font-medium text-slate-700 dark:text-slate-200">{l.title}</span> · {dateTime(e.at)}
                {e.author && ` · ${e.author.name}`}
              </div>
              {e.task && e.type !== "note" && (
                <div className="text-sm">
                  {e.task.text}
                  {e.type === "task_created" && <span className="muted text-xs"> — {dueLabel(e.task.due_at)}</span>}
                </div>
              )}
              {e.text && !(e.task && e.type === "task_created") && (
                <div
                  className={cn(
                    "whitespace-pre-line break-words text-sm",
                    (isNote || e.type === "task_done") && "mt-0.5 rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-slate-800/60",
                  )}
                >
                  {href ? (
                    <Link className="text-brand-700 hover:underline dark:text-brand-300" to={href}>
                      {e.text} →
                    </Link>
                  ) : (
                    e.text
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* --------------------------------------------------- client history */

function ClientHistory({ invoice, onAnother }: { invoice: Invoice; onAnother?: () => void }) {
  const { data } = useGet<{ invoices: Invoice[]; meterings: Metering[]; orders: Order[] }>(
    `/clients/${encodeURIComponent(invoice.client.phone)}/related/`,
  );
  const others = data?.invoices.filter((i) => i.id !== invoice.id) ?? [];
  const meterings = data?.meterings ?? [];
  const orders = data?.orders ?? [];
  const empty = !others.length && !meterings.length && !orders.length;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="label mb-0">Mijoz tarixi</div>
        {onAnother && (
          <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={onAnother}>
            Shu mijoz uchun yangi ariza
          </Button>
        )}
      </div>
      {data && empty && <p className="muted text-sm">Boshqa ariza, o'lchov yoki buyurtma yo'q</p>}
      <div className="space-y-1.5 text-sm">
        {orders.map((o) => (
          <Link key={`o${o.id}`} to={`/orders/${o.id}`} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50">
            <span>Buyurtma №{o.order_number}</span>
            <OrderStatusBadge status={o.status} label={o.status_label} />
          </Link>
        ))}
        {meterings.map((m) => (
          <Link key={`m${m.id}`} to={`/meterings/${m.id}`} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50">
            <span className="truncate">O'lchov · {dateTime(m.date_time)}</span>
            <MeteringStatusBadge status={m.status} label={m.status_label} />
          </Link>
        ))}
        {others.map((i) => (
          <Link key={`i${i.id}`} to={`/call-center?open=${i.id}`} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50">
            <span className="truncate">
              Ariza #{i.id} · {dateTime(i.create_date)}
            </span>
            <SolutionBadge solution={i.solution} label={i.solution_label} />
          </Link>
        ))}
      </div>
    </div>
  );
}
