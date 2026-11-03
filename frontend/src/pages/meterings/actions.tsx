import { useState } from "react";
import { CalendarClock, CheckCircle2, Upload, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { MeasurerList, Metering, MeteringNextStep, PersonRef } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button, Confirm, Field, Input, Modal, Textarea } from "@/components/ui";
import { cn } from "@/lib/cn";
import { phone, toLocalInput } from "@/lib/format";

/** everything a zamer change can show up in */
export const METERING_INVALIDATE = ["meterings", "dashboard", "designs", "prices", "invoices", "invoice-tasks", "timeline", "clients"];

export const OPEN_STATUSES = ["created", "other_day"];
export const isOpenMetering = (status: string) => OPEN_STATUSES.includes(status);

export const NEXT_STEP_LABEL: Record<Exclude<MeteringNextStep, "">, string> = {
  design_price: "Dizayn + narx",
  price: "Faqat narx",
};

/** 500 MB per file — the same limit the server checks (METERING_MAX_UPLOAD_MB) */
export const MAX_UPLOAD_MB = 500;

export function personName(u: PersonRef | null | undefined, empty = "—") {
  if (!u) return empty;
  return u.name || phone(u.phone) || `#${u.id}`;
}

const WEEKDAYS = ["Yakshanba", "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"];

