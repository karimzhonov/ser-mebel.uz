import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Check as CheckIcon, Lock, PhoneCall, Ruler } from "lucide-react";
import { api, errorMessage } from "@/api/client";
import { useAction, useMeta } from "@/api/hooks";
import type { InvoiceTask, TaskDoneResult } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button, Modal, Textarea, TONES } from "@/components/ui";
import { cn } from "@/lib/cn";
import { MeteringCreateModal } from "../Meterings";
import {
  CLOSING_OUTCOMES,
  CRM_INVALIDATE,
  dueLabel,
  FOLLOW_UP_OUTCOMES,
  NextCallPicker,
  type NextTaskBody,
  OUTCOME_SOLUTION,
  type TaskOutcome,
  taskOutcomes,
} from "./shared";

type DoneBody = { note?: string; outcome: TaskOutcome; next_task?: NextTaskBody };

/**
 * «Bajarildi» → which column the lead goes to next. re_phone needs the next call time,
 * given_info / given_location may set one, closing outcomes close the lead (and its other
 * open tasks), go_for_measured creates an O'lchov first. The server (task_outcomes) decides.
 */
export function CompleteTaskDialog({ task, onClose }: { task: InvoiceTask; onClose: () => void }) {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const qc = useQueryClient();
  const outcomes = taskOutcomes(task, can);
  // the metering was created (lead is now «Замерга борилади») but closing the task failed —
  // the cached task.invoice.solution is stale, so only «keep» (retry closing the task) is offered
  const [meteringCreated, setMeteringCreated] = useState(false);
  const keepOnly = meteringCreated || (outcomes.length === 1 && outcomes[0] === "keep");
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState<TaskOutcome | null>(keepOnly ? "keep" : null);
  const [next, setNext] = useState<NextTaskBody | "none" | null>(null);
  const [metering, setMetering] = useState(false);

  const done = useAction((body: DoneBody) => api.post<TaskDoneResult>(`/invoice-tasks/${task.id}/done/`, body).then((r) => r.data), {
    invalidate: [...CRM_INVALIDATE, "meterings"],
    onSuccess: (r) => {
      const parts = ["Vazifa bajarildi"];
      if (r.next_task) parts.push(`keyingi qo'ng'iroq: ${dueLabel(r.next_task.due_at)}`);
      if (r.closed_tasks) parts.push(`${r.closed_tasks} ta vazifa yopildi`);
      toast.success(parts.join(" · "));
      onClose();
    },
  });

  const pick = (o: TaskOutcome) => {
    setOutcome(o);
    done.reset();
    // re_phone: the time must be picked; given_*: «Eslatmasiz» by default
    setNext(o === "given_info" || o === "given_location" ? "none" : null);
  };

  const needsTime = outcome === "re_phone";
  const followUp = !!outcome && FOLLOW_UP_OUTCOMES.includes(outcome);
  const closing = !!outcome && CLOSING_OUTCOMES.includes(outcome);
  // owner's rule: a call result needs a comment (backend: complete_task); «keep» only closes the task
  const needsNote = !!outcome && outcome !== "keep";
  const ready =
    !!outcome &&
    outcome !== "go_for_measured" &&
    (!needsNote || !!note.trim()) &&
    (!needsTime || (next !== null && next !== "none"));

  const submit = (o: TaskOutcome = outcome!) => {
    const body: DoneBody = { outcome: o };
    if (note.trim()) body.note = note.trim();
    if (FOLLOW_UP_OUTCOMES.includes(o) && next && next !== "none") body.next_task = next;
    done.mutate(body, {
      // the lead may have changed meanwhile (or the metering already moved it) — refetch so
      // the board/agenda and this dialog's chips stop offering what the server rejects
      onError: () =>
        [...CRM_INVALIDATE, "meterings"].forEach((key) =>
          qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes(key) }),
        ),
    });
  };

  if (metering)
    return (
      <MeteringCreateModal
        initial={{
          client_phone: task.invoice.client.phone,
          client_fio: task.invoice.client.fio,
          invoice: task.invoice.id,
          address: task.invoice.address ?? "",
          invoiceHasLocation: !!task.invoice.has_point,
        }}
        onClose={() => setMetering(false)}
        // the metering moved the lead to «Замерга борилади» — now just close the task
        onCreated={() => {
          setMeteringCreated(true);
          setOutcome("keep");
          setNext(null);
          submit("keep");
        }}
      />
    );

  const label = (o: TaskOutcome) => meta?.solutions.find((s) => o !== "keep" && s.value === OUTCOME_SOLUTION[o]);
  const current = task.invoice.solution;

  return (
    <Modal
      open
      onClose={onClose}
      title={`Vazifa bajarildi · ${task.invoice.client.fio} #${task.invoice.id}`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          {outcome === "go_for_measured" ? (
            <Button variant="success" icon={<Ruler className="h-4 w-4" />} onClick={() => setMetering(true)}>
              O'lchov yaratish
            </Button>
          ) : (
            <Button
              variant={closing ? "danger" : "success"}
              icon={<CheckIcon className="h-4 w-4" />}
              disabled={!ready}
              loading={done.isPending}
              onClick={() => submit()}
            >
              {closing ? "Yopish" : "Saqlash"}
            </Button>
          )}
        </>
      }
    >
      <div
        className="space-y-4"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && ready && !done.isPending) submit();
        }}
      >
        <div className="muted text-sm">{task.text}</div>

        <Textarea
          autoFocus
          rows={2}
          placeholder={needsNote ? "Izoh (majburiy): mijoz bilan nima gaplashildi?" : "Izoh (ixtiyoriy): nima gaplashildi?"}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />

        {keepOnly ? (
          <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-sm text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:ring-slate-700">
            <Lock className="h-4 w-4 shrink-0" />
            {meteringCreated
              ? "O'lchov yaratildi — bosqich «Замерга борилади», endi faqat vazifa yopiladi"
              : can("call_center.change_invoice")
                ? "Ariza yopilgan — bosqich o'zgarmaydi"
                : "Bosqichni o'zgartirish huquqi yo'q — faqat vazifa yopiladi"}
            {!meteringCreated && task.invoice.solution_label && <span className="font-medium">· {task.invoice.solution_label}</span>}
          </div>
        ) : (
          <div>
            <div className="label">Keyingi bosqich</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {outcomes.map((o) => {
                const s = label(o);
                if (!s) return null;
                const active = outcome === o;
                const isCurrent = current === s.value;
                return (
                  <button
                    key={o}
                    type="button"
                    onClick={() => pick(o)}
                    className={cn(
                      "flex min-h-[48px] items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-semibold ring-inset transition hover:brightness-95",
                      TONES[s.tone].badge,
                      active ? "ring-2 ring-offset-0 brightness-95 dark:brightness-125" : "ring-1 opacity-90",
                    )}
                  >
                    {o === "go_for_measured" ? <Ruler className="h-4 w-4 shrink-0" /> : <PhoneCall className="h-4 w-4 shrink-0" />}
                    <span className="min-w-0 flex-1">{s.label}</span>
                    {isCurrent && (
                      <span className="rounded-md bg-white/70 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide dark:bg-slate-900/50">
                        hozirgi
                      </span>
                    )}
                    {active && <CheckIcon className="h-4 w-4 shrink-0" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {followUp && (
          <div>
            <div className="label">
              Keyingi qo'ng'iroq {needsTime ? <span className="text-rose-600">*</span> : <span className="muted font-normal">(ixtiyoriy)</span>}
            </div>
            <NextCallPicker value={next} onChange={setNext} allowNone={!needsTime} />
            {needsTime && !next && <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-300">Qachon qayta qo'ng'iroq qilishni tanlang</p>}
          </div>
        )}

        {closing && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Ariza yopiladi, ochiq vazifalar ham yopiladi
          </div>
        )}

        {outcome === "go_for_measured" && (
          <div className="rounded-xl bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300">
            Avval o'lchov yarating — javob kodi avtomatik «Замерга борилади» bo'ladi, vazifa yopiladi.
          </div>
        )}

        {done.error && (
          <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300">
            {errorMessage(done.error)}
          </div>
        )}
      </div>
    </Modal>
  );
}
