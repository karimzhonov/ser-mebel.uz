import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll } from "@/api/hooks";
import type { Factory } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PhoneLink } from "@/components/domain";
import { Button, Card, DataTable, Field, IconButton, Input, Modal, PageHeader } from "@/components/ui";

type Form = { id?: number; name: string; address: string; phone: string; ordering: string };

export default function FactoriesPage() {
  const { can } = useAuth();
  const { data, isFetching } = useAll<Factory>("factories");
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () => {
      const body = { ...form, ordering: Number(form!.ordering || 0) };
      return form!.id ? api.patch(`/factories/${form!.id}/`, body) : api.post("/factories/", body);
    },
    { success: "Сохранено", invalidate: ["factories"], onSuccess: () => setForm(null) },
  );
  const remove = useAction((id: number) => api.delete(`/factories/${id}/`), { success: "Удалено", invalidate: ["factories"] });

  return (
    <div>
      <PageHeader
        title="Заводы"
        subtitle="Производственные площадки"
        actions={
          can("order.add_factory") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setForm({ name: "", address: "", phone: "", ordering: "0" }))}>
              Завод
            </Button>
          )
        }
      />
      <Card padded={false}>
        <DataTable
          rows={data}
          loading={isFetching}
          rowKey={(r) => r.id}
          columns={[
            { key: "name", header: "Название", cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: "address", header: "Адрес", cell: (r) => r.address || "—" },
            { key: "phone", header: "Телефон", cell: (r) => <PhoneLink value={r.phone} /> },
            { key: "ordering", header: "Порядок", cell: (r) => r.ordering },
            {
              key: "actions",
              header: "",
              className: "text-right",
              cell: (r) => (
                <div className="flex justify-end gap-1">
                  {can("order.change_factory") && (
                    <IconButton label="Изменить" onClick={() => (setErrors({}), setForm({ id: r.id, name: r.name, address: r.address, phone: r.phone, ordering: String(r.ordering) }))}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                  {can("order.delete_factory") && (
                    <IconButton label="Удалить" onClick={() => confirm(`Удалить «${r.name}»?`) && remove.mutate(r.id)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>
      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? "Изменить завод" : "Новый завод"}
        size="sm"
        footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Сохранить</Button>}
      >
        {form && (
          <div className="space-y-4">
            <Field label="Название" error={errors.name}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Адрес" error={errors.address}><Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
            <Field label="Телефон" error={errors.phone}><Input inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="Порядок" error={errors.ordering}><Input type="number" value={form.ordering} onChange={(e) => setForm({ ...form, ordering: e.target.value })} /></Field>
          </div>
        )}
      </Modal>
    </div>
  );
}
