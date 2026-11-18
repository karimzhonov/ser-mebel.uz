import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import { Button, Field, Input, Modal, Segmented, Textarea } from "@/components/ui";
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

/** Where the parts are cut/edged — mirrors order.detailing.models.ServicePlace. */
export const SERVICE_PLACES = [
  { value: "timber", label: "Timber" },
  { value: "eman", label: "Eman" },
  { value: "other", label: "Boshqa" },
] as const;

export function servicePlaceLabel(value: string | null | undefined) {
  return SERVICE_PLACES.find((p) => p.value === value)?.label ?? "";
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

/**
 * «Detalirovka bajarildi» -> «Заказ на сырье» with the time the parts come out of
 * the service (POST /detailings/{id}/done/ {service_out_at}), or moving that time
 * later (POST /detailings/{id}/service-out/ {service_out_at}).
 */
export function ServiceOutModal({
  detailingId,
  current,
  place: currentPlace,
  note: currentNote,
  onClose,
}: {
  detailingId: number;
  /** set -> changing an existing time; absent -> marking the detailing done */
  current?: string | null;
  place?: string | null;
  note?: string | null;
  onClose: () => void;
}) {
  const finishing = current === undefined;
  const [value, setValue] = useState(current ? toLocalInput(current) : "");
  const [place, setPlace] = useState<string>(currentPlace ?? "");
  const [note, setNote] = useState(currentNote ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api.post(`/detailings/${detailingId}/${finishing ? "done" : "service-out"}/`, {
        service_out_at: value,
        service_place: place,
        service_note: note,
      }),
    {
      success: finishing ? "Xomashyo buyurtmasiga o'tdi" : "Vaqt o'zgartirildi",
      invalidate: [...INVALIDATE, "rovers", "painters"],
      onSuccess: onClose,
    },
  );
  const past = !!value && new Date(value).getTime() <= Date.now();
  return (
    <Modal
      open
      onClose={onClose}
      title={finishing ? "Detalirovka bajarildi" : "Usluga'dan chiqish vaqti"}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button
            size="lg"
            variant={finishing ? "success" : "primary"}
            disabled={!value || past || !place}
            loading={save.isPending}
            onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            {finishing ? "Bajarildi" : "Saqlash"}
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">
        {finishing
          ? "Buyurtma «Xomashyo buyurtmasi» bosqichiga o'tadi. Detallar usluga'dan qachon chiqadi?"
          : <>Hozirgi vaqt: <b className="text-slate-700 dark:text-slate-200">{dueText(current)}</b></>}
      </p>
      <div className="mb-3 grid grid-cols-4 gap-2">
        {[1, 2, 3, 5].map((n) => (
          <Button key={n} size="lg" variant="secondary" onClick={() => setValue(localInput(inDays(n)))}>
            +{n} kun
          </Button>
        ))}
      </div>
      <Field
        label="Usluga'dan chiqish vaqti"
        error={errors.service_out_at ?? errors.detail ?? (past ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}
      >
        <Input className="h-12 text-base" type="datetime-local" required value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <Field label="Qaysi usluga" error={errors.service_place}>
        <Segmented
          value={place}
          onChange={setPlace}
          options={SERVICE_PLACES.map((p) => ({ value: p.value as string, label: p.label }))}
        />
      </Field>
      <Field label="Izoh" error={errors.service_note}>
        <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Masalan: qaysi sex, kim olib keladi…" />
      </Field>
    </Modal>
  );
}
