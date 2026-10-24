import { Link, useNavigate, useParams } from "react-router-dom";
import { useState } from "react";
import { Pencil } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import type { Client, Invoice, Metering, Order } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  BackLink,
  DeadlinePill,
  MeteringStatusBadge,
  OrderStatusBadge,
  PhoneLink,
  SolutionBadge,
  TimelineChart,
} from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import { Button, Card, DataTable, Empty, Field, Input, Modal, PageHeader, PageLoader, Pagination, SearchInput } from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

export function ClientsPage() {
  const navigate = useNavigate();
  const { state, page, set } = useUrlState({ search: "", date_from: "", date_to: "", ordering: "" });
  const { data, isFetching } = useList<Client>("clients", { ...state, page });
  const { data: stats } = useGet<{ total: number; top: Client[]; timeline: { date: string; value: number }[] }>(
    "/clients/stats/",
    { search: state.search, date_from: state.date_from, date_to: state.date_to },
  );

  return (
    <div>
      <PageHeader title="Клиенты" subtitle={`Всего: ${stats?.total ?? "…"}`} />
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card padded={false}>
          <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
            <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="ФИО или телефон" />
            <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
          </div>
          <DataTable
            rows={data?.results}
            loading={isFetching}
            rowKey={(r) => r.phone}
            onRowClick={(r) => navigate(`/clients/${encodeURIComponent(r.phone)}`)}
            columns={[
              { key: "fio", header: "ФИО", cell: (r) => <span className="font-medium">{r.fio}</span> },
              { key: "phone", header: "Телефон", cell: (r) => <PhoneLink value={r.phone} /> },
              { key: "orders", header: "Заказов", cell: (r) => r.orders_count ?? 0 },
              { key: "created", header: "Добавлен", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
            ]}
          />
          <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
        <div className="space-y-4">
          <Card title="Новые клиенты">
            <TimelineChart data={stats?.timeline} height={180} />
          </Card>
          <Card title="Топ по заказам" padded={false}>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {stats?.top.map((c) => (
                <li key={c.phone}>
                  <Link to={`/clients/${encodeURIComponent(c.phone)}`} className="flex items-center justify-between px-5 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="truncate">{c.fio}</span>
                    <span className="font-semibold tabular-nums">{c.orders_count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function ClientDetailPage() {
  const { phone = "" } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const { data: client } = useGet<Client>(`/clients/${encodeURIComponent(phone)}/`);
  const { data: related } = useGet<{ invoices: Invoice[]; meterings: Metering[]; orders: Order[] }>(
    `/clients/${encodeURIComponent(phone)}/related/`,
  );
  const [editing, setEditing] = useState(false);
  const [fio, setFio] = useState("");
  const save = useAction(() => api.patch(`/clients/${encodeURIComponent(phone)}/`, { fio }), {
    success: "Сохранено",
    invalidate: ["clients"],
    onSuccess: () => setEditing(false),
  });

  if (!client) return <PageLoader />;
  return (
    <div>
      <PageHeader
        back={<BackLink to="/clients">Клиенты</BackLink>}
        title={client.fio}
        subtitle={<PhoneLink value={client.phone} />}
        actions={
          can("client.change_client") && (
            <Button variant="outline" icon={<Pencil className="h-4 w-4" />} onClick={() => (setFio(client.fio), setEditing(true))}>
              Изменить
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={`Заказы · ${related?.orders.length ?? 0}`} padded={false}>
          {!related?.orders.length && <Empty title="Нет заказов" />}
          {related?.orders.map((o) => (
            <button key={o.id} onClick={() => navigate(`/orders/${o.id}`)} className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
              <div>
                <div className="font-medium">№{o.order_number}</div>
                <div className="muted text-xs">{date(o.reception_date)}</div>
              </div>
              <div className="flex flex-col items-end gap-1">
                <OrderStatusBadge status={o.status} label={o.status_label} />
                <DeadlinePill deadline={o.deadline} />
              </div>
            </button>
          ))}
        </Card>
        <Card title={`Замеры · ${related?.meterings.length ?? 0}`} padded={false}>
          {!related?.meterings.length && <Empty title="Нет замеров" />}
          {related?.meterings.map((m) => (
            <button key={m.id} onClick={() => navigate(`/meterings/${m.id}`)} className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
              <div>
                <div className="font-medium">{m.address || "Без адреса"}</div>
                <div className="muted text-xs">{dateTime(m.date_time)}</div>
              </div>
              <MeteringStatusBadge status={m.status} label={m.status_label} />
            </button>
          ))}
        </Card>
        <Card title={`Заявки · ${related?.invoices.length ?? 0}`} padded={false}>
          {!related?.invoices.length && <Empty title="Нет заявок" />}
          {related?.invoices.map((i) => (
            <button key={i.id} onClick={() => navigate(`/call-center?open=${i.id}`)} className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
              <div className="min-w-0">
                <div className="truncate font-medium">{i.desc || `Заявка #${i.id}`}</div>
                <div className="muted text-xs">{dateTime(i.create_date)}</div>
              </div>
              <SolutionBadge solution={i.solution} label={i.solution_label} />
            </button>
          ))}
        </Card>
      </div>
      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Изменить клиента"
        size="sm"
        footer={<Button loading={save.isPending} onClick={() => save.mutate()}>Сохранить</Button>}
      >
        <Field label="ФИО">
          <Input value={fio} onChange={(e) => setFio(e.target.value)} />
        </Field>
      </Modal>
    </div>
  );
}
