import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, FolderOpen, Package, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import type { Design, DesignType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, BackLink, DeadlinePill, FolderButton, FolderModal, OrderStatusBadge, PhoneLink } from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import {
  Badge,
  Button,
  Card,
  Check,
  Confirm,
  DataTable,
  Empty,
  Field,
  IconButton,
  Input,
  KV,
  Modal,
  PageHeader,
  PageLoader,
  Pagination,
  SearchInput,
  Segmented,
} from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

export function DesignsPage() {
  const navigate = useNavigate();
  const { state, page, set } = useUrlState({ search: "", confirm: "false", date_from: "", date_to: "" });
  const { data, isFetching } = useList<Design>("designs", { ...state, page });
  return (
    <div>
      <PageHeader title="Дизайн" subtitle="Дизайн-проекты по замерам" />
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <Segmented
            value={state.confirm}
            onChange={(v) => set({ confirm: v })}
            options={[
              { value: "false", label: "Активные" },
              { value: "true", label: "Архив" },
              { value: "", label: "Все" },
            ]}
          />
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Клиент или телефон" />
          <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/designs/${r.id}`)}
          columns={[
            { key: "client", header: "Клиент", cell: (r) => <span className="font-medium">{r.metering.client.fio}</span> },
            { key: "variants", header: "Варианты", cell: (r) => r.types.map((t) => t.name).join(", ") || "—" },
            { key: "state", header: "Состояние", cell: (r) => <div className="flex gap-1"><Check ok={r.done} label="Готов" /><Check ok={r.confirm} label="Заказ" /></div> },
            {
              key: "order",
              header: "Заказ",
              cell: (r) =>
                r.order ? (
                  <div className="flex items-center gap-2">
                    <span className="font-medium">№{r.order.order_number}</span>
                    <DeadlinePill deadline={r.order.deadline} />
                  </div>
                ) : (
                  <span className="muted">—</span>
                ),
            },
            { key: "created", header: "Создан", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
    </div>
  );
}

export function DesignDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: d, isLoading } = useGet<Design>(`/designs/${id}/`);
  const [confirmDone, setConfirmDone] = useState(false);
  const [variant, setVariant] = useState<{ id?: number; name: string } | null>(null);
  const [folder, setFolder] = useState<number | null>(null);

  const inv = ["designs", "meterings", "dashboard"];
  const done = useAction(() => api.post(`/designs/${id}/done/`), {
    success: "Дизайн выполнен — call-center уведомлён",
    invalidate: inv,
    onSuccess: () => setConfirmDone(false),
  });
  const saveVariant = useAction(
    () =>
      variant?.id
        ? api.patch(`/design-types/${variant.id}/`, { name: variant.name })
        : api.post(`/designs/${id}/types/`, { name: variant?.name }),
    { success: "Сохранено", invalidate: inv, onSuccess: () => setVariant(null) },
  );
  const removeVariant = useAction((typeId: number) => api.delete(`/design-types/${typeId}/`), {
    success: "Удалено",
    invalidate: inv,
  });

  if (isLoading || !d) return <PageLoader />;
  const m = d.metering;
  return (
    <div>
      <PageHeader
        back={<BackLink to="/designs">Дизайн</BackLink>}
        title={m.client.fio}
        subtitle={
          <span className="flex gap-2">
            {d.done ? <Badge tone="ok">Выполнен</Badge> : <Badge tone="warn">В работе</Badge>}
            {d.confirm && <Badge tone="primary">Заказ оформлен</Badge>}
          </span>
        }
        actions={
          <>
            <FolderButton folderId={m.folder} label="Файлы замера" />
            {d.actions.done && (
              <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirmDone(true)}>
                Выполнить дизайн
              </Button>
            )}
            {d.actions.create_order && (
              <Button
                icon={<Package className="h-4 w-4" />}
                onClick={() => navigate(`/orders/new?metering=${m.id}&design=${d.id}`)}
              >
                Создать заказ
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Варианты дизайна"
          padded={false}
          actions={
            d.actions.add_type && (
              <Button size="sm" variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setVariant({ name: `Дизайн-${d.types.length + 1}` })}>
                Вариант
              </Button>
            )
          }
        >
          {!d.types.length && <Empty title="Нет вариантов" />}
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {d.types.map((t: DesignType) => (
              <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <div>
                  <div className="font-medium">{t.name}</div>
                  <div className="muted text-xs">{dateTime(t.created_at)}</div>
                </div>
                <div className="flex items-center gap-1">
                  {t.folder && (
                    <Button size="sm" variant="outline" icon={<FolderOpen className="h-4 w-4" />} onClick={() => setFolder(t.folder)}>
                      Файлы
                    </Button>
                  )}
                  {can("design.change_designtype") && (
                    <IconButton label="Переименовать" onClick={() => setVariant({ id: t.id, name: t.name })}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                  {can("design.delete_designtype") && d.types.length > 1 && (
                    <IconButton label="Удалить" onClick={() => confirm(`Удалить «${t.name}»?`) && removeVariant.mutate(t.id)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-4">
          <Card title="Замер">
            <KV
              items={[
                ["Клиент", can("metering.view_metering") ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/meterings/${m.id}`}>{m.client.fio}</Link> : m.client.fio],
                ["Телефон", <PhoneLink value={m.client.phone} />],
                ["Адрес", <AddressLink address={m.address} link={m.address_link} />],
                ["Дата замера", dateTime(m.date_time)],
              ]}
            />
          </Card>
          {d.order && (
            <Card title={`Заказ №${d.order.order_number}`}>
              <div className="flex flex-wrap gap-2">
                <OrderStatusBadge status={d.order.status} label={d.order.status_label} />
                <DeadlinePill deadline={d.order.deadline} />
              </div>
              <Link to={`/orders/${d.order.id}`} className="mt-3 inline-block text-sm text-brand-700 hover:underline dark:text-brand-300">
                Открыть заказ →
              </Link>
            </Card>
          )}
        </div>
      </div>

      <Confirm
        open={confirmDone}
        onClose={() => setConfirmDone(false)}
        title="Дизайн готов?"
        text="Call-center получит уведомление, что дизайн готов."
        variant="success"
        loading={done.isPending}
        onConfirm={() => done.mutate()}
      />
      <Modal
        open={!!variant}
        onClose={() => setVariant(null)}
        title={variant?.id ? "Переименовать вариант" : "Новый вариант"}
        size="sm"
        footer={<Button loading={saveVariant.isPending} onClick={() => saveVariant.mutate()}>Сохранить</Button>}
      >
        <Field label="Название">
          <Input value={variant?.name ?? ""} onChange={(e) => setVariant(variant && { ...variant, name: e.target.value })} />
        </Field>
      </Modal>
      {folder && <FolderModal folderId={folder} onClose={() => setFolder(null)} />}
    </div>
  );
}
