import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useMeta } from "@/api/hooks";
import type { Inventory, InventoryType, ObjectType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  Badge,
  Button,
  Card,
  Empty,
  Field,
  IconButton,
  Input,
  Modal,
  MoneyInput,
  PageHeader,
  PageLoader,
  Segmented,
  Select,
} from "@/components/ui";
import { money } from "@/lib/format";

type TypeForm = { id?: number; name: string; type: string; ordering: string };
type InvForm = { id?: number; name: string; type: number; price: { amount: number | string; currency: string } };

export default function CatalogPage() {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { data: objects } = useAll<ObjectType>("object-types");
  const [tab, setTab] = useState("");
  const current = tab || String(objects?.[0]?.id ?? "");
  const { data: types, isLoading } = useAll<InventoryType>("inventory-types", { obj: current }, !!current);
  const [typeForm, setTypeForm] = useState<TypeForm | null>(null);
  const [invForm, setInvForm] = useState<InvForm | null>(null);
  const [objForm, setObjForm] = useState<{ name: string; count_name: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const inv = ["inventory-types", "object-types", "inventories"];
  const saveType = useAction(
    () => {
      const body = { name: typeForm!.name, type: Number(typeForm!.type), ordering: Number(typeForm!.ordering || 0), obj: Number(current) };
      return typeForm!.id ? api.patch(`/inventory-types/${typeForm!.id}/`, body) : api.post("/inventory-types/", body);
    },
    { success: "Сохранено", invalidate: inv, onSuccess: () => setTypeForm(null) },
  );
  const saveInv = useAction(
    () => {
      const body = { name: invForm!.name, type: invForm!.type, price: invForm!.price };
      return invForm!.id ? api.patch(`/inventories/${invForm!.id}/`, body) : api.post("/inventories/", body);
    },
    { success: "Сохранено", invalidate: inv, onSuccess: () => setInvForm(null) },
  );
  const saveObj = useAction(() => api.post("/object-types/", objForm), {
    success: "Объект добавлен",
    invalidate: inv,
    onSuccess: () => setObjForm(null),
  });
  const delType = useAction((id: number) => api.delete(`/inventory-types/${id}/`), { success: "Удалено", invalidate: inv });
  const delInv = useAction((id: number) => api.delete(`/inventories/${id}/`), { success: "Удалено", invalidate: inv });

  if (!objects) return <PageLoader />;
  return (
    <div>
      <PageHeader
        title="Товары"
        subtitle="Каталог материалов и фурнитуры для расчёта цены"
        actions={
          <>
            {can("price.add_objecttype") && (
              <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setObjForm({ name: "", count_name: "kv" })}>
                Объект
              </Button>
            )}
            {can("price.add_inventorytype") && current && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setTypeForm({ name: "", type: "2", ordering: "0" })}>
                Тип товара
              </Button>
            )}
          </>
        }
      />
      {!objects.length ? (
        <Card>
          <Empty title="Нет объектов" text="Сначала добавьте объект (кухня, шкаф…)." />
        </Card>
      ) : (
        <>
          <Segmented className="mb-4" value={current} onChange={setTab} options={objects.map((o) => ({ value: String(o.id), label: o.name }))} />
          {isLoading && <PageLoader />}
          {types && !types.length && (
            <Card>
              <Empty title="Нет типов товаров" />
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {types?.map((t) => (
              <Card
                key={t.id}
                padded={false}
                title={
                  <span className="flex items-center gap-2">
                    {t.name} <Badge dot={false}>{t.type_label}</Badge>
                  </span>
                }
                actions={
                  <>
                    {can("price.change_inventorytype") && (
                      <IconButton label="Изменить" onClick={() => setTypeForm({ id: t.id, name: t.name, type: String(t.type), ordering: String(t.ordering) })}>
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                    )}
                    {can("price.delete_inventorytype") && (
                      <IconButton label="Удалить" onClick={() => confirm(`Удалить тип «${t.name}» со всеми товарами?`) && delType.mutate(t.id)}>
                        <Trash2 className="h-4 w-4" />
                      </IconButton>
                    )}
                  </>
                }
              >
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {t.inventories.map((i: Inventory) => (
                    <li key={i.id} className="group flex items-center justify-between gap-2 px-5 py-2.5 text-sm">
                      <span className="truncate">{i.name}</span>
                      <span className="flex items-center gap-1">
                        <span className="font-medium tabular-nums">{money(i.price)}</span>
                        {can("price.change_inventory") && (
                          <IconButton
                            label="Изменить"
                            className="h-7 w-7 opacity-60 group-hover:opacity-100"
                            onClick={() => setInvForm({ id: i.id, name: i.name, type: t.id, price: i.price ?? { amount: 0, currency: "USD" } })}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </IconButton>
                        )}
                        {can("price.delete_inventory") && (
                          <IconButton label="Удалить" className="h-7 w-7 opacity-60 group-hover:opacity-100" onClick={() => confirm(`Удалить «${i.name}»?`) && delInv.mutate(i.id)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </IconButton>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                {can("price.add_inventory") && (
                  <button
                    onClick={() => setInvForm({ name: "", type: t.id, price: { amount: "", currency: meta?.default_currency ?? "USD" } })}
                    className="flex w-full items-center justify-center gap-1 border-t border-slate-100 py-2.5 text-sm font-medium text-brand-700 hover:bg-slate-50 dark:border-slate-800 dark:text-brand-300 dark:hover:bg-slate-800/50"
                  >
                    <Plus className="h-4 w-4" /> Товар
                  </button>
                )}
              </Card>
            ))}
          </div>
        </>
      )}

      <Modal
        open={!!typeForm}
        onClose={() => setTypeForm(null)}
        title={typeForm?.id ? "Изменить тип" : "Новый тип товара"}
        size="sm"
        footer={<Button loading={saveType.isPending} onClick={() => saveType.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Сохранить</Button>}
      >
        {typeForm && (
          <div className="space-y-4">
            <Field label="Название" error={errors.name}>
              <Input value={typeForm.name} onChange={(e) => setTypeForm({ ...typeForm, name: e.target.value })} />
            </Field>
            <Field label="Как считается">
              <Select value={typeForm.type} onChange={(e) => setTypeForm({ ...typeForm, type: e.target.value })}>
                {meta?.inventory_type_kinds.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="Порядок">
              <Input type="number" value={typeForm.ordering} onChange={(e) => setTypeForm({ ...typeForm, ordering: e.target.value })} />
            </Field>
          </div>
        )}
      </Modal>
      <Modal
        open={!!invForm}
        onClose={() => setInvForm(null)}
        title={invForm?.id ? "Изменить товар" : "Новый товар"}
        size="sm"
        footer={<Button loading={saveInv.isPending} onClick={() => saveInv.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Сохранить</Button>}
      >
        {invForm && (
          <div className="space-y-4">
            <Field label="Название" error={errors.name}>
              <Input value={invForm.name} onChange={(e) => setInvForm({ ...invForm, name: e.target.value })} />
            </Field>
            <Field label="Цена за единицу" error={errors.price}>
              <MoneyInput value={invForm.price} currencies={meta?.currencies} onChange={(price) => setInvForm({ ...invForm, price })} />
            </Field>
          </div>
        )}
      </Modal>
      <Modal
        open={!!objForm}
        onClose={() => setObjForm(null)}
        title="Новый объект"
        size="sm"
        footer={<Button loading={saveObj.isPending} onClick={() => saveObj.mutate()}>Сохранить</Button>}
      >
        {objForm && (
          <div className="space-y-4">
            <Field label="Название">
              <Input value={objForm.name} onChange={(e) => setObjForm({ ...objForm, name: e.target.value })} placeholder="Кухня, шкаф…" />
            </Field>
            <Field label="Единица">
              <Select value={objForm.count_name} onChange={(e) => setObjForm({ ...objForm, count_name: e.target.value })}>
                {meta?.count_names.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </Select>
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}
