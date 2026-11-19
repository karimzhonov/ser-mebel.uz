import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import { Badge, Button, Field, Input, Modal, Textarea } from "@/components/ui";
import { dateTime, toLocalInput } from "@/lib/format";
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
 * or moving the deadline later (POST /detailings/{id}/due/ {due_at}; from the order page,
 * where orderId is given too, POST /orders/{id}/detailing-due/ — the Bosh menejer has no
 * access to the detailings section).
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
        : orderId
          ? api.post(`/orders/${orderId}/detailing-due/`, { due_at: value })
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

export type DetailingServiceRow = { place: string; out_at: string; note: string };

/** Each service with its own time (red once passed) and comment; `fallback` = the single
 * time of a detailing done before services existed. */
export function ServiceList({ services, fallback }: { services?: DetailingServiceRow[]; fallback?: string | null }) {
  if (!services?.length) return fallback ? <span>{dateTime(fallback)}</span> : <span className="muted">—</span>;
  return (
    <span className="flex flex-col gap-1">
      {services.map((s) => (
        <span key={s.place} className="flex flex-wrap items-center gap-1.5">
          <Badge tone="info" dot={false}>{servicePlaceLabel(s.place)}</Badge>
          <DueLabel value={s.out_at} overdue={false} />
          {s.note && <span className="muted text-xs">{s.note}</span>}
        </span>
      ))}
    </span>
  );
}

type Draft = { on: boolean; out_at: string; note: string; was?: string };

/**
 * «Detalirovka bajarildi» -> «Заказ на сырье»: which service(s) got the parts and when
 * each gives them back — an order can go half to Timber and half to Eman, each with its
 * own time (POST /detailings/{id}/done/ {services}); or changing them later
 * (POST /detailings/{id}/service-out/ {services}).
 */
export function ServiceOutModal({
  detailingId,
  current,
  onClose,
}: {
  detailingId: number;
  /** set -> changing the existing services; absent -> marking the detailing done */
  current?: DetailingServiceRow[];
  onClose: () => void;
}) {
  const finishing = current === undefined;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(
      SERVICE_PLACES.map(({ value }) => {
        const row = current?.find((r) => r.place === value);
        return [
          value,
          row
            ? { on: true, out_at: toLocalInput(row.out_at), note: row.note, was: toLocalInput(row.out_at) }
            : { on: false, out_at: "", note: "" },
        ];
      }),
    ),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const patch = (place: string, p: Partial<Draft>) => setDrafts((d) => ({ ...d, [place]: { ...d[place], ...p } }));
  const chosen = SERVICE_PLACES.filter((p) => drafts[p.value].on);
  // an unchanged time may have passed already (those parts are out); a new one may not
  const isPast = (d: Draft) => !!d.out_at && d.out_at !== d.was && new Date(d.out_at).getTime() <= Date.now();
  const invalid = !chosen.length || chosen.some((p) => !drafts[p.value].out_at || isPast(drafts[p.value]));
  const save = useAction(
    () =>
      api.post(`/detailings/${detailingId}/${finishing ? "done" : "service-out"}/`, {
        services: chosen.map((p) => ({ place: p.value, out_at: drafts[p.value].out_at, note: drafts[p.value].note })),
      }),
    {
      success: finishing ? "Xomashyo buyurtmasiga o'tdi" : "Saqlandi",
      invalidate: [...INVALIDATE, "rovers", "painters"],
      onSuccess: onClose,
    },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={finishing ? "Detalirovka bajarildi" : "Usluga'lar"}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button
            size="lg"
            variant={finishing ? "success" : "primary"}
            disabled={invalid}
            loading={save.isPending}
            onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            {finishing ? "Bajarildi" : "Saqlash"}
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">
        {finishing && "Buyurtma «Xomashyo buyurtmasi» bosqichiga o'tadi. "}
        Detallar qaysi usluga'ga berildi va qachon chiqadi? Bir nechtasini tanlash mumkin (masalan, yarmi Timber, yarmi Eman) — har biriga o'z muddati.
      </p>
      <div className="space-y-3">
        {SERVICE_PLACES.map(({ value, label }) => {
          const d = drafts[value];
          return (
            <div
              key={value}
              className={
                d.on
                  ? "rounded-2xl border border-brand-300 bg-brand-50/40 p-3 dark:border-brand-500/40 dark:bg-brand-500/5"
                  : "rounded-2xl border border-slate-200 p-3 dark:border-slate-700"
              }
            >
              <label className="flex cursor-pointer items-center gap-2 font-semibold">
                <input type="checkbox" className="h-4 w-4" checked={d.on} onChange={(e) => patch(value, { on: e.target.checked })} />
                {label}
              </label>
              {d.on && (
                <div className="mt-3 space-y-2">
                  <div className="grid grid-cols-4 gap-2">
                    {[3, 5, 7, 10].map((n) => (
                      <Button key={n} variant="secondary" onClick={() => patch(value, { out_at: localInput(inDays(n)) })}>
                        +{n} kun
                      </Button>
                    ))}
                  </div>
                  <Field
                    label="Chiqish vaqti"
                    error={isPast(d) ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined}
                  >
                    <Input
                      className="h-11 text-base"
                      type="datetime-local"
                      required
                      value={d.out_at}
                      onChange={(e) => patch(value, { out_at: e.target.value })}
                    />
                  </Field>
                  <Field label="Izoh">
                    <Textarea rows={2} value={d.note} onChange={(e) => patch(value, { note: e.target.value })} placeholder="Masalan: qaysi detallar, kim olib keladi…" />
                  </Field>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {(errors.services ?? errors.detail) && (
        <p className="mt-3 text-sm text-rose-600 dark:text-rose-400">{errors.services ?? errors.detail}</p>
      )}
    </Modal>
  );
}
