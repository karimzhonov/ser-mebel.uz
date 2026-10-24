import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2, Plus } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useAll, useGet, useList, useMeta } from "@/api/hooks";
import type { PainterType, ProductionItem, UserShort } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, DeadlinePill, FolderButton, OrderStatusBadge, PhoneLink, ROW_TONE } from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import {
  Button,
  Card,
  Check,
  Confirm,
  DataTable,
  Empty,
  Field,
  Input,
  KV,
  Modal,
  MoneyInput,
  PageHeader,
  Pagination,
  SearchInput,
  Segmented,
  Select,
  StatTile,
} from "@/components/ui";
import { date, money, num, phone } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

type Kind = "detailing" | "rover" | "painter" | "assembly";
const CONFIG: Record<Kind, { title: string; resource: string; doneField: string; subtitle: string }> = {
  detailing: { title: "Detalirovka / Ishlab chiqarish", resource: "detailings", doneField: "done", subtitle: "Detalirovka va xomashyo buyurtmasi" },
  rover: { title: "Rover", resource: "rovers", doneField: "done", subtitle: "Frezerlash" },
  painter: { title: "Molyar", resource: "painters", doneField: "done", subtitle: "Bo'yash" },
  assembly: { title: "Yig'ish / O'rnatish", resource: "assemblies", doneField: "installing_done", subtitle: "Mijozda yig'ish va o'rnatish" },
};

export default function ProductionPage() {
  const kind = (useParams().kind ?? "detailing") as Kind;
  const cfg = CONFIG[kind];
  if (!cfg) return <Empty title="Bo'lim topilmadi" />;
  return <ProductionList key={kind} kind={kind} />;
}

function ProductionList({ kind }: { kind: Kind }) {
  const cfg = CONFIG[kind];
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ search: "", [cfg.doneField]: "false", date_from: "", date_to: "", user: "" } as Record<string, string>);
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");
  const { data, isFetching } = useList<ProductionItem>(cfg.resource, { ...state, page });
  const { data: stats } = useGet<Record<string, number>>(`/${cfg.resource}/stats/`, { search: state.search, date_from: state.date_from, date_to: state.date_to });
  const isManager = can("assembly.manager");
  const { data: assemblers } = useGet<UserShort[]>(kind === "assembly" && isManager ? "/assemblies/assemblers/" : null);
  const [types, setTypes] = useState(false);

  return (
    <div>
      <PageHeader
        title={cfg.title}
        subtitle={cfg.subtitle}
        actions={
          kind === "painter" &&
          can("painter.view_paintertype") && (
            <Button variant="outline" onClick={() => setTypes(true)}>
              Bo'yash turlari
            </Button>
          )
        }
      />
      <div className="mb-4 grid grid-cols-3 gap-3">
        <StatTile label="Jami" value={stats?.total ?? "…"} tone="primary" />
        <StatTile label="Ishda" value={stats?.not_done ?? "…"} tone="warn" />
        <StatTile label="Bajarildi" value={(kind === "assembly" ? stats?.installing_done : stats?.done) ?? "…"} tone="ok" />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <Segmented
            value={state[cfg.doneField]}
            onChange={(v) => set({ [cfg.doneField]: v })}
            options={[
              { value: "false", label: "Faol" },
              { value: "true", label: "Arxiv" },
              { value: "", label: "Barchasi" },
            ]}
          />
          <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Buyurtma №, mijoz, telefon" />
          {assemblers && (
            <Select className="lg:w-48" value={state.user} onChange={(e) => set({ user: e.target.value })}>
              <option value="">Barcha yig'uvchilar</option>
              {assemblers.map((u) => (
                <option key={u.id} value={u.id}>{u.name || phone(u.phone)}</option>
              ))}
            </Select>
          )}
          <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={(r) => setSearchParams((p) => (p.set("open", String(r.id)), p))}
          rowClassName={(r) => (r.done ? undefined : ROW_TONE[r.order.deadline.level])}
          columns={[
            { key: "n", header: "Buyurtma", cell: (r) => <span className="font-semibold">№{r.order.order_number}</span> },
            { key: "client", header: "Mijoz", cell: (r) => r.order.client?.fio ?? "—" },
            { key: "status", header: "Buyurtma holati", cell: (r) => <OrderStatusBadge status={r.order.status} label={r.order.status_label} /> },
            { key: "deadline", header: "Muddat", cell: (r) => <DeadlinePill deadline={r.order.deadline} /> },
            ...(kind === "assembly"
              ? [{ key: "user", header: "Yig'uvchi", cell: (r: ProductionItem) => r.user_detail?.name || (r.user_detail ? phone(r.user_detail.phone) : <span className="muted">—</span>) }]
              : []),
            ...(kind === "painter" ? [{ key: "type", header: "Tur", cell: (r: ProductionItem) => r.type_detail?.name ?? <span className="muted">—</span> }] : []),
            { key: "square", header: "Maydon", cell: (r) => <span className="tabular-nums">{num(r.square)}</span> },
            ...(kind !== "detailing" ? [{ key: "price", header: "Narx", cell: (r: ProductionItem) => <span className="tabular-nums">{money(r.price)}</span> }] : []),
            {
              key: "done",
              header: "Bajarildi",
              cell: (r) =>
                kind === "assembly" ? (
                  <div className="flex gap-1"><Check ok={r.done} label="Yig'." /><Check ok={!!r.installing_done} label="O'rn." /></div>
                ) : (
                  <Check ok={r.done} />
                ),
            },
          ]}
          mobileCard={(r) => (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold">№{r.order.order_number} · {r.order.client?.fio}</span>
                <Check ok={kind === "assembly" ? !!r.installing_done : r.done} />
              </div>
              <div className="flex items-center justify-between text-sm">
                <DeadlinePill deadline={r.order.deadline} />
                <span className="muted">{num(r.square)} m²</span>
              </div>
            </div>
          )}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>

      {openId && (
        <ProductionModal
          kind={kind}
          id={Number(openId)}
          assemblers={assemblers}
          onClose={() => setSearchParams((p) => (p.delete("open"), p))}
        />
      )}
      {types && <PainterTypesModal onClose={() => setTypes(false)} />}
    </div>
  );
}