/** "14:30" */
export function timeOnly(value: string | null | undefined, empty = "—") {
  if (!value) return empty;
  return new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

/** "Payshanba, 05.11" */
export function dayLabel(value: string | null | undefined, empty = "—") {
  if (!value) return empty;
  const d = new Date(value);
  return `${WEEKDAYS[d.getDay()]}, ${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}`;
}

/** a Date as "2026-11-05T14:30" for <input type="datetime-local"> */
function localInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** Buttons a row of the agenda may show. The list API sends no `actions`, so this mirrors
 * services.can_work_metering / can_reschedule_or_cancel; the server checks again anyway. */
export function useRowActions() {
  const { user, can } = useAuth();
  return (m: Metering) => {
    const mine =
      can("metering.manage_metering") ||
      (!!m.measurer && m.measurer.id === user?.id) ||
      (!m.measurer && can("oauth.user_metering"));
    const steer = mine || can("metering.change_metering");
    const open = isOpenMetering(m.status);
    return {
      measured: open && mine,
      reschedule: open && steer,
      cancel: (open || m.status === "metering_done") && steer,
      finish: m.status === "metering_done" && mine,
    };
  };
}

export function useMeasurers(enabled = true) {
  return useGet<MeasurerList>(enabled ? "/meterings/measurers/" : null);
}

export interface MeteringAllowed {
  measured?: boolean;
  reschedule?: boolean;
  cancel?: boolean;
  /** «📤 Natija» — opens the result form */
  finish?: boolean;
}

/** «O'lchov oldim» / «Vaqtni o'zgartirish» / «Bekor bo'ldi» / «Natija» with their dialogs.
 * Clicks never reach a clickable card around it (modals are portals, but React still bubbles). */
export function MeteringActionButtons({
  metering,
  allowed,
  big,
  onMeasured,
  onResult,
  className,
}: {
  metering: Metering;
  allowed: MeteringAllowed;
  /** phone-sized buttons that fill the row */
  big?: boolean;
  onMeasured?: () => void;
  onResult?: () => void;
  className?: string;
}) {
  const [dialog, setDialog] = useState<null | "measured" | "reschedule" | "cancel">(null);
  const measured = useAction(() => api.post(`/meterings/${metering.id}/metering-done/`), {
    invalidate: METERING_INVALIDATE,
    onSuccess: () => {
      setDialog(null);
      if (onMeasured) onMeasured();
      else toast.success("O'lchov olindi — endi fayllarni yuklang", onResult ? { action: { label: "Natija", onClick: onResult } } : undefined);
    },
  });
  const any = allowed.measured || allowed.reschedule || allowed.cancel || allowed.finish;
  if (!any) return null;
  const size = big ? "lg" : "md";
  const wide = big && "flex-1 basis-[calc(50%-4px)] sm:basis-auto";

  return (
    <div className={cn("flex flex-wrap gap-2", className)} onClick={(e) => e.stopPropagation()}>
      {allowed.measured && (
        <Button size={size} variant="success" className={cn(wide, big && "basis-full sm:basis-auto")} icon={<CheckCircle2 className="h-5 w-5" />} onClick={() => setDialog("measured")}>
          O'lchov oldim
        </Button>
      )}
      {allowed.finish && onResult && (
        <Button size={size} className={cn(wide, big && "basis-full sm:basis-auto")} icon={<Upload className="h-5 w-5" />} onClick={onResult}>
          Natija
        </Button>
      )}
      {allowed.reschedule && (
        <Button size={size} variant="outline" className={cn(wide)} icon={<CalendarClock className="h-5 w-5" />} onClick={() => setDialog("reschedule")}>
          Vaqtni o'zgartirish
        </Button>
      )}
      {allowed.cancel && (
        <Button size={size} variant="outline" className={cn(wide, "text-rose-600 dark:text-rose-400")} icon={<XCircle className="h-5 w-5" />} onClick={() => setDialog("cancel")}>
          Bekor bo'ldi
        </Button>
      )}

      <Confirm
        open={dialog === "measured"}
        onClose={() => setDialog(null)}
        title="O'lchov olindimi?"
        text={
          <>
            <b>{metering.client.fio}</b> — o'lchov olingan deb belgilanadi. Keyin rasm/video/fayllarni yuklab, natijani yozasiz.
          </>
        }
        confirmLabel="Ha, o'lchov oldim"
        variant="success"
        loading={measured.isPending}
        onConfirm={() => measured.mutate()}
      />
      {dialog === "reschedule" && <RescheduleModal metering={metering} onClose={() => setDialog(null)} />}
      {dialog === "cancel" && <CancelModal metering={metering} onClose={() => setDialog(null)} />}
    </div>
  );
}

/** Measurer agreed a new time with the client (no SMS goes to the client). */
export function RescheduleModal({ metering, onClose }: { metering: Metering; onClose: () => void }) {
  const [value, setValue] = useState(toLocalInput(metering.date_time));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(() => api.post(`/meterings/${metering.id}/other-day/`, { date_time: value }), {
    success: "Vaqt o'zgartirildi",
    invalidate: METERING_INVALIDATE,
    onSuccess: onClose,
  });
  const base = metering.date_time ? new Date(metering.date_time) : new Date();
  const presets: { label: string; at: () => Date }[] = [
    {
      label: "1 soatdan keyin",
      at: () => {
        const d = new Date(Date.now() + 60 * 60000);
        const m = d.getMinutes();
        d.setSeconds(0, 0);
        if (m === 0 || m === 30) return d;
        d.setMinutes(m < 30 ? 30 : 60);
        return d;
      },
    },
    {
      label: "Ertaga",
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(base.getHours(), base.getMinutes(), 0, 0);
        return d;
      },
    },
    {
      label: "2 kundan keyin",
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 2);
        d.setHours(base.getHours(), base.getMinutes(), 0, 0);
        return d;
      },
    },
  ];
  const past = !!value && new Date(value).getTime() <= Date.now();
  const error = errors.time ?? errors.date_time;

  return (
    <Modal
      open
      onClose={onClose}
      title="Vaqtni o'zgartirish"
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
      <p className="muted mb-3 text-sm">Mijoz bilan kelishilgan yangi vaqtni kiriting.</p>
      <div className="mb-3 flex flex-wrap gap-2">
        {presets.map((p) => (
          <Button key={p.label} variant="secondary" onClick={() => setValue(localInput(p.at()))}>
            {p.label}
          </Button>
        ))}
      </div>
      <Field label="Yangi sana va vaqt" error={error ?? (past ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}>
        <Input className="h-12 text-base" type="datetime-local" required value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  );
}

/** The client refused / the zamer will not happen: the lead goes back to its operator. */
export function CancelModal({ metering, onClose }: { metering: Metering; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () => api.post<{ lead_returned?: boolean }>(`/meterings/${metering.id}/dont-need/`, { reason: reason.trim() }).then((r) => r.data),
    {
      invalidate: METERING_INVALIDATE,
      onSuccess: (r) => {
        toast.success(r?.lead_returned ? "Bekor qilindi — ariza operatorga qaytdi" : "Zamer bekor qilindi");
        onClose();
      },
    },
  );
  const ok = reason.trim().length >= 3;
  return (
    <Modal
      open
      onClose={onClose}
      title="Zamer bekor bo'ldimi?"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Orqaga</Button>
          <Button size="lg" variant="danger" disabled={!ok} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Bekor qilish
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">
        {metering.invoice ? "Ariza operatorga qaytadi — u mijozga qayta qo'ng'iroq qiladi." : "Zamer arxivga o'tadi."}
      </p>
      <Field label="Sababi" error={errors.reason}>
        <Textarea autoFocus value={reason} placeholder="Masalan: mijoz telefonni ko'tarmadi, uyda yo'q, fikridan qaytdi…" onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Modal>
  );
}
