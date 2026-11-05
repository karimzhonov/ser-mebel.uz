import { useState, type ReactNode } from "react";
import { CalendarClock } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { MeteringAssignees, OfferAnswerKind, OfferKind, OfferStage, PersonRef, Tone } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { cn } from "@/lib/cn";
import { toLocalInput } from "@/lib/format";
import { dayLabel, METERING_INVALIDATE, personName, timeOnly } from "../meterings/actions";

/** everything a design / price change can show up in (/designs/agenda/, /meterings/presentations/, the lead card …) */
export const OFFER_INVALIDATE = METERING_INVALIDATE;

export const OFFER_PATH: Record<OfferKind, "designs" | "prices"> = { design: "designs", price: "prices" };
export const OFFER_TITLE: Record<OfferKind, string> = { design: "Dizayn", price: "Narx hisoblash" };
/** who works on it */
export const ASSIGNEE_LABEL: Record<OfferKind, string> = { design: "Dizayner", price: "Narx hisoblovchi" };

export const ARCHIVE_STAGES = "approved,declined,cancelled";

export const STAGE_LABEL: Record<OfferStage, string> = {
  waiting: "Dizayn kutilmoqda",
  work: "Ishda",
  review: "Mijozda — javob kutilmoqda",
  approved: "Tasdiqlandi",
  declined: "Rad etildi",
  cancelled: "Bekor",
};

const STAGE_TONE: Record<OfferStage, Tone> = {
  waiting: "idle",
  work: "warn",
  review: "info",
  approved: "ok",
  declined: "danger",
  cancelled: "idle",
};

export const CLIENT_RESULT_LABEL: Record<string, string> = {
  agreed: "Mijoz rozi",
  design_declined: "Dizaynni rad etdi",
  price_declined: "Narxi qoniqtirmadi",
};

export function OfferStageBadge({ stage, label, overdue }: { stage?: OfferStage | null; label?: string; overdue?: boolean }) {
  if (!stage) return null;
  if (overdue && stage === "work") return <Badge tone="danger">Muddati o'tdi</Badge>;
  return <Badge tone={STAGE_TONE[stage] ?? "idle"}>{label || STAGE_LABEL[stage] || stage}</Badge>;
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "Bugun 18:00" / "Ertaga 18:00" / "Payshanba, 05.11 · 18:00" / "Muddat yo'q" */
export function dueText(value: string | null | undefined) {
  if (!value) return "Muddat yo'q";
  const d = new Date(value);
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(d, now)) return `Bugun ${timeOnly(value)}`;
  if (sameDay(d, tomorrow)) return `Ertaga ${timeOnly(value)}`;
  return `${dayLabel(value)} · ${timeOnly(value)}`;
}

/** The deadline, red when it passed. */
export function DueLabel({ value, overdue, className }: { value: string | null | undefined; overdue?: boolean; className?: string }) {
  return (
    <span className={cn("whitespace-nowrap font-semibold tabular-nums", overdue ? "text-rose-600 dark:text-rose-400" : !value && "muted", className)}>
      {overdue && "⚠️ "}
      {dueText(value)}
    </span>
  );
}

/** a Date as "2026-11-05T18:00" for <input type="datetime-local"> */
function localInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** max(current day, today) + n days, keeping the current clock time (else 18:00) — like services.shift_due */
function shifted(current: string | null | undefined, days: number) {
  const now = new Date();
  const base = current ? new Date(current) : null;
  const d = base && base > now ? new Date(base) : new Date(now);
  d.setDate(d.getDate() + days);
  if (base) d.setHours(base.getHours(), base.getMinutes(), 0, 0);
  else d.setHours(18, 0, 0, 0);
  return d;
}

export function useAssignees(enabled = true) {
  return useGet<MeteringAssignees>(enabled ? "/meterings/assignees/" : null);
}

