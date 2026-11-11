import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import { Button, Field, Input, Modal } from "@/components/ui";
import { cn } from "@/lib/cn";

const INVALIDATE = ["rovers", "orders", "dashboard"];

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

/** The rover deadline: red when late, muted when nobody set it yet, «(avto)» when automatic. */
export function RoverDueLabel({
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

/** The production head sets / moves the deadline (POST /rovers/{id}/due/ {due_date}). */
export function RoverDueModal({
  roverId,
  dueDate,
  onClose,
}: {
  roverId: number;
  dueDate?: string | null;
  onClose: () => void;
}) {
  const [value, setValue] = useState(dueDate ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const today = dateInput(new Date());
  const past = !!value && value < today;
  const save = useAction(() => api.post(`/rovers/${roverId}/due/`, { due_date: value }), {
    success: "Muddat belgilandi",
    invalidate: INVALIDATE,
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Rover muddati"
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
        {[3, 5, 7].map((n) => (
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
