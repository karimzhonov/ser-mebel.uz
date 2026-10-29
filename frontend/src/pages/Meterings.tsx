import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Brush, Calculator, CalendarClock, CheckCircle2, Plus, Send, UserPlus, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList, useMeta } from "@/api/hooks";
import type { Metering, StatusStats, UserShort } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  AddressLink,
  BackLink,
  DeadlinePill,
  FolderButton,
  MeteringStatusBadge,
  OrderStatusBadge,
  PhoneLink,
  TimelineChart,
} from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import {
  Button,
  Card,
  Check,
  Chip,
  Confirm,
  DataTable,
  Field,
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
import { dateTime, money, phone, toLocalInput } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

const ACTIVE = "created,other_day,metering_done";
const ARCHIVE = "dont_need,done,sold_out";

export function MeteringsPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { state, page, set } = useUrlState({ search: "", status: ACTIVE, date_from: "", date_to: "" });
  const [creating, setCreating] = useState(false);
  const { data, isFetching } = useList<Metering>("meterings", { ...state, page });
  const { data: stats } = useGet<StatusStats>("/meterings/stats/", { search: state.search, date_from: state.date_from, date_to: state.date_to });
  const counts = Object.fromEntries((stats?.by_status ?? []).map((s) => [s.key, s.count]));
  const selected = state.status.split(",").filter(Boolean);
  const tab = state.status === ACTIVE ? "active" : state.status === ARCHIVE ? "archive" : state.status ? "custom" : "all";

  return (
    <div>
      <PageHeader
        title="O'lchovlar"
        subtitle="O'lchovga chiqish, dizayn va narx hisoblash"
        actions={
          can("metering.add_metering") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Yangi o'lchov
            </Button>
          )
        }
      />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented
          value={tab}
          onChange={(v) => set({ status: v === "active" ? ACTIVE : v === "archive" ? ARCHIVE : "" })}
          options={[
            { value: "active", label: "Faol" },
            { value: "archive", label: "Bajarilgan" },
            { value: "all", label: "Barchasi", count: stats?.total },
          ]}
        />
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {meta?.metering_statuses.map((s) => (
          <Chip
            key={s.value}
            tone={s.tone}
            active={selected.includes(String(s.value))}
            onClick={() =>
              set({
                status: (selected.includes(String(s.value))
                  ? selected.filter((x) => x !== s.value)
                  : [...selected, String(s.value)]
                ).join(","),
              })
            }
          >
            {s.label} · {counts[String(s.value)] ?? 0}
          </Chip>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card padded={false}>
          <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
            <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Mijoz, telefon, manzil" />
            <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
          </div>
          <DataTable
            rows={data?.results}
            loading={isFetching}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(`/meterings/${r.id}`)}
            columns={[
              { key: "client", header: "Mijoz", cell: (r) => <div><div className="font-medium">{r.client.fio}</div><PhoneLink value={r.client.phone} /></div> },
              { key: "date", header: "O'lchov sanasi", cell: (r) => <span className="whitespace-nowrap">{dateTime(r.date_time)}</span> },
              { key: "status", header: "Holat", cell: (r) => <MeteringStatusBadge status={r.status} label={r.status_label} /> },
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
                <div className="muted text-sm">{dateTime(r.date_time)} · {r.address || "—"}</div>
                <div className="flex gap-1">
                  {r.design && <Check ok={r.design.done} label="Dizayn" />}
                  {r.price && <Check ok={r.price.done} label="Narx" />}
                  {r.order && <OrderStatusBadge status={r.order.status} label={`№${r.order.order_number}`} />}
                </div>
              </div>
            )}
          />
          <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
        <Card title="Kunlar bo'yicha o'lchovlar">
          <TimelineChart data={stats?.timeline} />
        </Card>
      </div>
      {creating && <MeteringCreateModal onClose={() => setCreating(false)} onCreated={(m) => navigate(`/meterings/${m.id}`)} />}
    </div>
  );
}

export function MeteringCreateModal({
  initial,
  onClose,
  onCreated,
}: {
  initial?: { client_phone?: string; client_fio?: string; invoice?: number };
  onClose: () => void;
  onCreated?: (m: Metering) => void;
}) {
  const [form, setForm] = useState({
    client_phone: initial?.client_phone ?? "+998",
    client_fio: initial?.client_fio ?? "",
    date_time: "",
    address: "",
    address_link: "",
    desc: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useAction(
    () => api.post<Metering>("/meterings/", { ...form, invoice: initial?.invoice ?? null }).then((r) => r.data),
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
        <Field label="O'lchov sanasi va vaqti" error={errors.date_time} className="sm:col-span-2">
          <Input type="datetime-local" value={form.date_time} onChange={upd("date_time")} />
        </Field>
        <Field label="Manzil" error={errors.address} className="sm:col-span-2">
          <Input value={form.address} onChange={upd("address")} />
        </Field>
        <Field label="Xarita havolasi" error={errors.address_link} className="sm:col-span-2">
          <Input type="url" placeholder="https://yandex.uz/maps/…" value={form.address_link} onChange={upd("address_link")} />
        </Field>
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
  const { data: m, isLoading } = useGet<Metering>(`/meterings/${id}/`);
  const [otherDay, setOtherDay] = useState(false);
  const [assign, setAssign] = useState(false);
  const [confirm, setConfirm] = useState<null | "dont_need" | "metering_done">(null);
  const [form, setForm] = useState({ date_time: "", desc: "" });
  useEffect(() => {
    if (m) setForm({ date_time: toLocalInput(m.date_time), desc: m.desc ?? "" });
  }, [m]);

  const inv = ["meterings", "dashboard", "designs", "prices"];
  const run = useAction((path: string) => api.post(`/meterings/${id}/${path}/`), { success: "Tayyor", invalidate: inv });
  const save = useAction(() => api.patch(`/meterings/${id}/`, form), { success: "Saqlandi", invalidate: inv });
  const move = useAction(() => api.post(`/meterings/${id}/other-day/`, { date_time: form.date_time || null }), {
    success: "Ko'chirildi",
    invalidate: inv,
    onSuccess: () => setOtherDay(false),
  });

  if (isLoading || !m) return <PageLoader />;
  const a = m.actions!;
  const dirty = form.desc !== (m.desc ?? "") || form.date_time !== toLocalInput(m.date_time);

  return (
    <div>
      <PageHeader
        back={<BackLink to="/meterings">O'lchovlar</BackLink>}
        title={m.client.fio}
        subtitle={<span className="flex flex-wrap items-center gap-2"><MeteringStatusBadge status={m.status} label={m.status_label} /> O'lchov #{m.id}</span>}
        actions={
          <>
            <FolderButton folderId={m.folder} />
            {a.other_day && (
              <Button variant="outline" icon={<CalendarClock className="h-4 w-4" />} onClick={() => setOtherDay(true)}>
                Boshqa kun
              </Button>
            )}
            {a.assign && (
              <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setAssign(true)}>
                Ijrochilarni tayinlash
              </Button>
            )}
            {a.metering_done && (
              <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirm("metering_done")}>
                O'lchov bajarildi
              </Button>
            )}
            {a.dont_need && (
              <Button variant="danger" icon={<XCircle className="h-4 w-4" />} onClick={() => setConfirm("dont_need")}>
                Bekor qilish
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Ma'lumot">
            <KV
              items={[
                ["Mijoz", <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(m.client.phone)}`}>{m.client.fio}</Link>],
                ["Telefon", <PhoneLink value={m.client.phone} />],
                ["Manzil", <AddressLink address={m.address} link={m.address_link} />],
                ["Yaratilgan", dateTime(m.create_date)],
                ...(m.invoice ? ([["Ariza", <Link className="text-brand-700 hover:underline" to={`/call-center?open=${m.invoice}`}>#{m.invoice}</Link>]] as [string, JSX.Element][]) : []),
              ]}
            />
          </Card>
          <Card title="O'lchov tafsilotlari">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Sana va vaqt">
                <Input type="datetime-local" disabled={!a.edit} value={form.date_time} onChange={(e) => setForm({ ...form, date_time: e.target.value })} />
              </Field>
              <Field label="Tavsif" className="sm:col-span-2">
                <Textarea disabled={!a.edit} value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
              </Field>
            </div>
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
              <Step done={m.status !== "created" && m.status !== "other_day"} label="O'lchov" />
              <Step
                done={!!m.design?.done}
                label="Dizayn"
                hint={m.design ? assigneeLabel(m.design.user) : undefined}
                action={
                  m.design ? (
                    <Link to={`/designs/${m.design.id}`} className="text-brand-700 hover:underline dark:text-brand-300">Ochish</Link>
                  ) : a.assign ? (
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
                hint={m.price ? assigneeLabel(m.price.user) : undefined}
                action={
                  m.price ? (
                    <Link to={`/prices/${m.price.id}`} className="text-brand-700 hover:underline dark:text-brand-300">Ochish</Link>
                  ) : a.assign ? (
                    <Button size="sm" variant="outline" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setAssign(true)}>
                      Tayinlash
                    </Button>
                  ) : a.create_price ? (
                    <Button size="sm" variant="outline" icon={<Calculator className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => run.mutate("create-price")}>
                      Boshlash
                    </Button>
                  ) : null
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

      <Modal
        open={otherDay}
        onClose={() => setOtherDay(false)}
        title="Boshqa kunga ko'chirish"
        size="sm"
        footer={<Button loading={move.isPending} onClick={() => move.mutate()}>Ko'chirish</Button>}
      >
        <Field label="Yangi sana va vaqt">
          <Input type="datetime-local" value={form.date_time} onChange={(e) => setForm({ ...form, date_time: e.target.value })} />
        </Field>
      </Modal>
      <Confirm
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={confirm === "dont_need" ? "O'lchov bekor qilinsinmi?" : "O'lchov bajarilgan deb belgilansinmi?"}
        text={confirm === "dont_need" ? "O'lchov «Bajarilgan» bo'limiga o'tadi — keyin uni o'zgartirib bo'lmaydi." : "Shundan keyin dizayn va narx hisoblashni boshlash mumkin."}
        variant={confirm === "dont_need" ? "danger" : "success"}
        loading={run.isPending}
        onConfirm={() =>
          run.mutate(confirm === "dont_need" ? "dont-need" : "metering-done", {
            onSettled: () => setConfirm(null),
            // Next step after measuring: hand the design / price tasks out.
            onSuccess: () => confirm === "metering_done" && setAssign(true),
          })
        }
      />
      {assign && <AssignTasksModal metering={m} onClose={() => setAssign(false)} />}
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
