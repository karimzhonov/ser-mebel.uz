import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, FileSpreadsheet, Pencil, Plus, Trash2, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, errorMessage } from "@/api/client";
import { useAction, useAll, useGet, useList } from "@/api/hooks";
import type { Calculation, InventoryType, ObjectType, Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { BackLink, DeadlinePill, FolderButton, OrderStatusBadge, PhoneLink } from "@/components/domain";
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
  Modal,
  PageHeader,
  PageLoader,
  Pagination,
  SearchInput,
  Segmented,
  Select,
  Textarea,
  Chip,
} from "@/components/ui";
import { date, money, num, phone } from "@/lib/format";
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
              { value: "true", label: "Arxiv" },
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

export function PriceDetailPage() {
  const { id } = useParams();
  const { data: p, isLoading } = useGet<Price>(`/prices/${id}/`);
  const { data: objects } = useAll<ObjectType>("object-types");
  const [tab, setTab] = useState<string>("");
  const [editing, setEditing] = useState<{ calc?: Calculation; objectType: ObjectType } | null>(null);
  const [confirmDone, setConfirmDone] = useState(false);
  const [descDraft, setDescDraft] = useState<string | null>(null);

  const inv = ["prices", "meterings", "orders"];
  const done = useAction(() => api.post(`/prices/${id}/done/`), {
    success: "Hisob-kitob bajarildi",
    invalidate: inv,
    onSuccess: () => setConfirmDone(false),
  });
  const remove = useAction((calcId: number) => api.delete(`/prices/${id}/calculations/${calcId}/`), {
    success: "O'chirildi",
    invalidate: inv,
  });
  const saveDesc = useAction(() => api.patch(`/prices/${id}/`, { desc: descDraft }), {
    success: "Saqlandi",
    invalidate: inv,
    onSuccess: () => setDescDraft(null),
  });

  if (isLoading || !p || !objects) return <PageLoader />;
  const currentTab = tab || String(objects[0]?.id ?? "");
  const currentObject = objects.find((o) => String(o.id) === currentTab);
  const calcs = (p.calculations ?? []).filter((c) => String(c.obj) === currentTab);
  const title = p.metering?.client.fio ?? p.desc ?? `Hisob-kitob #${p.id}`;
  const canEdit = !!p.actions?.edit;

  return (
    <div>
      <PageHeader
        back={<BackLink to="/prices">Narx hisoblash</BackLink>}
        title={title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {p.done ? <Badge tone="ok">Bajarildi</Badge> : <Badge tone="warn">Ishda</Badge>}
            {p.user_detail && <span>Mas'ul: {p.user_detail.name || phone(p.user_detail.phone)}</span>}
          </span>
        }
        actions={
          <>
            <FolderButton folderId={p.metering?.folder} label="O'lchov fayllari" />
            <FolderButton folderId={p.folder} label="Hisob-kitob fayllari" />
            <Button
              variant="outline"
              icon={<FileSpreadsheet className="h-4 w-4" />}
              onClick={() => downloadFile(`/prices/${id}/excel/`, `${title}.xlsx`).catch((e) => toast.error(errorMessage(e)))}
            >
              Excel
            </Button>
            {p.actions?.done && (
              <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirmDone(true)}>
                Bajarish
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Segmented
            value={currentTab}
            onChange={setTab}
            options={objects.map((o) => ({
              value: String(o.id),
              label: o.name,
              count: (p.calculations ?? []).filter((c) => c.obj === o.id).length,
            }))}
          />
          {!calcs.length && (
            <Card>
              <Empty title={`Hisob-kitoblar yo'q: ${currentObject?.name ?? ""}`} />
            </Card>
          )}
          {calcs.map((c) => (
            <Card
              key={c.id}
              title={c.name}
              actions={
                <>
                  <span className="text-sm font-semibold tabular-nums">{money(c.amount)}</span>
                  {canEdit && currentObject && (
                    <>
                      <IconButton label="Tahrirlash" onClick={() => setEditing({ calc: c, objectType: currentObject })}>
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="O'chirish" onClick={() => confirm(`«${c.name}» o'chirilsinmi?`) && remove.mutate(c.id)}>
                        <Trash2 className="h-4 w-4" />
                      </IconButton>
                    </>
                  )}
                </>
              }
              padded={false}
            >
              <div className="px-5 py-2 text-sm">
                <span className="muted">{currentObject?.count_label}: </span>
                <b className="tabular-nums">{num(c.count)}</b>
              </div>
              <table className="w-full text-sm">
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {c.items.map((it) => (
                    <tr key={it.id}>
                      <td className="muted px-5 py-2">{it.inventory_name}</td>
                      <td className="px-5 py-2 text-right tabular-nums">× {num(it.count)}</td>
                      <td className="px-5 py-2 text-right font-medium tabular-nums">{money(it.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))}
          {canEdit && currentObject && (
            <Button variant="outline" className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing({ objectType: currentObject })}>
              Hisob-kitob qo'shish: {currentObject.name}
            </Button>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <div className="muted text-xs font-medium uppercase tracking-wide">Jami</div>
            <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900 dark:text-white">{money(p.price, "$0")}</div>
            <div className="muted mt-1 text-xs">Summa shu o'lchovning buyurtmasiga o'tadi</div>
          </Card>
          {p.metering && (
            <Card title="O'lchov">
              <div className="space-y-1 text-sm">
                <Link to={`/meterings/${p.metering.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
                  {p.metering.client.fio}
                </Link>
                <div><PhoneLink value={p.metering.client.phone} /></div>
                <div className="muted">{p.metering.address}</div>
              </div>
            </Card>
          )}
          {p.order && (
            <Card title={`Buyurtma №${p.order.order_number}`}>
              <div className="flex flex-wrap gap-2">
                <OrderStatusBadge status={p.order.status} label={p.order.status_label} />
                <DeadlinePill deadline={p.order.deadline} />
              </div>
            </Card>
          )}
          <Card title="Tavsif">
            <Textarea
              disabled={!canEdit}
              value={descDraft ?? p.desc ?? ""}
              onChange={(e) => setDescDraft(e.target.value)}
            />
            {descDraft !== null && (
              <Button className="mt-3" size="sm" loading={saveDesc.isPending} onClick={() => saveDesc.mutate()}>
                Saqlash
              </Button>
            )}
          </Card>
        </div>
      </div>

      {editing && (
        <CalculationEditor
          priceId={Number(id)}
          objectType={editing.objectType}
          calc={editing.calc}
          onClose={() => setEditing(null)}
        />
      )}
      <Confirm
        open={confirmDone}
        onClose={() => setConfirmDone(false)}
        title="Hisob-kitob yakunlansinmi?"
        text="Hisob-kitob arxivga o'tadi."
        variant="success"
        loading={done.isPending}
        onConfirm={() => done.mutate()}
      />
    </div>
  );
}

type Line = { inventory: string; count: string };

function CalculationEditor({
  priceId,
  objectType,
  calc,
  onClose,
}: {
  priceId: number;
  objectType: ObjectType;
  calc?: Calculation;
  onClose: () => void;
}) {
  const { data: types } = useAll<InventoryType>("inventory-types", { obj: objectType.id });
  const [name, setName] = useState(calc?.name ?? "");
  const [count, setCount] = useState(calc?.count != null ? String(calc.count) : "");
  const [lines, setLines] = useState<Record<number, Line>>(() => {
    const init: Record<number, Line> = {};
    calc?.items.forEach((it) => (init[it.inventory_type] = { inventory: String(it.inventory), count: String(it.count) }));
    return init;
  });

  const total = useMemo(() => {
    if (!types) return 0;
    return types.reduce((sum, t) => {
      const line = lines[t.id];
      const inv = t.inventories.find((i) => String(i.id) === line?.inventory);
      if (!inv?.price) return sum;
      const qty = t.type === 1 ? Number(count || 0) : Number(line?.count || 0);
      return sum + qty * inv.price.amount;
    }, 0);
  }, [types, lines, count]);

  const save = useAction(
    () => {
      const body = {
        name,
        count: Number(count || 0),
        object_type: objectType.id,
        items: (types ?? []).map((t) => ({
          inventory_type: t.id,
          inventory: lines[t.id]?.inventory ? Number(lines[t.id].inventory) : null,
          count: t.type === 2 ? Number(lines[t.id]?.count || 0) : null,
        })),
      };
      return calc
        ? api.patch(`/prices/${priceId}/calculations/${calc.id}/`, body)
        : api.post(`/prices/${priceId}/calculations/`, body);
    },
    { success: "Hisob-kitob saqlandi", invalidate: ["prices", "meterings", "orders"], onSuccess: onClose },
  );

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={`${calc ? "Hisob-kitobni tahrirlash" : "Yangi hisob-kitob"} · ${objectType.name}`}
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <div className="text-sm">
            Jami: <b className="text-lg tabular-nums">{money({ amount: total, currency: "USD" })}</b>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
            <Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>Saqlash</Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nomi">
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Oshxona 1" />
        </Field>
        <Field label={objectType.count_label}>
          <Input type="number" inputMode="decimal" value={count} onChange={(e) => setCount(e.target.value)} />
        </Field>
      </div>
      <div className="mt-5 space-y-3">
        {!types && <PageLoader />}
        {types?.map((t) => {
          const line = lines[t.id] ?? { inventory: "", count: "" };
          const inv = t.inventories.find((i) => String(i.id) === line.inventory);
          const qty = t.type === 1 ? Number(count || 0) : Number(line.count || 0);
          return (
            <div key={t.id} className="grid items-end gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-700 sm:grid-cols-[1fr_120px_110px]">
              <Field label={t.name}>
                <Select value={line.inventory} onChange={(e) => setLines({ ...lines, [t.id]: { ...line, inventory: e.target.value } })}>
                  <option value="">— tanlanmagan —</option>
                  {t.inventories.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} — {money(i.price)}
                    </option>
                  ))}
                </Select>
              </Field>
              {t.type === 2 ? (
                <Field label="Soni">
                  <Input type="number" inputMode="decimal" value={line.count} onChange={(e) => setLines({ ...lines, [t.id]: { ...line, count: e.target.value } })} />
                </Field>
              ) : (
                <div className="muted pb-2 text-xs">× {objectType.count_label}</div>
              )}
              <div className="pb-2 text-right text-sm font-medium tabular-nums">
                {inv?.price ? money({ amount: qty * inv.price.amount, currency: inv.price.currency }) : "—"}
              </div>
            </div>
          );
        })}
        {types && !types.length && <Empty title="Bu obyekt uchun mahsulot turlari yo'q" text="Ularni «Mahsulotlar» bo'limida qo'shing." />}
      </div>
    </Modal>
  );
}
