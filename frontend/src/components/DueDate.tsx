import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import { Button, Field, Input, Modal } from "@/components/ui";
import { cn } from "@/lib/cn";

/** a Date as "2026-11-05" (local) for <input type="date"> */
function dateInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return dateInput(d);
}

function dayText(value: string) {
  const [y, m, d] = value.split("-");
  return `${d}.${m}.${y}`;
}

/** A production deadline: red when late, muted when nobody set it yet, «(avto)» when automatic. */
export function DueLabel({
  dueDate,
  auto,
  overdue,
  className,
}: {
  dueDate: string | null | undefined;
  auto?: boolean;
  overdue?: boolean;
  className?: string;
}) {
  if (!dueDate) return <span className={cn("muted whitespace-nowrap", className)}>Muddat hali belgilanmagan</span>;
  return (
    <span
      className={cn(
        "whitespace-nowrap font-semibold tabular-nums",
        overdue && "text-rose-600 dark:text-rose-400",
        className,
      )}
    >
      {overdue && "⚠️ "}
      {dayText(dueDate)}
      {auto && <span className="muted ml-1 text-xs font-normal">(avto)</span>}
    </span>
  );
}

/** The production head sets / moves the deadline (POST /{resource}/{id}/due/ {due_date}). */
export function DueModal({
  resource,
  id,
  dueDate,
  title,
  presets,
  invalidate,
  extra,
  onClose,
}: {
  resource: string;
  id: number;
  dueDate?: string | null;
  title: string;
  presets: number[];
  invalidate: string[];
  /** more fields for the POST body (e.g. the painter part id) */
  extra?: Record<string, unknown>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(dueDate ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const today = dateInput(new Date());
  const past = !!value && value < today;
  const save = useAction(() => api.post(`/${resource}/${id}/due/`, { due_date: value, ...extra }), {
    success: "Muddat belgilandi",
    invalidate,
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button
            size="lg"
            disabled={!value || past}
            loading={save.isPending}
            onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            Saqlash
          </Button>
        </>
      }
    >
      <p className="muted mb-3 text-sm">
        Hozirgi muddat: <b className="text-slate-700 dark:text-slate-200">{dueDate ? dayText(dueDate) : "belgilanmagan"}</b>
      </p>
      <div className="mb-3 grid grid-cols-3 gap-2">
        {presets.map((n) => (
          <Button key={n} size="lg" variant="secondary" onClick={() => setValue(inDays(n))}>
            +{n} kun
          </Button>
        ))}
      </div>
      <Field label="Muddat" error={errors.due ?? errors.due_date ?? (past ? "O'tgan sana — bugun yoki keyingi sanani tanlang" : undefined)}>
        <Input className="h-12 text-base" type="date" min={today} required value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  );
}
