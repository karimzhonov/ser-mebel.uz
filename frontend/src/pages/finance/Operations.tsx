import { useState } from "react";
import { ArrowLeftRight, Minus, Paperclip, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Badge, Button, Card, DataTable, IconButton, PageHeader, Pagination, SearchInput, Segmented, Select, StatTile } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { CatLabel, OperationModal, ReceiptModal, TransferModal, som, useCategories, useFinMe, useMembers, usd } from "./shared";
import type { Operation } from "./types";

export default function FinanceOperationsPage() {
  const { can } = useAuth();
  const { data: me } = useFinMe();
  const { data: members } = useMembers({}, !!me?.view_all);
  const { data: cats } = useCategories();
  const { state, page, set } = useUrlState({
    date_from: monthStartISO(),
    date_to: iso(new Date()),
    kind: "",
    member: "",
    category: "",
    search: "",
    deleted: "",
    order_ref: "",
  });
  const params = { ...state, page };
  const { data, isFetching } = useList<Operation>("finance/operations", params);
  const { data: stats } = useGet<{ income: number; expense: number; count: number }>("/finance/operations/stats/", state);
  const [edit, setEdit] = useState<Operation | "income" | "expense" | null>(null);
  const [receipt, setReceipt] = useState<Operation | null>(null);
  const [transfer, setTransfer] = useState(false);
  const remove = useAction((id: number) => api.delete(`/finance/operations/${id}/`), { success: "O'chirildi", invalidate: ["finance"] });
  const restore = useAction((id: number) => api.post(`/finance/operations/${id}/restore/`), { success: "Tiklandi", invalidate: ["finance"] });
  const canAdd = can("accounting.add_operation");
  const canChange = can("accounting.change_operation");
  const canDelete = can("accounting.delete_operation");

  return (
    <div>
      <PageHeader
        title="Amallar"
        subtitle="Telegram botda, saytda kiritilgan va Google jadvaldan ko'chirilgan barcha kirim-chiqimlar"
        actions={
          canAdd && (
            <>
              {me?.view_all && (
                <Button variant="outline" icon={<ArrowLeftRight className="h-4 w-4" />} onClick={() => setTransfer(true)}>
                  O'tkazma
                </Button>
              )}
              <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit("income")}>
                Kirim
              </Button>
              <Button icon={<Minus className="h-4 w-4" />} onClick={() => setEdit("expense")}>
                Chiqim
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        <Segmented
          value={state.kind}
          onChange={(kind) => set({ kind })}
          options={[
            { value: "", label: "Hammasi" },
            { value: "expense", label: "🔴 Chiqim" },
            { value: "income", label: "🟢 Kirim" },
          ]}
        />
      </div>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <StatTile label="🟢 Kirim" value={som(stats?.income ?? 0)} tone="ok" />
        <StatTile label="🔴 Chiqim" value={som(-(stats?.expense ?? 0))} tone="danger" />
        <StatTile label="Amallar" value={stats?.count ?? 0} tone="idle" />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Izoh, ishchi, buyurtma ID, xodim…" />
          {me?.view_all && (
            <Select className="lg:w-48" value={state.member} onChange={(e) => set({ member: e.target.value })}>
              <option value="">Barcha xodimlar</option>
              {members?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </Select>
          )}
          <Select className="lg:w-56" value={state.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">Barcha kategoriyalar</option>
            {cats?.map((c) => (
              <option key={c.code} value={c.code}>
                {c.emoji} {c.name}
              </option>
            ))}
          </Select>
          <Select className="lg:w-40" value={state.deleted} onChange={(e) => set({ deleted: e.target.value })}>
            <option value="">Faol yozuvlar</option>
            <option value="1">O'chirilganlar</option>
            <option value="all">Hammasi</option>
          </Select>
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          rowClassName={(r) => (r.is_deleted ? "opacity-50 line-through" : undefined)}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="muted tabular-nums">#{r.number}</span> },
            {
              key: "d",
              header: "Sana",
              cell: (r) => (
                <span className="whitespace-nowrap">
                  {date(r.date)} <span className="muted">{r.time?.slice(0, 5)}</span>
                </span>
              ),
            },
            { key: "m", header: "Xodim", cell: (r) => r.member_detail.name },
            { key: "c", header: "Kategoriya", cell: (r) => <CatLabel c={r.category_detail} /> },
            {
              key: "a",
              header: "Summa",
              cell: (r) => (
                <span className={`whitespace-nowrap font-semibold tabular-nums ${r.kind === "income" ? "text-emerald-600" : "text-rose-600"}`}>
                  {som(r.kind === "income" ? r.amount : -Number(r.amount), true)}
                  {r.currency === "USD" && <span className="muted ml-1 text-xs font-normal">({usd(r.orig_amount)})</span>}
                </span>
              ),
            },
            {
              key: "o",
              header: "Buyurtma / kimga",
              cell: (r) => (
                <span className="text-sm">
                  {r.order_ref && <span className="font-medium">🧾 {r.order_ref} </span>}
                  {r.worker && <span className="muted">👷 {r.worker}</span>}
                  {r.pay_type && <Badge tone="info" className="ml-1">{r.pay_type}</Badge>}
                </span>
              ),
              hideOnMobile: true,
            },
            { key: "i", header: "Izoh", cell: (r) => <span className="line-clamp-2 max-w-xs text-sm">{r.comment || "—"}</span>, hideOnMobile: true },
            {
              key: "s",
              header: "Manba",
              cell: (r) => (
                <span className="muted whitespace-nowrap text-xs">
                  {r.source === "bot" ? "🤖" : r.source === "site" ? "🌐" : "📄"} {r.author_detail?.name || r.site_user_detail?.name || r.source_label}
                  {r.pair_number && <span className="ml-1">↔ #{r.pair_number}</span>}
                </span>
              ),
              hideOnMobile: true,
            },
            {
              key: "x",
              header: "",
              cell: (r) => (
                <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  {r.has_receipt && (
                    <IconButton label="Chek" onClick={() => setReceipt(r)}>
                      <Paperclip className="h-4 w-4" />
                    </IconButton>
                  )}
                  {!r.is_deleted && canChange && (
                    <IconButton label="Tahrirlash" onClick={() => setEdit(r)}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                  {!r.is_deleted && canDelete && (
                    <IconButton
                      label="O'chirish"
                      onClick={() => confirm(`#${r.number} o'chirilsinmi?${r.pair_number ? " (o'tkazmaning ikkala tomoni)" : ""}`) && remove.mutate(r.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  )}
                  {r.is_deleted && canDelete && (
                    <IconButton label="Tiklash" onClick={() => restore.mutate(r.id)}>
                      <RotateCcw className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              ),
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {edit && (
        <OperationModal
          op={typeof edit === "string" ? null : edit}
          defaultKind={typeof edit === "string" ? edit : undefined}
          defaultMember={state.member ? Number(state.member) : me?.member?.id}
          onClose={() => setEdit(null)}
        />
      )}
      {receipt && <ReceiptModal op={receipt} onClose={() => setReceipt(null)} />}
      {transfer && <TransferModal onClose={() => setTransfer(false)} />}
    </div>
  );
}
