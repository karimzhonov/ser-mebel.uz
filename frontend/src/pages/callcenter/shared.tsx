import { useState } from "react";
import { AlarmClock, BellOff, Check as CheckIcon, Clock, Sunrise, Timer } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useMeta } from "@/api/hooks";
import type { Assignee, InvoiceTask, UserRef } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PhoneLink } from "@/components/domain";
import { Badge, Button, Input, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { CompleteTaskDialog } from "./CompleteTaskDialog";

/** Query keys every CRM write refreshes (useAction matches them by substring). */
export const CRM_INVALIDATE = ["invoices", "invoice-tasks", "dashboard"];

/** Solutions a lead can be moved to by hand: «Сотилди» comes only from an order. */
export const SOLD_OUT = 6;
export const GO_FOR_MEASURED = 5;

/* ----------------------------------------------------- task outcomes */

/** The next column a lead goes to when a task is done (POST /invoice-tasks/{id}/done/ `outcome`). */
export type TaskOutcome =
  | "re_phone"
  | "given_info"
  | "given_location"
  | "go_for_measured"
  | "price_problem"
  | "dont_need"
  | "declined"
  | "keep";

/** outcome key → solution value (call_center.constants.SolutionChoice) */
export const OUTCOME_SOLUTION: Record<Exclude<TaskOutcome, "keep">, number> = {
  re_phone: 1,
  given_info: 2,
  given_location: 3,
  go_for_measured: 5,
  price_problem: 4,
  dont_need: 0,
  declined: -1,
};

/** Outcomes that close the lead (and the lead's other open tasks). */
export const CLOSING_OUTCOMES: TaskOutcome[] = ["price_problem", "dont_need", "declined"];
/** Outcomes where a next call / reminder may be set. */
export const FOLLOW_UP_OUTCOMES: TaskOutcome[] = ["re_phone", "given_info", "given_location"];

/** sold_out, go_for_measured, price_problem, dont_need, declined — mirrors services.CLOSED_SOLUTIONS */
const CLOSED_SOLUTIONS = [6, 5, 4, 0, -1];

/** Mirror of call_center.services.task_outcomes — only for the UI, the server decides. */
export function taskOutcomes(task: InvoiceTask, can: (perm: string) => boolean): TaskOutcome[] {
  const sol = task.invoice.solution;
  if ((sol !== null && CLOSED_SOLUTIONS.includes(sol)) || !can("call_center.change_invoice")) return ["keep"];
  const out: TaskOutcome[] = ["re_phone", "given_info", "given_location"];
  if (can("metering.add_metering")) out.push("go_for_measured");
  out.push("price_problem", "dont_need", "declined");
  return out;
}

/* ------------------------------------------------------------- dates */

function pad(n: number) {
  return String(n).padStart(2, "0");
}

/** naive local "YYYY-MM-DDTHH:MM" — the API works in local time (USE_TZ=False) */
export function localISO(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Same presets as call_center.services.due_preset. */
export function presetDue(preset: "1h" | "today" | "tomorrow", now = new Date()): string {
  const d = new Date(now);
  d.setSeconds(0, 0);
  if (preset === "1h") d.setHours(d.getHours() + 1);
  else if (preset === "today") {
    if (now.getHours() < 17) d.setHours(18, 0);
    else d.setHours(d.getHours() + 1);
  } else {
    d.setDate(d.getDate() + 1);
    d.setHours(10, 0);
  }
  return localISO(d);
}

function parseLocal(value: string) {
  return new Date(value.length === 10 ? value + "T00:00:00" : value);
}

export function isOverdue(due: string | null | undefined) {
  return !!due && parseLocal(due).getTime() < Date.now();
}

/** "Bugun 14:30", "Ertaga 10:00", "05.11 10:00", "Kecha 18:00" */
export function dueLabel(due: string | null | undefined) {
  if (!due) return "—";
  const d = parseLocal(due);
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const t = new Date();
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
  const diff = Math.round((day - today) / 86400000);
  if (diff === 0) return `Bugun ${time}`;
  if (diff === 1) return `Ertaga ${time}`;
  if (diff === -1) return `Kecha ${time}`;
  const year = d.getFullYear() !== t.getFullYear() ? `.${d.getFullYear()}` : "";
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}${year} ${time}`;
}

export function DueText({ due, className }: { due: string | null | undefined; className?: string }) {
  const late = isOverdue(due);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap tabular-nums",
        late ? "font-semibold text-rose-600 dark:text-rose-400" : "text-slate-600 dark:text-slate-300",
        className,
      )}
      title={late ? "Muddati o'tgan" : undefined}
    >
      <Clock className="h-3.5 w-3.5" />
      {dueLabel(due)}
    </span>
  );
}

export function NoTaskBadge() {
  return (
    <Badge tone="warn" className="whitespace-nowrap">
      Vazifa yo'q
    </Badge>
  );
}

export function SourceBadge({ label }: { label: string | null | undefined }) {
  if (!label) return null;
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
      {label}
    </span>
  );
}

export function userName(u: UserRef | null | undefined, fallback = "—") {
  return u?.name || fallback;
}

/* ------------------------------------------------------------ hooks */

export function useAssignees(enabled = true) {
  const { can } = useAuth();
  const q = useGet<Assignee[]>(enabled && can("call_center.view_invoice") ? "/invoices/assignees/" : null);
  return q.data ?? [];
}

export function useLeadSources() {
  const { data: meta } = useMeta();
  return meta?.lead_sources ?? [];
}

/** Server rule (can_manage_task): view_invoice + (superuser, assignee, creator or a call-center manager). */
export function useCanManageTask() {
  const { user, can } = useAuth();
  return (t: InvoiceTask) => {
    if (!user || !can("call_center.view_invoice")) return false;
    if (user.is_superuser || can("call_center.manage_invoice")) return true;
    return t.assigned?.id === user.id || t.created_by?.id === user.id;
  };
}

export function AssigneeSelect({
  value,
  onChange,
  assignees,
  allowEmpty,
  emptyLabel = "—",
  className,
  disabled,
}: {
  value: number | "" | null | undefined;
  onChange: (id: number | null) => void;
  assignees: Assignee[];
  allowEmpty?: boolean;
  emptyLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <Select
      className={className}
      disabled={disabled}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      {(allowEmpty || !value) && <option value="">{emptyLabel}</option>}
      {assignees.map((a) => (
        <option key={a.id} value={a.id}>
          {a.name}
          {a.has_telegram ? "" : " · Telegram ulanmagan"}
        </option>
      ))}
    </Select>
  );
}

/* ------------------------------------------------------ due picker */

/** Bugun / Ertaga / exact time — returns a naive local datetime string (or ""). */
export function DuePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [mode, setMode] = useState<"today" | "tomorrow" | "custom" | "">(value ? "custom" : "");
  const pick = (m: "today" | "tomorrow") => {
    setMode(m);
    onChange(presetDue(m));
  };
  const btn = (active: boolean) =>
    cn(
      "inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-sm font-medium transition",
      active
        ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200"
        : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={btn(mode === "today")} onClick={() => pick("today")}>
        <AlarmClock className="h-4 w-4" /> Bugun
      </button>
      <button type="button" className={btn(mode === "tomorrow")} onClick={() => pick("tomorrow")}>
        <Sunrise className="h-4 w-4" /> Ertaga
      </button>
      <Input
        type="datetime-local"
        className="h-9 w-auto min-w-[200px] flex-1"
        value={value}
        onChange={(e) => {
          setMode("custom");
          onChange(e.target.value);
        }}
      />
    </div>
  );
}

export type NextTaskBody = { preset: "1h" | "today" | "tomorrow" } | { due_at: string };

/** Next call for a finished task: one-tap presets (resolved time shown), exact time, optional «Eslatmasiz».
 * `value` null = nothing chosen yet, "none" = no reminder. */
export function NextCallPicker({
  value,
  onChange,
  allowNone,
}: {
  value: NextTaskBody | "none" | null;
  onChange: (v: NextTaskBody | "none" | null) => void;
  allowNone?: boolean;
}) {
  const preset = value && value !== "none" && "preset" in value ? value.preset : null;
  const custom = value && value !== "none" && "due_at" in value ? value.due_at : "";
  const btn = (active: boolean) =>
    cn(
      "flex min-h-[52px] flex-col items-start justify-center rounded-xl border px-3 py-1.5 text-left text-sm font-semibold transition",
      active
        ? "border-brand-500 bg-brand-50 text-brand-700 ring-1 ring-brand-500 dark:bg-brand-500/15 dark:text-brand-200"
        : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
    );
  const presets: { key: "1h" | "today" | "tomorrow"; label: string; icon: typeof Clock }[] = [
    { key: "1h", label: "+1 soat", icon: Timer },
    { key: "today", label: "Bugun", icon: AlarmClock },
    { key: "tomorrow", label: "Ertaga", icon: Sunrise },
  ];
  return (
    <div className="space-y-2">
      <div className={cn("grid gap-2", allowNone ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3")}>
        {presets.map((p) => (
          <button key={p.key} type="button" className={btn(preset === p.key)} onClick={() => onChange({ preset: p.key })}>
            <span className="inline-flex items-center gap-1.5">
              <p.icon className="h-4 w-4" /> {p.label}
            </span>
            <span className="text-xs font-normal opacity-75 tabular-nums">{dueLabel(presetDue(p.key))}</span>
          </button>
        ))}
        {allowNone && (
          <button type="button" className={btn(value === "none")} onClick={() => onChange("none")}>
            <span className="inline-flex items-center gap-1.5">
              <BellOff className="h-4 w-4" /> Eslatmasiz
            </span>
            <span className="text-xs font-normal opacity-75">vazifa qo'yilmaydi</span>
          </button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="muted whitespace-nowrap text-xs">Aniq vaqt:</span>
        <Input
          type="datetime-local"
          className={cn("h-9 flex-1", custom && "border-brand-500 ring-1 ring-brand-500")}
          value={custom}
          onChange={(e) => onChange(e.target.value ? { due_at: e.target.value } : allowNone ? "none" : null)}
        />
      </div>
    </div>
  );
}

/* --------------------------------------------------------- task row */

/** One task with its actions: done (opens CompleteTaskDialog — next stage + next call), +1 soat, ertaga, another time. */
export function TaskRow({
  task,
  showClient,
  onOpen,
}: {
  task: InvoiceTask;
  showClient?: boolean;
  onOpen?: () => void;
}) {
  const canManage = useCanManageTask()(task);
  const [mode, setMode] = useState<null | "move">(null);
  const [completing, setCompleting] = useState(false);
  const [due, setDue] = useState("");
  const reset = () => {
    setMode(null);
    setDue("");
  };
  const move = useAction(
    (body: { preset: string } | { due_at: string }) => api.post(`/invoice-tasks/${task.id}/reschedule/`, body),
    { success: "Vazifa ko'chirildi", invalidate: CRM_INVALIDATE, onSuccess: reset },
  );
  const assignee = task.assigned;
  const late = !task.is_done && isOverdue(task.due_at);

  return (
    <div
      className={cn(
        "rounded-xl border p-3 text-sm",
        task.is_done
          ? "border-slate-100 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/40"
          : late
            ? "border-rose-200 bg-rose-50/60 dark:border-rose-500/30 dark:bg-rose-500/10"
            : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div
          className={cn("min-w-0 flex-1", onOpen && "cursor-pointer")}
          onClick={onOpen}
          role={onOpen ? "button" : undefined}
        >
          {showClient && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
              <span className="truncate font-semibold text-slate-900 dark:text-white">
                {task.invoice.client.fio} <span className="muted font-normal">· #{task.invoice.id}</span>
              </span>
              <span className="text-xs" onClick={(e) => e.stopPropagation()}>
                <PhoneLink value={task.invoice.client.phone} />
              </span>
              <SourceBadge label={task.invoice.source_label} />
            </div>
          )}
          <div className={cn("break-words", task.is_done && "muted line-through")}>{task.text}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {task.is_done ? (
              <span className="muted inline-flex items-center gap-1">
                <CheckIcon className="h-3.5 w-3.5 text-emerald-600" /> {dueLabel(task.done_at)}
              </span>
            ) : (
              <DueText due={task.due_at} />
            )}
            {assignee && <span className="muted">{assignee.name}</span>}
          </div>
        </div>
        {!task.is_done && canManage && !mode && (
          <div className="flex flex-wrap gap-1">
            <Button size="sm" variant="success" icon={<CheckIcon className="h-3.5 w-3.5" />} onClick={() => setCompleting(true)}>
              Bajarildi
            </Button>
            <Button size="sm" variant="outline" loading={move.isPending} onClick={() => move.mutate({ preset: "1h" })}>
              +1 soat
            </Button>
            <Button size="sm" variant="outline" onClick={() => move.mutate({ preset: "tomorrow" })} disabled={move.isPending}>
              Ertaga
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("move")}>
              Boshqa vaqt
            </Button>
          </div>
        )}
      </div>
      {mode === "move" && (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <Input type="datetime-local" autoFocus value={due} onChange={(e) => setDue(e.target.value)} />
          <div className="flex gap-1">
            <Button size="md" loading={move.isPending} disabled={!due} onClick={() => move.mutate({ due_at: due })}>
              Ko'chirish
            </Button>
            <Button size="md" variant="ghost" onClick={reset}>
              Bekor
            </Button>
          </div>
        </div>
      )}
      {completing && <CompleteTaskDialog task={task} onClose={() => setCompleting(false)} />}
    </div>
  );
}
