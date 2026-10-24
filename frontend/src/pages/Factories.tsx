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
    { success: "Saqlandi", invalidate: ["factories"], onSuccess: () => setForm(null) },
  );
  const remove = useAction((id: number) => api.delete(`/factories/${id}/`), { success: "O'chirildi", invalidate: ["factories"] });

  return (
    <div>
      <PageHeader
        title="Zavodlar"
        subtitle="Ishlab chiqarish maydonchalari"
        actions={
          can("order.add_factory") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => (setErrors({}), setForm({ name: "", address: "", phone: "", ordering: "0" }))}>
              Zavod
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
            { key: "name", header: "Nomi", cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: "address", header: "Manzil", cell: (r) => r.address || "—" },
            { key: "phone", header: "Telefon", cell: (r) => <PhoneLink value={r.phone} /> },
            { key: "ordering", header: "Tartib", cell: (r) => r.ordering },
            {
              key: "actions",
              header: "",
              className: "text-right",
              cell: (r) => (
                <div className="flex justify-end gap-1">
                  {can("order.change_factory") && (
                    <IconButton label="Tahrirlash" onClick={() => (setErrors({}), setForm({ id: r.id, name: r.name, address: r.address, phone: r.phone, ordering: String(r.ordering) }))}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                  {can("order.delete_factory") && (
                    <IconButton label="O'chirish" onClick={() => confirm(`«${r.name}» o'chirilsinmi?`) && remove.mutate(r.id)}>
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
        title={form?.id ? "Zavodni tahrirlash" : "Yangi zavod"}
        size="sm"
        footer={<Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}
      >
        {form && (
          <div className="space-y-4">
            <Field label="Nomi" error={errors.name}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Manzil" error={errors.address}><Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
            <Field label="Telefon" error={errors.phone}><Input inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="Tartib" error={errors.ordering}><Input type="number" value={form.ordering} onChange={(e) => setForm({ ...form, ordering: e.target.value })} /></Field>
          </div>
        )}
      </Modal>
    </div>
  );
}
