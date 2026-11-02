import { useState } from "react";
import { api, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import type { Invoice } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button, Chip, Field, Input, Modal, Textarea } from "@/components/ui";
import { AssigneeSelect, CRM_INVALIDATE, DuePicker, useAssignees, useLeadSources } from "./shared";

export function LeadCreateModal({
  initial,
  onClose,
  onCreated,
}: {
  initial?: { phone?: string; fio?: string; source?: string | null };
  onClose: () => void;
  onCreated?: (inv: Invoice) => void;
}) {
  const { user } = useAuth();
  const sources = useLeadSources();
  const assignees = useAssignees();
  const [form, setForm] = useState({
    phone: initial?.phone ?? "+998",
    fio: initial?.fio ?? "",
    source: initial?.source ?? "",
    desc: "",
  });
  const [assignedTo, setAssignedTo] = useState<number | null>(user?.id ?? null);
  const [withTask, setWithTask] = useState(true);
  const [task, setTask] = useState({ text: "Mijozga qo'ng'iroq qilish", due_at: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  // the creator is the default assignee, but only if they may be assigned at all
  const assigneeValue = assignees.length && !assignees.some((a) => a.id === assignedTo) ? null : assignedTo;

  const create = useAction(
    () =>
      api
        .post<Invoice>("/invoices/", {
          ...form,
          ...(assigneeValue ? { assigned_to: assigneeValue } : {}),
          ...(withTask && task.due_at ? { task_text: task.text.trim(), task_due_at: task.due_at } : {}),
        })
        .then((r) => r.data),
    {
      success: "Ariza yaratildi",
      invalidate: CRM_INVALIDATE,
      onSuccess: (inv) => {
        onClose();
        onCreated?.(inv);
      },
    },
  );

  const submit = () => {
    const local: Record<string, string> = {};
    if (!form.source) local.source = "Manbani tanlang";
    if (withTask && !task.due_at) local.task_due_at = "Qachon qo'ng'iroq qilishni tanlang (yoki vazifani o'chiring)";
    if (Object.keys(local).length) return setErrors(local);
    setErrors({});
    create.mutateAsync().catch((e) => setErrors(fieldErrors(e)));
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Yangi ariza"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          <Button loading={create.isPending} onClick={submit}>
            Saqlash
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Mijoz telefoni" error={errors.phone}>
          <Input autoFocus inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        <Field label="Mijoz F.I.Sh." error={errors.fio} hint="Mijoz bazada bo'lsa — mavjudi ishlatiladi.">
          <Input value={form.fio} onChange={(e) => setForm({ ...form, fio: e.target.value })} />
        </Field>

        <div className="sm:col-span-2">
          <span className="label">
            Manba <span className="text-rose-600">*</span>
          </span>
          <div className="flex flex-wrap gap-2">
            {sources.map((s) => (
              <Chip key={s.value} active={form.source === s.value} onClick={() => setForm({ ...form, source: s.value })}>
                {s.label}
              </Chip>
            ))}
            {!sources.length && <span className="muted text-xs">Manbalar yuklanmoqda…</span>}
          </div>
          {errors.source && <span className="mt-1 block text-xs text-rose-600">{errors.source}</span>}
        </div>

        <Field label="Mas'ul xodim" error={errors.assigned_to} className="sm:col-span-2">
          <AssigneeSelect value={assigneeValue} onChange={setAssignedTo} assignees={assignees} emptyLabel="Menga" />
        </Field>

        <Field label="Izoh" error={errors.desc} className="sm:col-span-2">
          <Textarea
            placeholder="Mijoz nima so'radi, qanday mebel, qaysi xona…"
            value={form.desc}
            onChange={(e) => setForm({ ...form, desc: e.target.value })}
          />
        </Field>

        <div className="rounded-xl border border-slate-200 p-3 sm:col-span-2 dark:border-slate-700">
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={withTask} onChange={(e) => setWithTask(e.target.checked)} />
            Eslatma (keyingi qo'ng'iroq)
          </label>
          {withTask && (
            <div className="mt-3 space-y-3">
              <Field error={errors.task_text}>
                <Input value={task.text} onChange={(e) => setTask({ ...task, text: e.target.value })} />
              </Field>
              <DuePicker value={task.due_at} onChange={(due_at) => setTask({ ...task, due_at })} />
              {errors.task_due_at && <span className="block text-xs text-rose-600">{errors.task_due_at}</span>}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