function ProductionModal({
  kind,
  id,
  assemblers,
  onClose,
}: {
  kind: Kind;
  id: number;
  assemblers?: UserShort[];
  onClose: () => void;
}) {
  const cfg = CONFIG[kind];
  const { data: item } = useGet<ProductionItem>(`/${cfg.resource}/${id}/`);
  const { data: painterTypes } = useAll<PainterType>("painter-types", {}, kind === "painter");
  const [squares, setSquares] = useState({ square: "", painter_square: "", rover_square: "" });
  const [confirm, setConfirm] = useState<null | string>(null);
  useEffect(() => {
    if (item && kind === "detailing")
      setSquares({
        square: String(item.square ?? 0),
        painter_square: String(item.painter_square ?? 0),
        rover_square: String(item.rover_square ?? 0),
      });
  }, [item, kind]);

  const inv = [cfg.resource, "orders", "dashboard", "assemblies", "rovers", "painters"];
  const patch = useAction((body: Record<string, unknown>) => api.patch(`/${cfg.resource}/${id}/`, body), {
    success: "Saqlandi",
    invalidate: inv,
  });
  const run = useAction((path: string) => api.post(`/${cfg.resource}/${id}/${path}/`), {
    success: "Tayyor",
    invalidate: inv,
    onSuccess: () => setConfirm(null),
  });

  if (!item) return null;
  const o = item.order;
  const a = item.actions;

  return (
    <Modal open onClose={onClose} title={`${cfg.title} · buyurtma №${o.order_number}`} size="lg">
      <div className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <OrderStatusBadge status={o.status} label={o.status_label} />
          <DeadlinePill deadline={o.deadline} />
          <FolderButton folderId={item.folder} label="Bosqich fayllari" />
          <FolderButton folderId={o.folder} label="Buyurtma fayllari" />
        </div>
        <KV
          items={[
            ["Mijoz", o.client?.fio ?? "—"],
            ["Telefon", <PhoneLink value={o.client?.phone} />],
            ["Manzil", <AddressLink address={o.address} link={o.address_link} />],
            ["Topshirish sanasi", date(o.end_date, "ko'rsatilmagan")],
            ["Buyurtma", <Link to={`/orders/${o.id}`} className="text-brand-700 hover:underline dark:text-brand-300">Buyurtmani ochish →</Link>],
            ...(kind !== "detailing" ? ([["Maydon", num(item.square)], ["Narx", money(item.price)]] as [string, string][]) : []),
          ]}
        />

        {kind === "detailing" && (
          <div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Maydon (yig'ish)">
                <Input type="number" disabled={!a.edit} value={squares.square} onChange={(e) => setSquares({ ...squares, square: e.target.value })} />
              </Field>
              <Field label="Bo'yash maydoni">
                <Input type="number" disabled={!a.edit} value={squares.painter_square} onChange={(e) => setSquares({ ...squares, painter_square: e.target.value })} />
              </Field>
              <Field label="Rover maydoni">
                <Input type="number" disabled={!a.edit} value={squares.rover_square} onChange={(e) => setSquares({ ...squares, rover_square: e.target.value })} />
              </Field>
            </div>
            <p className="muted mt-2 text-xs">Saqlanganda Yig'ish, Molyar va Rover maydon bo'yicha narxi bilan avtomatik yaratiladi/yangilanadi.</p>
            {a.edit && (
              <Button
                className="mt-3"
                variant="outline"
                loading={patch.isPending}
                onClick={() =>
                  patch.mutate({
                    square: Number(squares.square || 0),
                    painter_square: Number(squares.painter_square || 0),
                    rover_square: Number(squares.rover_square || 0),
                  })
                }
              >
                Maydonlarni saqlash
              </Button>
            )}
          </div>
        )}

        {kind === "painter" && (
          <Field label="Bo'yash turi" hint="Tanlanganda molyarga xabar boradi, narx maydon bo'yicha qayta hisoblanadi">
            <Select disabled={!a.edit} value={item.type ?? ""} onChange={(e) => patch.mutate({ type: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— tayinlanmagan —</option>
              {painterTypes?.map((t) => (
                <option key={t.id} value={t.id}>{t.name} — {money(t.price)}/m²</option>
              ))}
            </Select>
          </Field>
        )}

        {kind === "assembly" && (
          <Field label="Yig'uvchi">
            <Select disabled={!a.edit} value={item.user ?? ""} onChange={(e) => patch.mutate({ user: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— tayinlanmagan —</option>
              {(assemblers ?? (item.user_detail ? [item.user_detail] : [])).map((u) => (
                <option key={u.id} value={u.id}>{u.name || phone(u.phone)}</option>
              ))}
            </Select>
          </Field>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
          {a.done && (
            <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirm("done")}>
              {kind === "assembly" ? "Yig'ish bajarildi" : kind === "detailing" ? "Detalirovka bajarildi" : "Bajarildi"}
            </Button>
          )}
          {a.installing_done && (
            <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirm("installing-done")}>
              O'rnatish bajarildi
            </Button>
          )}
        </div>
      </div>
      <Confirm
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title="Bajarilganini tasdiqlang"
        text={
          confirm === "installing-done"
            ? "Buyurtma «Tayyor» holatini oladi."
            : kind === "detailing"
              ? "Buyurtma «Xomashyo buyurtmasi» bosqichiga o'tadi."
              : kind === "assembly"
                ? "Buyurtma «O'rnatish» bosqichiga o'tadi."
                : "Bosqich bajarilgan deb belgilanadi."
        }
        variant="success"
        loading={run.isPending}
        onConfirm={() => confirm && run.mutate(confirm)}
      />
    </Modal>
  );
}

function PainterTypesModal({ onClose }: { onClose: () => void }) {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { data: types } = useAll<PainterType>("painter-types");
  const { user } = useAuth();
  const { data: users } = useList<UserShort>("users", { page_size: 200 }, !!user?.is_superuser);
  const [form, setForm] = useState<{ id?: number; name: string; price: { amount: number | string; currency: string }; user: string } | null>(null);
  const save = useAction(
    () => {
      const body = { name: form!.name, price: form!.price, user: form!.user ? Number(form!.user) : null };
      return form!.id ? api.patch(`/painter-types/${form!.id}/`, body) : api.post("/painter-types/", body);
    },
    { success: "Saqlandi", invalidate: ["painter-types"], onSuccess: () => setForm(null) },
  );
  return (
    <Modal open onClose={onClose} title="Bo'yash turlari" size="lg">
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {types?.map((t) => (
          <li key={t.id} className="flex items-center justify-between py-2.5 text-sm">
            <div>
              <div className="font-medium">{t.name}</div>
              <div className="muted text-xs">{t.user_detail ? t.user_detail.name || phone(t.user_detail.phone) : "ijrochisiz"}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="tabular-nums">{money(t.price)}</span>
              {can("painter.change_paintertype") && (
                <Button size="sm" variant="ghost" onClick={() => setForm({ id: t.id, name: t.name, price: t.price, user: t.user ? String(t.user) : "" })}>
                  Tahrirlash
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {can("painter.add_paintertype") && !form && (
        <Button className="mt-3" variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setForm({ name: "", price: { amount: "", currency: meta?.default_currency ?? "USD" }, user: "" })}>
          Tur qo'shish
        </Button>
      )}
      {form && (
        <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700 sm:grid-cols-3">
          <Field label="Nomi"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="1 m² narxi"><MoneyInput value={form.price} currencies={meta?.currencies} onChange={(price) => setForm({ ...form, price })} /></Field>
          <Field label="Molyar" hint={users ? undefined : "Ro'yxat administratorga ochiq"}>
            <Select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })}>
              <option value="">—</option>
              {users?.results.map((u) => <option key={u.id} value={u.id}>{u.name || phone(u.phone)}</option>)}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 sm:col-span-3">
            <Button variant="ghost" onClick={() => setForm(null)}>Bekor qilish</Button>
            <Button loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
