import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import { Button, Field, Input, Modal } from "@/components/ui";
import { toLocalInput } from "@/lib/format";
import { DueLabel, dueText } from "@/pages/offers/actions";

const INVALIDATE = ["orders", "dashboard", "detailings", "assemblies", "meterings"];

/** a Date as "2026-11-05T18:00" for <input type="datetime-local"> */
function localInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** today + n days at 18:00 */
function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  d.setHours(18, 0, 0, 0);
  return d;
}

export function isDetailingOverdue(dueAt: string | null | undefined, done: boolean) {
  return !done && !!dueAt && new Date(dueAt).getTime() < Date.now();
}

/** The detailing deadline, red when it passed. */
export function DetailingDue({ dueAt, done }: { dueAt: string | null | undefined; done: boolean }) {
  return <DueLabel value={dueAt} overdue={isDetailingOverdue(dueAt, done)} />;
}

/**
 * «Detalirovkaga» with its deadline (POST /orders/{id}/detailing/ {due_at}),
 * or moving the deadline later (POST /detailings/{id}/due/ {due_at}).
 */
export function DetailingDueModal({
  orderId,
  detailingId,
  dueAt,
  onClose,
}: {
  orderId?: number;
  detailingId?: number;
  dueAt?: string | null;
  onClose: () => void;
}) {
  const sending = !detailingId;
  const [value, setValue] = useState(dueAt ? toLocalInput(dueAt) : "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      sending
        ? api.post(`/orders/${orderId}/detailing/`, { due_at: value })
        : api.post(`/detailings/${detailingId}/due/`, { due_at: value }),
    {
      success: sending ? "Detalirovkaga yuborildi" : "Muddat o'zgartirildi",
      invalidate: INVALIDATE,
      onSuccess: onClose,
    },
  );
  const past = !!value && new Date(value).getTime() <= Date.now();
  const error = errors.due_at;
  return (
    <Modal
      open
      onClose={onClose}
      title={sending ? "Detalirovkaga yuborish" : "Detalirovka muddatini o'zgartirish"}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button
            size="lg"
            variant={sending ? "success" : "primary"}
            disabled={!value || past}
            loading={save.isPending}
            onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            {sending ? "Yuborish" : "Saqlash"}
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">
        {sending
          ? "Detalirovka qachongacha tayyor bo'lishi kerak? Detalirovka xodimlariga xabar boradi."
          : <>Hozirgi muddat: <b className="text-slate-700 dark:text-slate-200">{dueText(dueAt)}</b></>}
      </p>
      <div className="mb-3 grid grid-cols-4 gap-2">
        {[1, 2, 3, 5].map((n) => (
          <Button key={n} size="lg" variant="secondary" onClick={() => setValue(localInput(inDays(n)))}>
            +{n} kun
          </Button>
        ))}
      </div>
      <Field label="Muddat" error={error ?? (past ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}>
        <Input className="h-12 text-base" type="datetime-local" required value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  );
}
