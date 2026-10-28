import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import type { Tone } from "@/api/types";
import { Badge, Button, Field, Input, Modal, Select, Textarea } from "@/components/ui";

// HR — davomat API shapes (backend/api/views/hr.py)

export type Status = "on_time" | "late" | "waiting" | "absent" | "excused" | "leave" | "off" | "holiday" | "noin";

export const STATUS: Record<Status, { label: string; tone: Tone }> = {
  on_time: { label: "✅ Vaqtida", tone: "ok" },
  late: { label: "⏰ Kech qoldi", tone: "warn" },
  waiting: { label: "⏳ Hali kelmadi", tone: "info" },
  absent: { label: "❌ Kelmadi", tone: "danger" },
  excused: { label: "📝 Sababli", tone: "idle" },
  leave: { label: "🏖 Ta'tilda", tone: "idle" },
  off: { label: "😴 Dam kuni", tone: "idle" },
  holiday: { label: "🎉 Bayram", tone: "primary" },
  noin: { label: "❔ Kelish qayd etilmagan", tone: "warn" },
};

export function StatusBadge({ s }: { s: string }) {
  const x = STATUS[s as Status];
  return x ? <Badge tone={x.tone}>{x.label}</Badge> : <Badge>{s || "—"}</Badge>;
}

export const WD = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];

export interface DayRow {
  employee_id: number;
  number: number;
  name: string;
  username: string;
  group: string;
  status: Status;
  attendance_id: number | null;
  in_time: string;
  out_time: string;
  late_min: number | null;
  late_reason: string;
  late_comment: string;
  early_min: number | null;
  early_reason: string;
  early_comment: string;
  eta: string;
  uniform: boolean | null;
  note: string;
  link: string;
  hours: string;
  points: number | null;
  finalized: boolean;
  can_dm: boolean | null;
}

export interface DayBoard {
  date: string;
  now: string | null;
  holiday: string | null;
  rows: DayRow[];
  counts: Partial<Record<Status, number>>;
  expected: number;
}

export interface Attendance {
  id: number;
  employee: number;
  employee_name: string;
  employee_number: number;
  day: string;
  status: Status;
  status_label: string;
  in_time: string | null;
  late_min: number | null;
  late_reason: string;
  late_comment: string;
  out_time: string | null;
  early_min: number | null;
  early_reason: string;
  early_comment: string;
  uniform: boolean | null;
  eta: string | null;
  excuse: string;
  note: string;
  link: string;
  work_start: string;
  work_end: string;
  points: number | null;
  finalized: boolean;
  group_title: string;
}

export interface Employee {
  id: number;
  telegram_id: number;
  number: number;
  name: string;
  username: string;
  is_active: boolean;
  can_dm: boolean | null;
  off_days: number[] | null;
  off_days_effective: number[];
  group: number | null;
  group_title: string;
  work_start: string;
  work_end: string;
  hours: string;
  created_on: string | null;
  member: number | null;
  member_name: string | null;
}

export interface Group {
  id: number;
  chat_id: number;
  title: string;
  is_active: boolean;
  employees: number;
}

export interface StatRow {
  employee_id: number;
  number: number;
  name: string;
  points: number;
  expected: number;
  on_time: number;
  late?: number;
  late_min?: number;
  absent?: number;
  excused?: number;
  left_early?: number;
  discipline: number;
  bonus: number;
  adjust: number;
  wins?: number;
}

export const hhmm = (t: string | null | undefined) => (t ? t.slice(0, 5) : "");

/** HR correction of one day (points of a finished day are recomputed on the server). */
export function AttendanceModal({ id, title, initial, onClose }: { id: number; title: string; initial: Partial<Attendance>; onClose: () => void }) {
  const [f, setF] = useState({
    status: initial.status ?? "absent",
    in_time: hhmm(initial.in_time),
    out_time: hhmm(initial.out_time),
    late_reason: initial.late_reason ?? "",
    late_comment: initial.late_comment ?? "",
    early_reason: initial.early_reason ?? "",
    early_comment: initial.early_comment ?? "",
    uniform: initial.uniform === null || initial.uniform === undefined ? "" : initial.uniform ? "1" : "0",
    excuse: initial.excuse ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api.patch(`/hr/attendance/${id}/`, {
        status: f.status,
        in_time: f.in_time || null,
        out_time: f.out_time || null,
        late_reason: f.late_reason,
        late_comment: f.late_comment,
        early_reason: f.early_reason,
        early_comment: f.early_comment,
        uniform: f.uniform === "" ? null : f.uniform === "1",
        excuse: f.excuse,
      }),
    { success: "Saqlandi", invalidate: ["hr"], onSuccess: onClose },
  );
  const set = (p: Partial<typeof f>) => setF({ ...f, ...p });
  return (
    <Modal open onClose={onClose} title={title} size="sm" footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}>
      <div className="space-y-3">
        <Field label="Holat" error={errors.status}>
          <Select value={f.status} onChange={(e) => set({ status: e.target.value as Status })}>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kelgan vaqti" error={errors.in_time}>
            <Input type="time" value={f.in_time} onChange={(e) => set({ in_time: e.target.value })} />
          </Field>
          <Field label="Ketgan vaqti" error={errors.out_time}>
            <Input type="time" value={f.out_time} onChange={(e) => set({ out_time: e.target.value })} />
          </Field>
        </div>
        {f.status === "late" && (
          <div className="grid grid-cols-[140px_1fr] gap-3">
            <Field label="Kechikish">
              <Select value={f.late_reason} onChange={(e) => set({ late_reason: e.target.value })}>
                <option value="">—</option>
                <option value="Sababli">Sababli</option>
                <option value="Sababsiz">Sababsiz</option>
              </Select>
            </Field>
            <Field label="Izoh">
              <Input value={f.late_comment} onChange={(e) => set({ late_comment: e.target.value })} />
            </Field>
          </div>
        )}
        {f.out_time && (
          <div className="grid grid-cols-[140px_1fr] gap-3">
            <Field label="Erta ketish">
              <Select value={f.early_reason} onChange={(e) => set({ early_reason: e.target.value })}>
                <option value="">—</option>
                <option value="Sababli">Sababli</option>
                <option value="Sababsiz">Sababsiz</option>
              </Select>
            </Field>
            <Field label="Izoh">
              <Input value={f.early_comment} onChange={(e) => set({ early_comment: e.target.value })} />
            </Field>
          </div>
        )}
        <Field label="Forma">
          <Select value={f.uniform} onChange={(e) => set({ uniform: e.target.value })}>
            <option value="">—</option>
            <option value="1">👕 Formada</option>
            <option value="0">Formasiz</option>
          </Select>
        </Field>
        {f.status === "excused" && (
          <Field label="Sabab">
            <Textarea value={f.excuse} onChange={(e) => set({ excuse: e.target.value })} />
          </Field>
        )}
        <p className="muted text-xs">Yakunlangan kunning bali shu ma'lumotlar bo'yicha qayta hisoblanadi.</p>
      </div>
    </Modal>
  );
}
