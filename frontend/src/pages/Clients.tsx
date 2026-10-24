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
      <PageHeader title="Mijozlar" subtitle={`Jami: ${stats?.total ?? "…"}`} />
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card padded={false}>
          <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
            <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="F.I.Sh. yoki telefon" />
            <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
          </div>
          <DataTable
            rows={data?.results}
            loading={isFetching}
            rowKey={(r) => r.phone}
            onRowClick={(r) => navigate(`/clients/${encodeURIComponent(r.phone)}`)}
            columns={[
              { key: "fio", header: "F.I.Sh.", cell: (r) => <span className="font-medium">{r.fio}</span> },
              { key: "phone", header: "Telefon", cell: (r) => <PhoneLink value={r.phone} /> },
              { key: "orders", header: "Buyurtmalar", cell: (r) => r.orders_count ?? 0 },
              { key: "created", header: "Qo'shilgan", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
            ]}
          />
          <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
        <div className="space-y-4">
          <Card title="Yangi mijozlar">
            <TimelineChart data={stats?.timeline} height={180} />
          </Card>
          <Card title="Buyurtmalar bo'yicha top" padded={false}>
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
    success: "Saqlandi",
    invalidate: ["clients"],
    onSuccess: () => setEditing(false),
  });

  if (!client) return <PageLoader />;
  return (
    <div>
      <PageHeader
        back={<BackLink to="/clients">Mijozlar</BackLink>}
        title={client.fio}
        subtitle={<PhoneLink value={client.phone} />}
        actions={
          can("client.change_client") && (
            <Button variant="outline" icon={<Pencil className="h-4 w-4" />} onClick={() => (setFio(client.fio), setEditing(true))}>
              Tahrirlash
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={`Buyurtmalar · ${related?.orders.length ?? 0}`} padded={false}>
          {!related?.orders.length && <Empty title="Buyurtmalar yo'q" />}
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
        <Card title={`O'lchovlar · ${related?.meterings.length ?? 0}`} padded={false}>
          {!related?.meterings.length && <Empty title="O'lchovlar yo'q" />}
          {related?.meterings.map((m) => (
            <button key={m.id} onClick={() => navigate(`/meterings/${m.id}`)} className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
              <div>
                <div className="font-medium">{m.address || "Manzilsiz"}</div>
                <div className="muted text-xs">{dateTime(m.date_time)}</div>
              </div>
              <MeteringStatusBadge status={m.status} label={m.status_label} />
            </button>
          ))}
        </Card>
        <Card title={`Arizalar · ${related?.invoices.length ?? 0}`} padded={false}>
          {!related?.invoices.length && <Empty title="Arizalar yo'q" />}
          {related?.invoices.map((i) => (
            <button key={i.id} onClick={() => navigate(`/call-center?open=${i.id}`)} className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 text-left text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
              <div className="min-w-0">
                <div className="truncate font-medium">{i.desc || `Ariza #${i.id}`}</div>
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
        title="Mijozni tahrirlash"
        size="sm"
        footer={<Button loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>}
      >
        <Field label="F.I.Sh.">
          <Input value={fio} onChange={(e) => setFio(e.target.value)} />
        </Field>
      </Modal>
    </div>
  );
}
