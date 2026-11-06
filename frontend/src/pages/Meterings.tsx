import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { AlarmClockOff, Brush, Calculator, CalendarCheck, Pencil, Plus, Send, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import type { Metering, MeteringAgenda, UserShort } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  AddressLink,
  BackLink,
  DeadlinePill,
  FolderButton,
  MeteringStatusBadge,
  OrderStatusBadge,
  PhoneLink,
} from "@/components/domain";
import { LocationEditModal, LocationField } from "@/components/LocationField";
import {
  Button,
  Card,
  Check,
  DataTable,
  Empty,
  Field,
  IconButton,
  Input,
  KV,
  Modal,
  PageHeader,
  PageLoader,
  Select,
  Pagination,
  SearchInput,
  Segmented,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { dateTime, money, phone } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import {
  dayLabel,
  METERING_INVALIDATE,
  MeteringActionButtons,
  NEXT_STEP_LABEL,
  personName,
  timeOnly,
  useMeasurers,
  useRowActions,
} from "./meterings/actions";
import { MeteringResultCard } from "./meterings/result";

const ARCHIVE = "dont_need,done,sold_out";

type Tab = "today" | "tomorrow" | "week" | "waiting" | "archive";
const TABS: Tab[] = ["today", "tomorrow", "week", "waiting", "archive"];

/** «O'lchovlar» — the measurer's day plan: overdue on top, then today / tomorrow / the week,
 * the zamers waiting for files + result, and the archive. Made for a phone: time first,
 * big buttons, the address opens Yandex Maps. */
export function MeteringsPage() {
  const navigate = useNavigate();
  const { can, user } = useAuth();
  const manager = can("metering.manage_metering");
  const { state, page, set } = useUrlState({ tab: "today", measurer: "", search: "" });
  const tab: Tab = (TABS as string[]).includes(state.tab) ? (state.tab as Tab) : "today";
  const [creating, setCreating] = useState(false);
  const measurers = useMeasurers(manager);
  const filter = { measurer: manager ? state.measurer : "", search: state.search };
  const { data: agenda, isLoading } = useGet<MeteringAgenda>("/meterings/agenda/", filter);
  const archive = useList<Metering>("meterings", { ...filter, status: ARCHIVE, page }, tab === "archive");
  const c = agenda?.counts;
  const open = (m: Metering) => navigate(`/meterings/${m.id}`);

  return (
    <div>
      <PageHeader
        title="O'lchovlar"
        subtitle="Zamerlar kun rejasi"
        actions={
          // owner's rule: everyone else books a zamer from the lead (Call-center)
          user?.is_superuser && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Yangi o'lchov
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <Segmented
          value={tab}
          onChange={(v) => set({ tab: v })}
          options={[
            { value: "today", label: "Bugun", count: c?.today },
            { value: "tomorrow", label: "Ertaga", count: c?.tomorrow },
            { value: "week", label: "Shu hafta", count: c?.week },
            { value: "waiting", label: "Ma'lumot kutilmoqda", count: c?.waiting },
            { value: "archive", label: "Arxiv", count: c?.archive },
          ]}
        />
        <div className="flex flex-1 flex-col gap-2 sm:flex-row lg:justify-end">
          <SearchInput className="sm:max-w-xs sm:flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Mijoz, telefon, manzil" />
          {manager && (
            <Select className="sm:w-auto sm:min-w-[200px]" value={state.measurer} onChange={(e) => set({ measurer: e.target.value })}>
              <option value="">Barcha zamerchilar</option>
              <option value="me">Mening zamerlarim</option>
              {measurers.data?.items.map((u) => (
                <option key={u.id} value={u.id}>{personName(u)}</option>
              ))}
            </Select>
          )}
        </div>
      </div>

      {tab !== "archive" && !!agenda?.overdue.length && (
        <Card
          className="mb-4 border-rose-200 dark:border-rose-500/30"
          title={
            <span className="flex items-center gap-2 text-rose-600 dark:text-rose-400">
              <AlarmClockOff className="h-4 w-4" /> Javob kutilmoqda · {agenda.overdue.length}
            </span>
          }
          padded={false}
        >
          <p className="muted px-5 pt-3 text-xs">Vaqti o'tdi — o'lchov olindimi, ko'chirildimi yoki bekor bo'ldimi, belgilang.</p>
          <AgendaList rows={agenda.overdue} withDate showMeasurer={manager} onOpen={open} late />
        </Card>
      )}

      {tab === "archive" ? (
        <Card padded={false}>
          <DataTable
            rows={archive.data?.results}
            loading={archive.isFetching}
            rowKey={(r) => r.id}
            onRowClick={open}
            columns={[
              { key: "client", header: "Mijoz", cell: (r) => <div><div className="font-medium">{r.client.fio}</div><PhoneLink value={r.client.phone} /></div> },
              { key: "date", header: "O'lchov sanasi", cell: (r) => <span className="whitespace-nowrap">{dateTime(r.date_time)}</span> },
              { key: "status", header: "Holat", cell: (r) => <MeteringStatusBadge status={r.status} label={r.status_label} /> },
              ...(manager ? [{ key: "measurer", header: "Zamerchi", cell: (r: Metering) => personName(r.measurer) }] : []),
              {
                key: "flow",
                header: "Dizayn / Narx",
                cell: (r) => (
                  <div className="flex gap-1">
                    {r.design ? <Check ok={r.design.done} label="D" /> : <span className="muted">—</span>}
                    {r.price && <Check ok={r.price.done} label="N" />}
                  </div>
                ),
              },
              {
                key: "order",
                header: "Buyurtma",
                cell: (r) =>
                  r.order ? (
                    <div className="flex flex-col items-start gap-1">
                      <span className="font-medium">№{r.order.order_number}</span>
                      <DeadlinePill deadline={r.order.deadline} />
                    </div>
                  ) : (
                    <span className="muted">—</span>
                  ),
              },
              { key: "left", header: "Qoldiq", cell: (r) => (r.order?.money_left ? money(r.order.money_left) : <span className="muted">—</span>), hideOnMobile: true },
            ]}
            mobileCard={(r) => (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{r.client.fio}</span>
                  <MeteringStatusBadge status={r.status} label={r.status_label} />
                </div>
                <div className="muted text-sm">
                  {dateTime(r.date_time)} ·{" "}
                  <AddressLink nested address={r.address} link={r.address_link} mapUrl={r.map_url} lat={r.lat} lon={r.lon} />
                </div>
                {r.status === "dont_need" && r.cancel_reason && <div className="text-sm text-rose-600 dark:text-rose-400">{r.cancel_reason}</div>}
                <div className="flex gap-1">
                  {r.design && <Check ok={r.design.done} label="Dizayn" />}
                  {r.price && <Check ok={r.price.done} label="Narx" />}
                  {r.order && <OrderStatusBadge status={r.order.status} label={`№${r.order.order_number}`} />}
                </div>
              </div>
            )}
          />
          <Pagination page={page} count={archive.data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
      ) : isLoading || !agenda ? (
        <PageLoader />
      ) : (
        <Card padded={false}>
          {agenda[tab].length ? (
            <AgendaList rows={agenda[tab]} withDate={tab === "week" || tab === "waiting"} waiting={tab === "waiting"} showMeasurer={manager} onOpen={open} />
          ) : (
            <Empty
              icon={<CalendarCheck className="h-6 w-6" />}
              title={tab === "waiting" ? "Hamma natijalar topshirilgan" : "Zamer yo'q"}
              text={tab === "today" ? "Bugunga zamer rejalashtirilmagan." : undefined}
            />
          )}
        </Card>
      )}
      {creating && <MeteringCreateModal onClose={() => setCreating(false)} onCreated={(m) => navigate(`/meterings/${m.id}`)} />}
    </div>
  );
}

function AgendaList({
  rows,
  withDate,
  waiting,
  late,
  showMeasurer,
  onOpen,
}: {
  rows: Metering[];
  withDate?: boolean;
  waiting?: boolean;
  late?: boolean;
  showMeasurer?: boolean;
  onOpen: (m: Metering) => void;
}) {
  const allowed = useRowActions();
  const navigate = useNavigate();
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {rows.map((m) => {
        const when = waiting ? m.measured_at ?? m.date_time : m.date_time;
        const act = allowed(m);
        return (
          <li
            key={m.id}
            onClick={() => onOpen(m)}
            className={cn("cursor-pointer px-4 py-4 transition hover:bg-slate-50 sm:px-5 dark:hover:bg-slate-800/40", late && "bg-rose-50/40 dark:bg-rose-500/[.04]")}
          >
            <div className="flex gap-4">
              <div className="w-16 shrink-0 sm:w-20">
                <div className={cn("text-2xl font-bold tabular-nums leading-none tracking-tight", late ? "text-rose-600 dark:text-rose-400" : "text-slate-900 dark:text-white")}>
                  {timeOnly(when)}
                </div>
                {withDate && when && <div className="muted mt-1 text-xs leading-tight">{dayLabel(when)}</div>}
                {waiting && <div className="muted mt-1 text-[11px] leading-tight">olingan</div>}
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-base font-semibold text-slate-900 dark:text-white">{m.client.fio}</span>
                  {m.status === "other_day" && <MeteringStatusBadge status={m.status} label={m.status_label} />}
                </div>
                <div className="text-sm">
                  <PhoneLink value={m.client.phone} />
                </div>
                <div className="text-sm">
                  <AddressLink nested address={m.address} link={m.address_link} mapUrl={m.map_url} lat={m.lat} lon={m.lon} empty="Manzil yo'q" />
                </div>
                {m.desc && <div className="muted line-clamp-2 text-sm">{m.desc}</div>}
                <div className="muted flex flex-wrap gap-x-3 text-xs">
                  {m.operator && <span>Operator: {personName(m.operator)}</span>}
                  {showMeasurer && <span>Zamerchi: {personName(m.measurer, "tayinlanmagan")}</span>}
                </div>
              </div>
            </div>
            <MeteringActionButtons
              className="mt-3 sm:pl-24"
              big
              metering={m}
              allowed={act}
              onResult={() => navigate(`/meterings/${m.id}#natija`)}
            />
          </li>
        );
      })}
    </ul>
  );
}

export function MeteringCreateModal({
  initial,
  onClose,
  onCreated,
}: {
  initial?: {
    client_phone?: string;
    client_fio?: string;
    invoice?: number;
    /** the lead's address — prefilled; its map point is copied by the server when the field is left empty */
    address?: string;
    invoiceHasLocation?: boolean;
  };
  onClose: () => void;
  onCreated?: (m: Metering) => void;
}) {
  const [form, setForm] = useState({
    client_phone: initial?.client_phone ?? "+998",
    client_fio: initial?.client_fio ?? "",
    date_time: "",
    address: initial?.address ?? "",
    location: "",
    desc: "",
  });
  const measurers = useMeasurers();
  const [measurer, setMeasurer] = useState("");
  // the only measurer is preselected
  useEffect(() => {
    const data = measurers.data;
    const d = data?.default ?? (data?.items.length === 1 ? data.items[0].id : null);
    if (d && !measurer) setMeasurer(String(d));
  }, [measurers.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useAction(
    () =>
      api
        .post<Metering>("/meterings/", { ...form, invoice: initial?.invoice ?? null, ...(measurer ? { measurer: Number(measurer) } : {}) })
        .then((r) => r.data),
    {
      success: "O'lchov yaratildi",
      invalidate: ["meterings", "invoices", "dashboard", "clients"],
      onSuccess: (m) => {
        onClose();
        onCreated?.(m);
      },
    },
  );
  const upd = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const items = measurers.data?.items ?? [];
  return (
    <Modal
      open
      onClose={onClose}
      title={initial?.invoice ? `#${initial.invoice} ariza bo'yicha o'lchov` : "Yangi o'lchov"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button loading={create.isPending} onClick={() => create.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            O'lchov yaratish
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Mijoz telefoni" error={errors.client_phone}>
          <Input inputMode="tel" value={form.client_phone} disabled={!!initial?.invoice} onChange={upd("client_phone")} />
        </Field>
        <Field label="F.I.Sh. (yangi mijoz uchun)" error={errors.client_fio}>
          <Input value={form.client_fio} disabled={!!initial?.invoice} onChange={upd("client_fio")} />
        </Field>
        <Field label="O'lchov sanasi va vaqti" error={errors.date_time}>
          <Input type="datetime-local" value={form.date_time} onChange={upd("date_time")} />
        </Field>
        <Field
          label="Zamerchi"
          error={errors.measurer}
          hint={
            measurers.data && !items.length ? (
              <span className="text-amber-700 dark:text-amber-300">
                {measurers.data.hint || "Zamerchi yo'q — xodimga «Metering» huquqini bering"}
              </span>
            ) : (
              "Telegram orqali xabar boradi"
            )
          }
        >
          <Select value={measurer} onChange={(e) => setMeasurer(e.target.value)} disabled={!items.length}>
            {items.length !== 1 && <option value="">— tanlang —</option>}
            {items.map((u) => (
              <option key={u.id} value={u.id}>{personName(u)}</option>
            ))}
          </Select>
        </Field>
        <Field label="Manzil" error={errors.address} className="sm:col-span-2">
          <Input value={form.address} onChange={upd("address")} />
        </Field>
        <LocationField
          className="sm:col-span-2"
          value={form.location}
          onChange={(location) => setForm({ ...form, location })}
          error={errors.location ?? errors.address_link}
          hint={initial?.invoiceHasLocation ? "Arizadan olinadi 📍 (bo'sh qoldiring yoki boshqasini kiriting)" : undefined}
        />
        <Field label="Tavsif" error={errors.desc} className="sm:col-span-2">
          <Textarea value={form.desc} onChange={upd("desc")} />
        </Field>
      </div>
    </Modal>
  );
}

export function MeteringDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: m, isLoading } = useGet<Metering>(`/meterings/${id}/`);
  const { can } = useAuth();
  const [editLocation, setEditLocation] = useState(false);
  const [assign, setAssign] = useState(false);
  const [desc, setDesc] = useState("");
  useEffect(() => {
    if (m) setDesc(m.desc ?? "");
  }, [m]);
  const a = m?.actions ?? {};
  const measurers = useMeasurers(!!a.set_measurer);

  const scrollToResult = () =>
    setTimeout(() => document.getElementById("natija")?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
  // opened from the agenda's «Natija» button
  useEffect(() => {
    if (m && location.hash === "#natija") scrollToResult();
  }, [m?.id, location.hash]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = useAction((path: string) => api.post(`/meterings/${id}/${path}/`), { success: "Tayyor", invalidate: METERING_INVALIDATE });
  // the zamer's approximate price (before «Bajarildi»): opened at once to calculate
  const estimate = useAction(() => api.post<{ id: number }>(`/meterings/${id}/estimate/`).then((r) => r.data), {
    invalidate: [...METERING_INVALIDATE, "invoices"],
    onSuccess: (r) => navigate(`/prices/${r.id}`),
  });
  const save = useAction(() => api.patch(`/meterings/${id}/`, { desc }), { success: "Saqlandi", invalidate: METERING_INVALIDATE });
  const setMeasurer = useAction((measurer: number) => api.post(`/meterings/${id}/measurer/`, { measurer }), {
    success: "Zamerchi almashtirildi",
    invalidate: METERING_INVALIDATE,
  });

  if (isLoading || !m) return <PageLoader />;
  const dirty = desc !== (m.desc ?? "");
  const showResult = !!(a.finish || a.upload || m.status === "done");
  const measurerItems = measurers.data?.items ?? [];
  const measurerKnown = !m.measurer || measurerItems.some((u) => u.id === m.measurer!.id);

  return (
    <div>
      <PageHeader
        back={<BackLink to="/meterings">O'lchovlar</BackLink>}
        title={m.client.fio}
        subtitle={<span className="flex flex-wrap items-center gap-2"><MeteringStatusBadge status={m.status} label={m.status_label} /> O'lchov #{m.id}</span>}
        actions={
          <>
            <FolderButton folderId={m.folder} />
            {a.assign && !a.finish && (
              <Button variant="outline" icon={<UserPlus className="h-4 w-4" />} onClick={() => setAssign(true)}>
                Ijrochilarni tayinlash
              </Button>
            )}
          </>
        }
      />
      <MeteringActionButtons
        className="mb-4"
        big
        metering={m}
        allowed={{
          measured: a.measured ?? a.metering_done,
          reschedule: a.reschedule ?? a.other_day,
          cancel: a.cancel ?? a.dont_need,
        }}
        onMeasured={() => {
          toast.success("O'lchov olindi — endi fayllarni yuklang");
          scrollToResult();
        }}
      />
      {m.is_overdue && (
        <div className="mb-4 rounded-xl bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700 ring-1 ring-inset ring-rose-600/15 dark:bg-rose-500/10 dark:text-rose-300">
          Zamer vaqti o'tdi — natijani belgilang.
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Ma'lumot">
            <KV
              items={[
                ["Vaqt", <span className="whitespace-nowrap text-base font-semibold">{m.date_time ? `${dayLabel(m.date_time)} · ${timeOnly(m.date_time)}` : "—"}</span>],
                ["Mijoz", <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(m.client.phone)}`}>{m.client.fio}</Link>],
                ["Telefon", <PhoneLink value={m.client.phone} />],
                [
                  "Manzil",
                  <span className="inline-flex items-start gap-1">
                    <AddressLink address={m.address} link={m.address_link} mapUrl={m.map_url} lat={m.lat} lon={m.lon} />
                    {can("metering.change_metering") && m.is_editable && (
                      <IconButton label="Manzil va lokatsiyani o'zgartirish" className="-my-2 h-8 w-8" onClick={() => setEditLocation(true)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </IconButton>
                    )}
                  </span>,
                ],
                [
                  "Zamerchi",
                  a.set_measurer && measurerItems.length ? (
                    <Select
                      className="h-8 w-auto min-w-[180px] py-0 text-sm"
                      value={measurerKnown ? m.measurer?.id ?? "" : ""}
                      disabled={setMeasurer.isPending}
                      onChange={(e) => e.target.value && setMeasurer.mutate(Number(e.target.value))}
                    >
                      {(!m.measurer || !measurerKnown) && <option value="">{m.measurer ? personName(m.measurer) : "— tanlang —"}</option>}
                      {measurerItems.map((u) => (
                        <option key={u.id} value={u.id}>{personName(u)}</option>
                      ))}
                    </Select>
                  ) : (
                    personName(m.measurer, "tayinlanmagan")
                  ),
                ],
                ["Operator", personName(m.operator)],
                ["Yaratilgan", dateTime(m.create_date)],
                ...(m.measured_at ? ([["O'lchov olingan", dateTime(m.measured_at)]] as [string, ReactNode][]) : []),
                ...(m.done_at ? ([["Bajarilgan", dateTime(m.done_at)]] as [string, ReactNode][]) : []),
                ...(m.next_step ? ([["Keyingi qadam", NEXT_STEP_LABEL[m.next_step]]] as [string, ReactNode][]) : []),
                ...(m.status === "dont_need" && m.cancel_reason
                  ? ([["Bekor sababi", <span className="whitespace-pre-line text-rose-600 dark:text-rose-400">{m.cancel_reason}</span>]] as [string, ReactNode][])
                  : []),
                ...(m.invoice ? ([["Ariza", <Link className="text-brand-700 hover:underline" to={`/call-center?open=${m.invoice}`}>#{m.invoice}</Link>]] as [string, ReactNode][]) : []),
              ]}
            />
          </Card>
          {m.result_note && (
            <Card title="Zamerchi izohi">
              <p className="whitespace-pre-line break-words text-sm">{m.result_note}</p>
            </Card>
          )}
          {showResult && <MeteringResultCard id="natija" metering={m} />}
          <Card title="Tavsif">
            <Textarea disabled={!a.edit} value={desc} onChange={(e) => setDesc(e.target.value)} />
            {a.edit && dirty && (
              <div className="mt-4 flex justify-end">
                <Button loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Bosqichlar">
            <ol className="space-y-3 text-sm">
              <Step done={m.status !== "created" && m.status !== "other_day" && m.status !== "dont_need"} label="O'lchov" hint={m.measured_at ? dateTime(m.measured_at) : undefined} />
              <Step done={m.status === "done" || m.status === "sold_out"} label="Fayllar va natija" hint={m.next_step ? NEXT_STEP_LABEL[m.next_step] : undefined} />
              <Step
                done={!!m.design?.done}
                label="Dizayn"
                hint={m.design ? assigneeLabel(m.design.user) : undefined}
                action={
                  m.design ? (
                    <Link to={`/designs/${m.design.id}`} className="text-brand-700 hover:underline dark:text-brand-300">Ochish</Link>
                  ) : a.assign && !a.finish ? (
                    <Button size="sm" variant="outline" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setAssign(true)}>
                      Tayinlash
                    </Button>
                  ) : a.create_design ? (
                    <Button size="sm" variant="outline" icon={<Brush className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => run.mutate("create-design")}>
                      Boshlash
                    </Button>
                  ) : null
                }
              />
              <Step
                done={!!m.price?.done}
                label="Narx hisoblash"
                hint={m.price ? (m.price.stage === "estimate" ? "Taxminiy narx — «Bajarildi»da menejerga beriladi" : assigneeLabel(m.price.user)) : undefined}
                action={
                  m.price ? (
                    <Link to={`/prices/${m.price.id}`} className="text-brand-700 hover:underline dark:text-brand-300">
                      Narx tahrirlash
                    </Link>
                  ) : (
                    <div className="flex flex-wrap justify-end gap-2">
                      {a.assign && !a.finish ? (
                        <Button size="sm" variant="outline" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setAssign(true)}>
                          Tayinlash
                        </Button>
                      ) : a.create_price ? (
                        <Button size="sm" variant="outline" icon={<Calculator className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => run.mutate("create-price")}>
                          Boshlash
                        </Button>
                      ) : null}
                      {["created", "other_day", "metering_done"].includes(m.status) && (
                        <Button size="sm" variant="outline" icon={<Calculator className="h-3.5 w-3.5" />} loading={estimate.isPending} onClick={() => estimate.mutate()}>
                          Taxminiy narx
                        </Button>
                      )}
                    </div>
                  )
                }
              />
              <Step
                done={!!m.order}
                label="Buyurtma"
                action={
                  m.order ? (
                    <button onClick={() => navigate(`/orders/${m.order!.id}`)} className="text-brand-700 hover:underline dark:text-brand-300">
                      №{m.order.order_number}
                    </button>
                  ) : null
                }
              />
            </ol>
          </Card>
          {m.order && (
            <Card title={`Buyurtma №${m.order.order_number}`}>
              <div className="flex flex-wrap gap-2">
                <OrderStatusBadge status={m.order.status} label={m.order.status_label} />
                <DeadlinePill deadline={m.order.deadline} />
              </div>
              {m.order.money_left && <p className="mt-3 text-sm">Qoldiq: <b>{money(m.order.money_left)}</b></p>}
            </Card>
          )}
        </div>
      </div>

      {assign && <AssignTasksModal metering={m} onClose={() => setAssign(false)} />}
      {editLocation && (
        <LocationEditModal
          resource="meterings"
          id={m.id}
          address={m.address}
          link={m.address_link}
          lat={m.lat}
          lon={m.lon}
          invalidate={["meterings", "dashboard", "designs", "prices", "orders", "invoices"]}
          onClose={() => setEditLocation(false)}
        />
      )}
    </div>
  );
}

function assigneeLabel(user: UserShort | null) {
  return user ? `Ijrochi: ${user.name || phone(user.phone)}` : "Ijrochi tayinlanmagan";
}

function Step({ done, label, action, hint }: { done: boolean; label: string; action?: ReactNode; hint?: string }) {
  return (
    <li className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2">
        <span
          className={
            done
              ? "flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-xs text-white"
              : "flex h-6 w-6 items-center justify-center rounded-full border-2 border-slate-300 dark:border-slate-600"
          }
        >
          {done && "✓"}
        </span>
        <span>
          <span className={done ? "font-medium" : ""}>{label}</span>
          {hint && <span className="muted block text-xs">{hint}</span>}
        </span>
      </span>
      {action}
    </li>
  );
}

function AssignTasksModal({ metering, onClose }: { metering: Metering; onClose: () => void }) {
  const { data: people, isLoading } = useGet<{ designers: UserShort[]; pricers: UserShort[] }>("/meterings/assignees/");
  const designDone = !!metering.design?.done;
  const priceDone = !!metering.price?.done;
  const [design, setDesign] = useState({ on: !designDone, user: metering.design?.user ? String(metering.design.user.id) : "" });
  const [price, setPrice] = useState({ on: !priceDone, user: metering.price?.user ? String(metering.price.user.id) : "" });

  const body = {
    designer: design.on && design.user ? Number(design.user) : null,
    pricer: price.on && price.user ? Number(price.user) : null,
  };
  const missing = (design.on && !design.user) || (price.on && !price.user);
  const nothing = !body.designer && !body.pricer;
  const save = useAction(
    () => api.post(`/meterings/${metering.id}/assign/`, body).then((r) => r.data.assigned as Record<string, string | null>),
    {
      invalidate: ["meterings", "designs", "prices", "dashboard"],
      onSuccess: (assigned) => {
        const sent = Object.values(assigned).filter(Boolean).length;
        if (sent) toast.success(sent > 1 ? "Vazifalar ijrochilarga yuborildi" : "Vazifa ijrochiga yuborildi");
        else toast.info("O'zgarish yo'q — bu xodimlar allaqachon tayinlangan");
        onClose();
      },
    },
  );

  const row = (
    title: string,
    icon: ReactNode,
    state: { on: boolean; user: string },
    set: (s: { on: boolean; user: string }) => void,
    options: UserShort[] | undefined,
    done: boolean,
  ) => (
    <div className={cn("rounded-2xl border p-4 transition", state.on ? "border-brand-300 bg-brand-50/40 dark:border-brand-600 dark:bg-brand-500/5" : "border-slate-200 dark:border-slate-700")}>
      <label className="flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          className="h-4 w-4 accent-brand-700"
          checked={state.on}
          disabled={done}
          onChange={(e) => set({ ...state, on: e.target.checked })}
        />
        <span className="flex items-center gap-2 font-medium">{icon}{title}</span>
        {done && <span className="muted ml-auto text-xs">allaqachon bajarilgan</span>}
      </label>
      {state.on && !done && (
        <Select className="mt-3" value={state.user} onChange={(e) => set({ ...state, user: e.target.value })}>
          <option value="">— xodimni tanlang —</option>
          {options?.map((u) => (
            <option key={u.id} value={u.id}>{u.name || phone(u.phone)}</option>
          ))}
        </Select>
      )}
      {state.on && !done && options && !options.length && (
        <p className="mt-2 text-xs text-amber-600">Kerakli huquqqa ega xodim yo'q</p>
      )}
    </div>
  );

  return (
    <Modal
      open
      onClose={onClose}
      title="Ijrochilarni tayinlash"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Keyinroq</Button>
          <Button icon={<Send className="h-4 w-4" />} loading={save.isPending} disabled={missing || nothing} onClick={() => save.mutate()}>
            Vazifalarni yuborish
          </Button>
        </>
      }
    >
      {isLoading ? (
        <PageLoader />
      ) : (
        <div className="space-y-3">
          <p className="muted text-sm">
            Dizaynni kim chizishi va narxni kim hisoblashini tanlang. Vazifa Telegram orqali faqat tanlangan xodimlarga boradi.
          </p>
          {row("Dizayn chizish", <Brush className="h-4 w-4 text-brand-600" />, design, setDesign, people?.designers, designDone)}
          {row("Narx hisoblash", <Calculator className="h-4 w-4 text-brand-600" />, price, setPrice, people?.pricers, priceDone)}
        </div>
      )}
    </Modal>
  );
}
