import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2, Plus } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList, useMeta } from "@/api/hooks";
import type { PainterType, ProductionItem, UserShort } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, DeadlinePill, FolderButton, OrderStatusBadge, PhoneLink, ROW_TONE } from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import { DetailingDue, DetailingDueModal } from "@/components/DetailingDue";
import { DueLabel, DueModal } from "@/components/DueDate";
import { RoverDueLabel, RoverDueModal } from "@/components/RoverDue";
import {
  Badge,
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
  Textarea,
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
  const { state, page, set } = useUrlState({ search: "", [cfg.doneField]: "false", date_from: "", date_to: "", user: "", state: "" } as Record<string, string>);
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");
  const { data, isFetching } = useList<ProductionItem>(cfg.resource, { ...state, page });
  const { data: stats } = useGet<Record<string, number>>(`/${cfg.resource}/stats/`, { search: state.search, date_from: state.date_from, date_to: state.date_to });
  const isManager = can("assembly.manager") || can("oauth.user_production_head");
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
      <div className={`mb-4 grid gap-3 ${kind === "rover" ? "grid-cols-2 sm:grid-cols-4" : kind === "assembly" ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3"}`}>
        <StatTile label="Jami" value={stats?.total ?? "…"} tone="primary" />
        <StatTile label="Ishda" value={stats?.not_done ?? "…"} tone="warn" />
        {(kind === "rover" || kind === "assembly") && <StatTile label="Tekshiruvda" value={stats?.checking ?? "…"} tone="warn" />}
        <StatTile label="Bajarildi" value={(kind === "assembly" ? stats?.installing_done : stats?.done) ?? "…"} tone="ok" />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <Segmented
            value={(kind === "rover" || kind === "assembly") && state.state ? state.state : state[cfg.doneField]}
            onChange={(v) =>
              kind === "rover" || kind === "assembly"
                ? v === "checking"
                  ? set({ [cfg.doneField]: "", state: "checking" })
                  : set({ [cfg.doneField]: v, state: "" })
                : set({ [cfg.doneField]: v })
            }
            options={[
              { value: "false", label: "Faol" },
              ...(kind === "rover" || kind === "assembly" ? [{ value: "checking", label: "Tekshiruvda" }] : []),
              { value: "true", label: "Bajarilgan" },
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
          rowClassName={(r) => (r.done ? undefined : kind === "rover" ? (r.overdue ? ROW_TONE.danger : undefined) : ROW_TONE[r.order.deadline.level])}
          columns={[
            { key: "n", header: "Buyurtma", cell: (r) => <span className="font-semibold">№{r.order.order_number}</span> },
            { key: "client", header: "Mijoz", cell: (r) => r.order.client?.fio ?? "—" },
            { key: "status", header: "Buyurtma holati", cell: (r) => <OrderStatusBadge status={r.order.status} label={r.order.status_label} /> },
            ...(kind === "rover" ? [] : [{ key: "deadline", header: "Muddat", cell: (r: ProductionItem) => <DeadlinePill deadline={r.order.deadline} /> }]),
            ...(kind === "detailing"
              ? [{ key: "due_at", header: "Detalirovka muddati", cell: (r: ProductionItem) => <DetailingDue dueAt={r.due_at} done={r.done} /> }]
              : []),
            ...(kind === "rover"
              ? [{ key: "due_date", header: "Rover muddati", cell: (r: ProductionItem) => <RoverDueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} /> }]
              : []),
            ...(kind === "assembly"
              ? [
                  { key: "user", header: "Yig'uvchi", cell: (r: ProductionItem) => r.user_detail?.name || (r.user_detail ? phone(r.user_detail.phone) : <span className="muted">—</span>) },
                  { key: "due_date", header: "Yig'ish muddati", cell: (r: ProductionItem) => <DueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} /> },
                ]
              : []),
            ...(kind === "painter"
              ? [
                  {
                    key: "type",
                    header: "Tur",
                    cell: (r: ProductionItem) =>
                      r.type_detail ? (
                        <span>
                          {r.type_detail.name}
                          {r.painter_detail && <span className="muted"> · {r.painter_detail.name || phone(r.painter_detail.phone)}</span>}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      ),
                  },
                  { key: "due_date", header: "Molyar muddati", cell: (r: ProductionItem) => <DueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} /> },
                ]
              : []),
            { key: "square", header: "Maydon", cell: (r) => <span className="tabular-nums">{num(r.square)}</span> },
            ...(kind !== "detailing" ? [{ key: "price", header: "Narx", cell: (r: ProductionItem) => <span className="tabular-nums">{money(r.price)}</span> }] : []),
            {
              key: "done",
              header: "Bajarildi",
              cell: (r) =>
                kind === "assembly" && r.state === "checking" ? (
                  <Badge tone="warn">Tekshiruvda</Badge>
                ) : kind === "assembly" ? (
                  <div className="flex gap-1"><Check ok={r.done} label="Yig'." /><Check ok={!!r.installing_done} label="O'rn." /></div>
                ) : kind === "rover" && r.state === "checking" ? (
                  <Badge tone="warn">Tekshiruvda</Badge>
                ) : (
                  <Check ok={r.done} />
                ),
            },
          ]}
          mobileCard={(r) => (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold">№{r.order.order_number} · {r.order.client?.fio}</span>
                {(kind === "rover" || kind === "assembly") && r.state === "checking" ? (
                  <Badge tone="warn">Tekshiruvda</Badge>
                ) : (
                  <Check ok={kind === "assembly" ? !!r.installing_done : r.done} />
                )}
              </div>
              <div className="flex items-center justify-between text-sm">
                {kind === "rover" ? <span /> : <DeadlinePill deadline={r.order.deadline} />}
                <span className="muted">{num(r.square)} m²</span>
              </div>
              {kind === "detailing" && (
                <div className="text-sm">
                  <span className="muted">Detalirovka: </span>
                  <DetailingDue dueAt={r.due_at} done={r.done} />
                </div>
              )}
              {kind === "rover" && (
                <div className="text-sm">
                  <span className="muted">Rover muddati: </span>
                  <RoverDueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} />
                </div>
              )}
              {kind === "painter" && (
                <div className="text-sm">
                  <span className="muted">Molyar muddati: </span>
                  <DueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} />
                </div>
              )}
              {kind === "assembly" && (
                <div className="text-sm">
                  <span className="muted">Yig'ish muddati: </span>
                  <DueLabel dueDate={r.due_date} auto={r.due_auto} overdue={r.overdue} />
                </div>
              )}
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
  const { can } = useAuth();
  const { data: item } = useGet<ProductionItem>(`/${cfg.resource}/${id}/`);
  const { data: painterTypes } = useAll<PainterType>(
    "painter-types",
    {},
    kind === "painter" && can("oauth.user_production_head"),
  );
  const [squares, setSquares] = useState({ square: "", painter_square: "", rover_square: "" });
  const [confirm, setConfirm] = useState<null | string>(null);
  const [moveDue, setMoveDue] = useState(false);
  const [amountOpen, setAmountOpen] = useState(false);
  const [roverDue, setRoverDue] = useState(false);
  const [painterDue, setPainterDue] = useState(false);
  const [painterDoneOpen, setPainterDoneOpen] = useState(false);
  const [assemblyDue, setAssemblyDue] = useState(false);
  const [installOpen, setInstallOpen] = useState(false);
  const [note, setNote] = useState("");
  const [submitErrors, setSubmitErrors] = useState<Record<string, string>>({});
  const [amount, setAmount] = useState<{ amount: number | string; currency: string }>({ amount: "", currency: "UZS" });
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
  const painterAssign = useAction((body: { type: number | null }) => api.post(`/painters/${id}/assign/`, body), {
    success: "Saqlandi",
    invalidate: inv,
  });
  const assemblyAssign = useAction((body: { user: number | null }) => api.post(`/assemblies/${id}/assign/`, body), {
    success: "Saqlandi",
    invalidate: inv,
  });
  const run = useAction((path: string) => api.post(`/${cfg.resource}/${id}/${path}/`), {
    success: "Tayyor",
    invalidate: inv,
    onSuccess: () => setConfirm(null),
  });

  const submit = useAction(
    () =>
      api.post(`/${cfg.resource}/${id}/done/`, {
        price: { amount: Number(amount.amount), currency: amount.currency },
        note: note.trim(),
      }),
    { success: "Tekshiruvga yuborildi", invalidate: inv, onSuccess: () => setAmountOpen(false) },
  );

  const painterDone = useAction(
    () => api.post(`/painters/${id}/done/`, { note: note.trim() }),
    { success: "Bajarildi", invalidate: inv, onSuccess: () => setPainterDoneOpen(false) },
  );

  const installDone = useAction(
    () => api.post(`/assemblies/${id}/installing-done/`, { note: note.trim() }),
    { success: "Tekshiruvga yuborildi — rahbar tasdiqlaydi", invalidate: inv, onSuccess: () => setInstallOpen(false) },
  );

  if (!item) return null;
  const o = item.order;
  const a = item.actions;

  return (
    <Modal open onClose={onClose} title={`${cfg.title} · buyurtma №${o.order_number}`} size="lg">
      <div className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <OrderStatusBadge status={o.status} label={o.status_label} />
          {kind !== "rover" && <DeadlinePill deadline={o.deadline} />}
          <FolderButton folderId={item.folder} label="Bosqich fayllari" />
          <FolderButton folderId={o.folder} label="Buyurtma fayllari" />
        </div>
        <KV
          items={[
            ["Mijoz", o.client?.fio ?? "—"],
            ["Telefon", <PhoneLink value={o.client?.phone} />],
            ["Manzil", <AddressLink address={o.address} link={o.address_link} mapUrl={o.map_url} lat={o.lat} lon={o.lon} />],
            ...(kind === "rover" ? [] : ([["Topshirish sanasi", date(o.end_date, "ko'rsatilmagan")]] as [string, ReactNode][])),
            ...(kind === "detailing"
              ? ([[
                  "Detalirovka muddati",
                  <span className="flex flex-wrap items-center gap-2">
                    <DetailingDue dueAt={item.due_at} done={item.done} />
                    {a.due && (
                      <button type="button" className="text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => setMoveDue(true)}>
                        o'zgartirish
                      </button>
                    )}
                  </span>,
                ]] as [string, JSX.Element][])
              : []),
            ...(kind === "painter"
              ? ([
                  ["Molyar", item.painter_detail ? item.painter_detail.name || phone(item.painter_detail.phone) : "—"],
                  [
                    "Molyar muddati",
                    <span className="flex flex-wrap items-center gap-2">
                      <DueLabel dueDate={item.due_date} auto={item.due_auto} overdue={item.overdue} />
                      {a.due && can("oauth.user_production_head") && (
                        <button type="button" className="text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => setPainterDue(true)}>
                          o'zgartirish
                        </button>
                      )}
                    </span>,
                  ],
                  ["Holat", item.state === "done" ? <Badge tone="ok">Bajarildi</Badge> : <Badge tone="idle">Ishda</Badge>],
                  ...(item.note ? [["Izoh", <span className="whitespace-pre-wrap">{item.note}</span>]] : []),
                  ...(item.done_at
                    ? [["Bajardi", `${item.done_by_detail?.name || (item.done_by_detail ? phone(item.done_by_detail.phone) : "—")} · ${date(item.done_at)}`]]
                    : []),
                ] as [string, ReactNode][])
              : []),
            ...(kind === "assembly"
              ? ([
                  [
                    "Yig'ish muddati",
                    <span className="flex flex-wrap items-center gap-2">
                      <DueLabel dueDate={item.due_date} auto={item.due_auto} overdue={item.overdue} />
                      {a.due && can("oauth.user_production_head") && (
                        <button type="button" className="text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => setAssemblyDue(true)}>
                          o'zgartirish
                        </button>
                      )}
                    </span>,
                  ],
                  [
                    "Holat",
                    item.state === "done" ? <Badge tone="ok">{item.state_label}</Badge> : item.state === "checking" || item.state === "assembled" ? <Badge tone="warn">{item.state_label}</Badge> : <Badge tone="idle">{item.state_label ?? "Ishda"}</Badge>,
                  ],
                  ...(item.note ? [["Izoh", <span className="whitespace-pre-wrap">{item.note}</span>]] : []),
                  ...(item.finished_at
                    ? [["O'rnatdi", `${item.finished_by_detail?.name || (item.finished_by_detail ? phone(item.finished_by_detail.phone) : "—")} · ${date(item.finished_at)}`]]
                    : []),
                  ...(item.confirmed_at
                    ? [["Tasdiqladi", `${item.confirmed_by_detail?.name || (item.confirmed_by_detail ? phone(item.confirmed_by_detail.phone) : "—")} · ${date(item.confirmed_at)}`]]
                    : []),
                ] as [string, ReactNode][])
              : []),
            ["Buyurtma", <Link to={`/orders/${o.id}`} className="text-brand-700 hover:underline dark:text-brand-300">Buyurtmani ochish →</Link>],
            ...(kind !== "detailing" ? ([["Maydon", num(item.square)], ["Narx", money(item.price)]] as [string, string][]) : []),
            ...(kind === "rover"
              ? ([
                  [
                    "Rover muddati",
                    <span className="flex flex-wrap items-center gap-2">
                      <RoverDueLabel dueDate={item.due_date} auto={item.due_auto} overdue={item.overdue} />
                      {a.due && can("oauth.user_production_head") && (
                        <button type="button" className="text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => setRoverDue(true)}>
                          o'zgartirish
                        </button>
                      )}
                    </span>,
                  ],
                  ["Holat", item.state === "checking" ? <Badge tone="warn">Tekshiruvda</Badge> : item.state === "done" ? <Badge tone="ok">Bajarildi</Badge> : <Badge tone="idle">Ishda</Badge>],
                  ...(item.note ? [["Izoh", <span className="whitespace-pre-wrap">{item.note}</span>]] : []),
                  ...(item.submitted_at
                    ? [["Bajardi", `${item.submitted_by_detail?.name || (item.submitted_by_detail ? phone(item.submitted_by_detail.phone) : "—")} · ${date(item.submitted_at)}`]]
                    : []),
                  ...(item.checked_at
                    ? [["Tasdiqladi", `${item.checked_by_detail?.name || (item.checked_by_detail ? phone(item.checked_by_detail.phone) : "—")} · ${date(item.checked_at)}`]]
                    : []),
                ] as [string, ReactNode][])
              : []),
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
          <Field
            label="Jamoa (molyar turi)"
            hint="Rover tugagach rahbar jamoani tanlaydi — tanlangan jamoa mas'uliga Telegram kartasi boradi"
          >
            {a.edit && can("oauth.user_production_head") ? (
              <Select value={item.type ?? ""} onChange={(e) => painterAssign.mutate({ type: e.target.value ? Number(e.target.value) : null })}>
                <option value="">— tayinlanmagan —</option>
                {painterTypes?.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} — {money(t.price)}/m²</option>
                ))}
              </Select>
            ) : (
              <div className="text-sm">{item.type_detail?.name ?? "— tayinlanmagan —"}</div>
            )}
          </Field>
        )}

        {kind === "assembly" && (
          <Field
            label="Jamoa (yig'uvchi)"
            hint="«Сборка» holatiga o'tganda rahbar jamoani tanlaydi — tanlangan yig'uvchiga Telegram kartasi boradi"
          >
            {a.edit && can("oauth.user_production_head") ? (
              <Select value={item.user ?? ""} onChange={(e) => assemblyAssign.mutate({ user: e.target.value ? Number(e.target.value) : null })}>
                <option value="">— tayinlanmagan —</option>
                {(assemblers ?? (item.user_detail ? [item.user_detail] : [])).map((u) => (
                  <option key={u.id} value={u.id}>{u.name || phone(u.phone)}</option>
                ))}
              </Select>
            ) : (
              <div className="text-sm">{item.user_detail ? item.user_detail.name || phone(item.user_detail.phone) : "— tayinlanmagan —"}</div>
            )}
          </Field>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
          {a.done && (
            <Button
              variant="success"
              icon={<CheckCircle2 className="h-4 w-4" />}
              onClick={() => {
                if (kind === "rover") {
                  setAmount({ amount: "", currency: item.price?.currency ?? "UZS" });
                  setNote("");
                  setSubmitErrors({});
                  setAmountOpen(true);
                } else if (kind === "painter") {
                  setNote("");
                  setSubmitErrors({});
                  setPainterDoneOpen(true);
                } else setConfirm("done");
              }}
            >
              {kind === "assembly" ? "Yig'ish bajarildi" : kind === "detailing" ? "Detalirovka bajarildi" : "Bajarildi"}
            </Button>
          )}
          {kind === "rover" && a.due && can("oauth.user_production_head") && (
            <Button variant="outline" onClick={() => setRoverDue(true)}>
              🕒 Muddat
            </Button>
          )}
          {kind === "painter" && a.due && can("oauth.user_production_head") && (
            <Button variant="outline" onClick={() => setPainterDue(true)}>
              🕒 Muddat
            </Button>
          )}
          {kind === "assembly" && a.due && can("oauth.user_production_head") && (
            <Button variant="outline" onClick={() => setAssemblyDue(true)}>
              🕒 Muddat
            </Button>
          )}
          {a.confirm && (kind === "assembly" ? can("oauth.user_production_head") : can("oauth.user_rover_checker")) && (
            <Button variant="success" onClick={() => setConfirm("confirm")}>
              {kind === "assembly" ? "✅ Tayyor" : "✅ Tasdiqlash"}
            </Button>
          )}
          {a.installing_done && (
            <Button
              variant="success"
              icon={<CheckCircle2 className="h-4 w-4" />}
              onClick={() => {
                setNote("");
                setSubmitErrors({});
                setInstallOpen(true);
              }}
            >
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
          confirm === "confirm" && kind === "assembly"
            ? "Buyurtma «Готов» bo'ladi: kafolat xati va mijoz fikri boshlanadi."
            : confirm === "confirm"
              ? "Rover ishi tasdiqlanadi, molyarga xabar boradi."
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
      <Modal open={amountOpen} onClose={() => setAmountOpen(false)} title="Bajarilgan ish summasi" size="sm">
        <div className="space-y-4">
          <Field label="Summa" hint="Summa tekshiruvchiga yuboriladi" error={submitErrors.price}>
            <MoneyInput value={amount} currencies={["UZS", "USD"]} onChange={setAmount} />
          </Field>
          <Field label="Izoh (nima ish qilindi, nechta eshik)" error={submitErrors.note}>
            <Textarea required value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAmountOpen(false)}>Bekor qilish</Button>
            <Button
              variant="success"
              loading={submit.isPending}
              disabled={!(Number(amount.amount) > 0) || note.trim().length < 3}
              onClick={() => submit.mutateAsync().catch((e) => setSubmitErrors(fieldErrors(e)))}
            >
              Yuborish
            </Button>
          </div>
        </div>
      </Modal>
      <Modal open={painterDoneOpen} onClose={() => setPainterDoneOpen(false)} title="Molyar ishi bajarildi" size="sm">
        <div className="space-y-4">
          <Field label="Izoh (nima ish qilindi)" error={submitErrors.note}>
            <Textarea required value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setPainterDoneOpen(false)}>Bekor qilish</Button>
            <Button
              variant="success"
              loading={painterDone.isPending}
              disabled={note.trim().length < 3}
              onClick={() => painterDone.mutateAsync().catch((e) => setSubmitErrors(fieldErrors(e)))}
            >
              Bajarildi
            </Button>
          </div>
        </div>
      </Modal>
      <Modal open={installOpen} onClose={() => setInstallOpen(false)} title="O'rnatish bajarildi" size="sm">
        <div className="space-y-4">
          <Field label="Izoh (nima ish qilindi)" hint="Rahbar tasdiqlagach buyurtma «Tayyor» bo'ladi" error={submitErrors.note}>
            <Textarea required value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setInstallOpen(false)}>Bekor qilish</Button>
            <Button
              variant="success"
              loading={installDone.isPending}
              disabled={note.trim().length < 3}
              onClick={() => installDone.mutateAsync().catch((e) => setSubmitErrors(fieldErrors(e)))}
            >
              O'rnatildi
            </Button>
          </div>
        </div>
      </Modal>
      {assemblyDue && (
        <DueModal
          resource="assemblies"
          id={item.id}
          dueDate={item.due_date}
          title="Yig'ish muddati"
          presets={[5, 10, 14]}
          invalidate={["assemblies", "orders", "dashboard"]}
          onClose={() => setAssemblyDue(false)}
        />
      )}
      {painterDue && (
        <DueModal
          resource="painters"
          id={item.id}
          dueDate={item.due_date}
          title="Molyar muddati"
          presets={[5, 10, 14]}
          invalidate={["painters", "orders", "dashboard"]}
          onClose={() => setPainterDue(false)}
        />
      )}
      {roverDue && <RoverDueModal roverId={item.id} dueDate={item.due_date} onClose={() => setRoverDue(false)} />}
      {moveDue && <DetailingDueModal detailingId={item.id} dueAt={item.due_at} onClose={() => setMoveDue(false)} />}
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
