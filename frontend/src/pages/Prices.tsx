import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, UserCheck } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useList } from "@/api/hooks";
import type { Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { DeadlinePill } from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import { Button, Card, Check, DataTable, Field, Modal, PageHeader, Pagination, SearchInput, Segmented, Textarea, Chip } from "@/components/ui";
import { date, money, phone } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

export function PricesPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ search: "", done: "false", has_metering: "", mine: "", date_from: "", date_to: "" });
  const { data, isFetching } = useList<Price>("prices", { ...state, page });
  const [creating, setCreating] = useState(false);
  const [desc, setDesc] = useState("");
  const create = useAction(() => api.post<Price>("/prices/", { desc }).then((r) => r.data), {
    success: "Hisob-kitob yaratildi",
    invalidate: ["prices"],
    onSuccess: (p) => navigate(`/prices/${p.id}`),
  });

  return (
    <div>
      <PageHeader
        title="Narx hisoblash"
        subtitle="O'lchovlar bo'yicha narx hisob-kitobi"
        actions={
          can("price.add_price") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              O'lchovsiz hisob-kitob
            </Button>
          )
        }
      />
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <Segmented
            value={state.done}
            onChange={(v) => set({ done: v })}
            options={[
              { value: "false", label: "Faol" },
              { value: "true", label: "Bajarilgan" },
              { value: "", label: "Barchasi" },
            ]}
          />
          <Segmented
            value={state.has_metering}
            onChange={(v) => set({ has_metering: v })}
            options={[
              { value: "", label: "Barchasi" },
              { value: "true", label: "O'lchovli" },
              { value: "false", label: "O'lchovsiz" },
            ]}
          />
          <Chip active={state.mine === "1"} onClick={() => set({ mine: state.mine === "1" ? "" : "1" })}>
            <UserCheck className="h-3.5 w-3.5" /> Mening vazifalarim
          </Chip>
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} />
          <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/prices/${r.id}`)}
          columns={[
            { key: "client", header: "O'lchov", cell: (r) => <span className="font-medium">{r.metering?.client.fio ?? r.desc ?? `Hisob-kitob #${r.id}`}</span> },
            { key: "user", header: "Mas'ul", cell: (r) => (r.user_detail ? r.user_detail.name || phone(r.user_detail.phone) : <span className="muted">—</span>) },
            { key: "price", header: "Summa", cell: (r) => <span className="font-semibold tabular-nums">{money(r.price)}</span> },
            { key: "done", header: "Holat", cell: (r) => <Check ok={r.done} label={r.done ? "Bajarildi" : "Ishda"} /> },
            {
              key: "order",
              header: "Buyurtma",
              cell: (r) => (r.order ? <span className="flex items-center gap-2">№{r.order.order_number} <DeadlinePill deadline={r.order.deadline} /></span> : <span className="muted">—</span>),
            },
            { key: "created", header: "Yaratilgan", cell: (r) => <span className="muted">{date(r.created_at)}</span> },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="O'lchovsiz hisob-kitob"
        size="sm"
        footer={<Button loading={create.isPending} onClick={() => create.mutate()}>Yaratish</Button>}
      >
        <Field label="Tavsif" hint="Masalan, mijoz ismi yoki obyekt">
          <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} />
        </Field>
      </Modal>
    </div>
  );
}

export { PriceDetailPage } from "./PriceDetail";