/** «🕒 Muddatni o'zgartirish» — POST /{designs|prices}/{id}/due/ {due_at} */
export function DueModal({ kind, id, dueAt, onClose }: { kind: OfferKind; id: number; dueAt: string | null; onClose: () => void }) {
  const [value, setValue] = useState(dueAt ? toLocalInput(dueAt) : localInput(shifted(null, 1)));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(() => api.post(`/${OFFER_PATH[kind]}/${id}/due/`, { due_at: value }), {
    success: "Muddat o'zgartirildi",
    invalidate: OFFER_INVALIDATE,
    onSuccess: onClose,
  });
  const past = !!value && new Date(value).getTime() <= Date.now();
  const error = errors.due ?? errors.due_at;
  return (
    <Modal
      open
      onClose={onClose}
      title="Muddatni o'zgartirish"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button size="lg" disabled={!value || past} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Saqlash
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">Hozirgi muddat: <b className="text-slate-700 dark:text-slate-200">{dueText(dueAt)}</b></p>
      <div className="mb-3 grid grid-cols-3 gap-2">
        {[1, 2, 3].map((n) => (
          <Button key={n} size="lg" variant="secondary" onClick={() => setValue(localInput(shifted(dueAt, n)))}>
            +{n} kun
          </Button>
        ))}
      </div>
      <Field label="Yangi muddat" error={error ?? (past ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}>
        <Input className="h-12 text-base" type="datetime-local" required value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  );
}

/** «Muddatni o'zgartirish» button + its modal */
export function DueButton({ kind, id, dueAt, big, className }: { kind: OfferKind; id: number; dueAt: string | null; big?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size={big ? "lg" : "sm"}
        variant="outline"
        className={className}
        icon={<CalendarClock className={big ? "h-5 w-5" : "h-4 w-4"} />}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        Muddatni o'zgartirish
      </Button>
      {open && <DueModal kind={kind} id={id} dueAt={dueAt} onClose={() => setOpen(false)} />}
    </>
  );
}

type AnswerSpec = { value: OfferAnswerKind; label: string; variant: "success" | "outline" | "danger"; title: string; hint: string; comment: "none" | "optional" | "required"; due?: boolean };

export const ANSWERS: Record<OfferKind, AnswerSpec[]> = {
  design: [
    { value: "approved", label: "✅ Tasdiqladi", variant: "success", title: "Mijoz dizaynni tasdiqladimi?", hint: "Narx hisoblovchiga vazifa boradi (agar narx ham kerak bo'lsa).", comment: "optional" },
    { value: "changes", label: "✏️ O'zgartirish kerak", variant: "outline", title: "Nima o'zgarishi kerak?", hint: "Dizaynerga yangi muddat bilan qaytadi.", comment: "required", due: true },
    { value: "declined", label: "❌ Rad etdi", variant: "danger", title: "Mijoz dizaynni rad etdimi?", hint: "Ariza «Rad etdi» bo'ladi, narx hisoblash bekor qilinadi, zamer arxivga o'tadi.", comment: "required" },
  ],
  price: [
    { value: "approved", label: "✅ Rozi", variant: "success", title: "Mijoz narxga rozimi?", hint: "Buyurtma rasmiylashtirishga tayyor bo'ladi.", comment: "optional" },
    { value: "recalc", label: "🔁 Qayta hisoblash", variant: "outline", title: "Nimani qayta hisoblash kerak?", hint: "Narx hisoblovchiga yangi muddat bilan qaytadi.", comment: "required", due: true },
    { value: "declined", label: "❌ Narxi qoniqtirmadi", variant: "danger", title: "Narx mijozni qoniqtirmadimi?", hint: "Ariza «Narx muammosi»ga o'tadi, zamer arxivga o'tadi.", comment: "required" },
  ],
};

/** The manager records the client's answer — POST /{designs|prices}/{id}/answer/ {answer, comment?, due_at?} */
export function AnswerDialog({ kind, id, answer, client, onClose }: { kind: OfferKind; id: number; answer: OfferAnswerKind; client?: string; onClose: () => void }) {
  const spec = ANSWERS[kind].find((a) => a.value === answer) ?? ANSWERS[kind][0];
  const [comment, setComment] = useState("");
  const [due, setDue] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api
        .post<{ closed_tasks?: number }>(`/${OFFER_PATH[kind]}/${id}/answer/`, {
          answer,
          comment: comment.trim(),
          ...(spec.due && due ? { due_at: due } : {}),
        })
        .then((r) => r.data),
    {
      invalidate: OFFER_INVALIDATE,
      onSuccess: (r) => {
        const closed = r?.closed_tasks ? ` · ${r.closed_tasks} ta vazifa yopildi` : "";
        toast.success(`Javob yozildi${closed}`);
        onClose();
      },
    },
  );
  const ok = spec.comment !== "required" || comment.trim().length >= 3;
  const past = !!due && new Date(due).getTime() <= Date.now();
  return (
    <Modal
      open
      onClose={onClose}
      title={spec.title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Orqaga</Button>
          <Button
            size="lg"
            variant={spec.variant === "outline" ? "primary" : spec.variant}
            disabled={!ok || past}
            loading={save.isPending}
            onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            {spec.label}
          </Button>
        </>
      }
    >
      {client && <p className="mb-2 text-sm font-semibold">{client}</p>}
      <p className="muted mb-3 text-sm">{spec.hint}</p>
      {spec.comment !== "none" && (
        <Field
          label={spec.value === "declined" ? "Sababi" : spec.comment === "required" ? "Izoh" : "Izoh (ixtiyoriy)"}
          error={errors.comment ?? errors.answer}
        >
          <Textarea
            autoFocus={spec.comment === "required"}
            value={comment}
            placeholder={spec.value === "declined" ? "Masalan: boshqa joydan buyurtma qildi…" : spec.comment === "required" ? "Mijoz nima dedi, nima o'zgarishi kerak…" : ""}
            onChange={(e) => setComment(e.target.value)}
          />
        </Field>
      )}
      {spec.due && (
        <Field
          className="mt-3"
          label="Yangi muddat (ixtiyoriy)"
          hint="Bo'sh qolsa — standart muddat (ertaga 18:00)"
          error={errors.due ?? errors.due_at ?? (past ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}
        >
          <Input className="h-12 text-base" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>
      )}
      {errors.non_field_errors && <p className="mt-2 text-sm text-rose-600">{errors.non_field_errors}</p>}
    </Modal>
  );
}

/** The three answer buttons (design: Tasdiqladi / O'zgartirish / Rad etdi; price: Rozi / Qayta hisoblash / Qoniqtirmadi). */
export function AnswerButtons({ kind, id, client, big, className }: { kind: OfferKind; id: number; client?: string; big?: boolean; className?: string }) {
  const [answer, setAnswer] = useState<OfferAnswerKind | null>(null);
  return (
    <div className={cn("flex flex-wrap gap-2", className)} onClick={(e) => e.stopPropagation()}>
      {ANSWERS[kind].map((a) => (
        <Button
          key={a.value}
          size={big ? "lg" : "md"}
          variant={a.variant}
          className={cn(big && "flex-1 basis-full sm:basis-auto")}
          onClick={() => setAnswer(a.value)}
        >
          {a.label}
        </Button>
      ))}
      {answer && <AnswerDialog kind={kind} id={id} answer={answer} client={client} onClose={() => setAnswer(null)} />}
    </div>
  );
}

/** Designer / pricer select (POST /designs/{id}/designer/ or /prices/{id}/pricer/ {user}). */
export function ReassignSelect({ kind, id, current }: { kind: OfferKind; id: number; current: PersonRef | null | undefined }) {
  const people = useAssignees();
  const items = (kind === "design" ? people.data?.designers : people.data?.pricers) ?? [];
  const known = !current || items.some((u) => u.id === current.id);
  const save = useAction((user: number) => api.post(`/${OFFER_PATH[kind]}/${id}/${kind === "design" ? "designer" : "pricer"}/`, { user }), {
    success: `${ASSIGNEE_LABEL[kind]} almashtirildi`,
    invalidate: OFFER_INVALIDATE,
  });
  if (!items.length) return <>{personName(current, "tayinlanmagan")}</>;
  return (
    <Select
      className="h-9 w-auto min-w-[180px] py-0 text-sm"
      value={known ? current?.id ?? "" : ""}
      disabled={save.isPending}
      onChange={(e) => e.target.value && save.mutate(Number(e.target.value))}
    >
      {(!current || !known) && <option value="">{current ? personName(current) : "— tanlang —"}</option>}
      {items.map((u) => (
        <option key={u.id} value={u.id}>{personName(u)}</option>
      ))}
    </Select>
  );
}

/** Mirrors services.can_work_design / can_work_price for list rows that come without `actions`. */
export function useCanWork(kind: OfferKind) {
  const { user, can } = useAuth();
  return (assignee: PersonRef | null | undefined) =>
    can("metering.manage_metering") ||
    (!!assignee && assignee.id === user?.id) ||
    (!assignee && can(kind === "design" ? "oauth.user_design" : "price.change_price"));
}

/** answers history (detail pages) */
export function AnswersHistory({ kind, answers }: { kind: OfferKind; answers: { id: number; round: number; answer: OfferAnswerKind; answer_label?: string; comment: string; due_at: string | null; by: PersonRef | null; created_at: string }[] }) {
  const label = (a: OfferAnswerKind) => ANSWERS[kind].find((x) => x.value === a)?.label ?? a;
  return (
    <ol className="space-y-3 text-sm">
      {answers.map((a) => (
        <li key={a.id} className="rounded-xl border border-slate-200 px-3 py-2 dark:border-slate-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{a.answer_label || label(a.answer)}</span>
            <span className="muted text-xs">{a.round}-raund</span>
          </div>
          {a.comment && <p className="mt-1 whitespace-pre-line break-words">{a.comment}</p>}
          <div className="muted mt-1 text-xs">
            {dayLabel(a.created_at)} · {timeOnly(a.created_at)}
            {a.by && ` · ${personName(a.by)}`}
            {a.due_at && ` · yangi muddat: ${dueText(a.due_at)}`}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function Hint({ children, tone = "warn" }: { children: ReactNode; tone?: "warn" | "danger" | "info" }) {
  return (
    <div
      className={cn(
        "rounded-xl px-4 py-3 text-sm font-medium ring-1 ring-inset",
        tone === "danger" && "bg-rose-50 text-rose-700 ring-rose-600/15 dark:bg-rose-500/10 dark:text-rose-300",
        tone === "warn" && "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-200",
        tone === "info" && "bg-sky-50 text-sky-800 ring-sky-600/20 dark:bg-sky-500/10 dark:text-sky-200",
      )}
    >
      {children}
    </div>
  );
}
