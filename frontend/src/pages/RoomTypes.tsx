import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll } from "@/api/hooks";
import type { ObjectType, RoomType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Card, Field, IconButton, Input, Modal } from "@/components/ui";

type Form = { id?: number; name: string; icon: string; ordering: string; object_types: number[] };

/** «Xona turlari»: what a price calculation starts from, and which furniture fits each room. */
export function RoomTypesCard({ objects }: { objects: ObjectType[] }) {
  const { can } = useAuth();
  const { data: types } = useAll<RoomType>("room-types");
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () => {
      const body = { ...form!, ordering: Number(form!.ordering || 0) };
      return form!.id ? api.patch(`/room-types/${form!.id}/`, body) : api.post("/room-types/", body);
    },
    { success: "Saqlandi", invalidate: ["room-types"], onSuccess: () => setForm(null) },
  );
  const remove = useAction((id: number) => api.delete(`/room-types/${id}/`), { success: "O'chirildi", invalidate: ["room-types"] });
  if (!can("price.change_roomtype") && !can("price.add_roomtype")) return null;
  const objName = (id: number) => objects.find((o) => o.id === id)?.name ?? id;

  return (
    <Card
      className="mt-6"
      padded={false}
      title="Xona turlari"
      actions={
        can("price.add_roomtype") && (
          <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setForm({ name: "", icon: "", ordering: String((types?.length ?? 0) + 1), object_types: [] }))}>
            Xona turi
          </Button>
        )
      }
    >
      <p className="muted px-5 pt-3 text-xs">Narx hisoblash xona tanlashdan boshlanadi. Har bir xonaga qaysi mebellar mos kelishini belgilang (hech biri belgilanmasa — hammasi).</p>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {types?.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 text-sm">
            <span className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-xl leading-none">{t.icon || "🏠"}</span>
              <b>{t.name}</b>
              {t.object_types.length ? t.object_types.map((o) => <Badge key={o} dot={false}>{objName(o)}</Badge>) : <span className="muted text-xs">barcha mebellar</span>}
            </span>
            <span className="flex gap-1">
              {can("price.change_roomtype") && (
                <IconButton label="Tahrirlash" onClick={() => (setErrors({}), setForm({ id: t.id, name: t.name, icon: t.icon, ordering: String(t.ordering), object_types: t.object_types }))}>
                  <Pencil className="h-4 w-4" />
                </IconButton>
              )}
              {can("price.delete_roomtype") && (
                <IconButton label="O'chirish" onClick={() => confirm(`«${t.name}» o'chirilsinmi?`) && remove.mutate(t.id)}>
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              )}
            </span>
          </li>
        ))}
      </ul>
      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? "Xona turini tahrirlash" : "Yangi xona turi"}
        size="sm"
        footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}
      >
        {form && (
          <div className="space-y-4">
            <div className="grid grid-cols-[1fr_80px_80px] gap-3">
              <Field label="Nomi" error={errors.name}>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Oshxona" />
              </Field>
              <Field label="Belgi" error={errors.icon}>
                <Input value={form.icon} maxLength={8} onChange={(e) => setForm({ ...form, icon: e.target.value })} placeholder="🍳" />
              </Field>
              <Field label="Tartib">
                <Input type="number" value={form.ordering} onChange={(e) => setForm({ ...form, ordering: e.target.value })} />
              </Field>
            </div>
            <Field label="Mos mebellar" hint="Hech biri tanlanmasa — barcha mebellar">
              <div className="flex flex-wrap gap-2">
                {objects.filter((o) => !o.archived || form.object_types.includes(o.id)).map((o) => {
                  const on = form.object_types.includes(o.id);
                  return (
                    <button
                      key={o.id}
                      type="button"
                      onClick={() => setForm({ ...form, object_types: on ? form.object_types.filter((x) => x !== o.id) : [...form.object_types, o.id] })}
                      className={on ? "rounded-full bg-brand-600 px-3 py-1 text-xs font-medium text-white" : "rounded-full border border-slate-200 px-3 py-1 text-xs dark:border-slate-700"}
                    >
                      {o.name}
                    </button>
                  );
                })}
              </div>
            </Field>
          </div>
        )}
      </Modal>
    </Card>
  );
}
