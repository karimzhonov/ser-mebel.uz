import { useEffect, useState } from "react";
import { Plus, Trash2, Trophy } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useAll, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Card, Confirm, DataTable, Field, IconButton, Input, Modal, PageHeader, SearchInput, Segmented, Select } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { WD, type Employee, type Group, type StatRow } from "./shared";

/* ------------------------------------------------------------------ rating */
interface Winner { id: number; kind: "m" | "y"; kind_label: string; period: string; employee: number; employee_name: string }
interface Adjust { id: number; employee: number; employee_name: string; day: string; value: number; reason: string }

export function HrRatingPage() {
  const { can } = useAuth();
  const ym = new Date().toISOString().slice(0, 7);
  const { state, set } = useUrlState({ mode: "m", month: ym, year: ym.slice(0, 4) });
  const params = state.mode === "y" ? { year: state.year } : { month: state.month };
  const { data, isFetching } = useGet<{ rows: StatRow[] }>("/hr/stats/", params);
  const { data: winners } = useAll<Winner>("hr/winners");
  const from = state.mode === "y" ? `${state.year}-01-01` : `${state.month}-01`;
  const lastDay = new Date(Number(state.month.slice(0, 4)), Number(state.month.slice(5, 7)), 0).getDate();
  const to = state.mode === "y" ? `${state.year}-12-31` : `${state.month}-${String(lastDay).padStart(2, "0")}`;
  const { data: adj } = useList<Adjust>("hr/points", { date_from: from, date_to: to, page_size: 100 });
  const [give, setGive] = useState(false);
  const period = state.mode === "y" ? state.year : state.month;
  const won = winners?.find((w) => w.kind === state.mode && w.period === period);
  const announce = useAction((employee: number) => api.post("/hr/winners/announce/", { kind: state.mode, period, employee }), {
    success: "Guruhlarda e'lon qilindi",
    invalidate: ["hr"],
  });
  const removeAdj = useAction((id: number) => api.delete(`/hr/points/${id}/`), { success: "O'chirildi", invalidate: ["hr"] });
  const medal = (i: number) => ["🥇", "🥈", "🥉"][i] ?? `${i + 1}.`;
  return (
    <div>
      <PageHeader
        title="Reyting"
        subtitle="Ballar: vaqtida +10, kech −5, kelmadi −15, forma ±, ketish otcheti +5; toza oy +20"
        actions={can("hr.add_pointadjustment") && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setGive(true)}>Qo'shimcha ball</Button>}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented value={state.mode} onChange={(mode) => set({ mode })} options={[{ value: "m", label: "🏆 Oy" }, { value: "y", label: "👑 Yil" }]} />
        {state.mode === "m" ? (
          <Input type="month" className="w-44" value={state.month} onChange={(e) => set({ month: e.target.value || ym })} />
        ) : (
          <Input type="number" className="w-28" value={state.year} onChange={(e) => set({ year: e.target.value })} />
        )}
        {won && <Badge tone="primary">{won.kind_label}: {won.employee_name}</Badge>}
      </div>
      <Card padded={false}>
        <DataTable
          rows={data?.rows}
          loading={isFetching}
          rowKey={(r) => r.employee_id}
          columns={[
            { key: "i", header: "O'rin", cell: (r) => medal(data!.rows.indexOf(r)) },
            { key: "n", header: "Xodim", cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: "p", header: "Ball", cell: (r) => <b>{r.points}</b> },
            { key: "o", header: "Vaqtida / kutilgan", cell: (r) => `${r.on_time} / ${r.expected}` },
            ...(state.mode === "m"
              ? [
                  { key: "l", header: "Kech", cell: (r: StatRow) => `${r.late}${r.late_min ? ` (${r.late_min} daq)` : ""}` },
                  { key: "a", header: "Kelmadi", cell: (r: StatRow) => r.absent },
                  { key: "e", header: "Erta ketdi", cell: (r: StatRow) => r.left_early, hideOnMobile: true },
                ]
              : [{ key: "w", header: "🏆 Oy xodimi", cell: (r: StatRow) => r.wins || "—" }]),
            { key: "d", header: "Intizom", cell: (r) => `${r.discipline}%` },
            { key: "b", header: "Bonus / rahbar", cell: (r) => `${r.bonus ? `+${r.bonus}` : "—"} / ${r.adjust ? (r.adjust > 0 ? `+${r.adjust}` : r.adjust) : "—"}`, hideOnMobile: true },
            {
              key: "x",
              header: "",
              cell: (r) =>
                !won && can("hr.add_winner") && data!.rows.indexOf(r) < 3 ? (
                  <Button size="sm" variant="outline" icon={<Trophy className="h-4 w-4" />} onClick={() => confirm(`${r.name} — guruhlarda e'lon qilinsinmi?`) && announce.mutate(r.employee_id)}>
                    E'lon qilish
                  </Button>
                ) : null,
            },
          ]}
        />
      </Card>
      {!!adj?.results.length && (
        <Card title="Qo'shimcha ballar" className="mt-4" padded={false}>
          <DataTable
            rows={adj.results}
            rowKey={(r) => r.id}
            columns={[
              { key: "d", header: "Sana", cell: (r) => date(r.day) },
              { key: "n", header: "Xodim", cell: (r) => r.employee_name },
              { key: "v", header: "Ball", cell: (r) => <b className={r.value < 0 ? "text-rose-600" : "text-emerald-600"}>{r.value > 0 ? `+${r.value}` : r.value}</b> },
              { key: "r", header: "Sabab", cell: (r) => r.reason || "—" },
              {
                key: "x",
                header: "",
                cell: (r) =>
                  can("hr.delete_pointadjustment") && (
                    <IconButton label="O'chirish" onClick={() => confirm("O'chirilsinmi?") && removeAdj.mutate(r.id)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  ),
              },
            ]}
          />
        </Card>
      )}
      {give && <GivePointsModal onClose={() => setGive(false)} />}
    </div>
  );
}

function GivePointsModal({ onClose }: { onClose: () => void }) {
  const { data: emps } = useAll<Employee>("hr/employees", { active: "1" });
  const [f, setF] = useState({ employee: "", value: "10", reason: "", day: new Date().toISOString().slice(0, 10) });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(() => api.post("/hr/points/", { ...f, employee: Number(f.employee), value: Number(f.value) }), {
    success: "Yozildi (xodimga xabar ketdi)",
    invalidate: ["hr"],
    onSuccess: onClose,
  });
  return (
    <Modal open onClose={onClose} title="Qo'shimcha ball" size="sm" footer={<Button disabled={!f.employee} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}>
      <div className="space-y-3">
        <Field label="Xodim" error={errors.employee}>
          <Select value={f.employee} onChange={(e) => setF({ ...f, employee: e.target.value })}>
            <option value="">—</option>
            {emps?.map((e) => <option key={e.id} value={e.id}>#{e.number} {e.name}</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Ball (−100…100)" error={errors.value}>
            <Input type="number" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />
          </Field>
          <Field label="Sana" error={errors.day}>
            <Input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} />
          </Field>
        </div>
        <Field label="Sabab">
          <Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Mijozdan rahmat oldi" />
        </Field>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ employees */
export function HrEmployeesPage() {
  const { can } = useAuth();
  const [active, setActive] = useState("1");
  const [search, setSearch] = useState("");
  const { data, isFetching } = useAll<Employee>("hr/employees", active ? { active } : {});
  const [edit, setEdit] = useState<Employee | null>(null);
  const rows = (data ?? []).filter((e) => !search || `${e.name} ${e.username} ${e.number}`.toLowerCase().includes(search.toLowerCase()));
  return (
    <div>
      <PageHeader title="Xodimlar (davomat)" subtitle="Ish guruhiga video-doiracha tashlaganlar avtomatik qo'shiladi" />
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={search} onChange={setSearch} placeholder="Ism yoki №" />
          <Segmented value={active} onChange={setActive} options={[{ value: "1", label: "Faol" }, { value: "0", label: "Chiqarilgan" }, { value: "", label: "Hammasi" }]} />
        </div>
        <DataTable
          rows={rows}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={can("hr.change_employee") ? setEdit : undefined}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="muted">#{r.number}</span> },
            { key: "m", header: "Ism", cell: (r) => <span className="font-medium">{r.name}{r.username && <span className="muted ml-1 text-xs">@{r.username}</span>}</span> },
            { key: "g", header: "Filial", cell: (r) => r.group_title || "—", hideOnMobile: true },
            { key: "h", header: "Ish vaqti", cell: (r) => <span>{r.hours}{!r.work_start && <span className="muted text-xs"> (umumiy)</span>}</span> },
            { key: "o", header: "Dam kunlari", cell: (r) => (r.off_days_effective.length ? r.off_days_effective.map((d) => WD[d - 1]).join(", ") : <Badge tone="warn">belgilanmagan</Badge>) },
            { key: "b", header: "Bot", cell: (r) => (r.can_dm === false ? <Badge tone="danger">ulanmagan</Badge> : r.can_dm ? <Badge tone="ok">ulangan</Badge> : <Badge>noma'lum</Badge>), hideOnMobile: true },
          ]}
        />
      </Card>
      {edit && <EmployeeModal e={edit} onClose={() => setEdit(null)} />}
    </div>
  );
}

function EmployeeModal({ e, onClose }: { e: Employee; onClose: () => void }) {
  const { user } = useAuth();
  const { data: groups } = useAll<Group>("hr/groups");
  const [askDel, setAskDel] = useState(false);
  const remove = useAction(() => api.delete(`/hr/employees/${e.id}/`), { success: "O'chirildi", invalidate: ["hr"], onSuccess: onClose });
  const [f, setF] = useState({ name: e.name, is_active: e.is_active, group: e.group, work_start: e.work_start, work_end: e.work_end, own_off: !!e.off_days, off: e.off_days ?? [] });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () =>
      api.patch(`/hr/employees/${e.id}/`, {
        name: f.name,
        is_active: f.is_active,
        group: f.group,
        work_start: f.work_start,
        work_end: f.work_end,
        off_days: f.own_off ? f.off : null,
      }),
    { success: "Saqlandi", invalidate: ["hr"], onSuccess: onClose },
  );
  const toggle = (d: number) => setF({ ...f, off: f.off.includes(d) ? f.off.filter((x) => x !== d) : [...f.off, d].sort() });
  return (
    <Modal
      open
      onClose={onClose}
      title={`#${e.number} ${e.name}`}
      size="sm"
      footer={
        <>
          {user?.is_superuser && (
            <Button variant="ghost" className="mr-auto text-rose-600" icon={<Trash2 className="h-4 w-4" />} onClick={() => setAskDel(true)}>
              O'chirish
            </Button>
          )}
          <Button loading={save.isPending} onClick={() => save.mutateAsync().catch((x) => setErrors(fieldErrors(x)))}>Saqlash</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Ism" error={errors.name}>
          <Input value={f.name} onChange={(x) => setF({ ...f, name: x.target.value })} />
        </Field>
        <Field label="Filial">
          <Select value={f.group ?? ""} onChange={(x) => setF({ ...f, group: x.target.value ? Number(x.target.value) : null })}>
            <option value="">—</option>
            {groups?.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Ish boshlanishi" hint="bo'sh — umumiy vaqt" error={errors.work_start}>
            <Input type="time" value={f.work_start} onChange={(x) => setF({ ...f, work_start: x.target.value })} />
          </Field>
          <Field label="Ish tugashi" error={errors.work_end}>
            <Input type="time" value={f.work_end} onChange={(x) => setF({ ...f, work_end: x.target.value })} />
          </Field>
        </div>
        <div>
          <label className="mb-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.own_off} onChange={(x) => setF({ ...f, own_off: x.target.checked })} /> O'z dam kunlari (aks holda umumiy sozlama)
          </label>
          {f.own_off && (
            <div className="flex flex-wrap gap-1">
              {WD.map((w, i) => (
                <Button key={w} size="sm" variant={f.off.includes(i + 1) ? "primary" : "outline"} onClick={() => toggle(i + 1)}>
                  {w}
                </Button>
              ))}
            </div>
          )}
          {errors.off_days && <p className="mt-1 text-xs text-rose-600">{errors.off_days}</p>}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.is_active} onChange={(x) => setF({ ...f, is_active: x.target.checked })} /> Faol (davomat kuzatiladi)
        </label>
      </div>
      <Confirm
        open={askDel}
        onClose={() => setAskDel(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        variant="danger"
        confirmLabel="O'chirish"
        title="Xodimni o'chirish"
        text={
          <>
            <b>{e.name}</b> va uning butun davomat tarixi (kelish-ketish, ballar, ta'tillar) o'chiriladi. Faqat ishdan ketgan bo'lsa, «Faol» belgisini olib qo'yish kifoya.
          </>
        }
      />
    </Modal>
  );
}

/* ------------------------------------------------------------------ calendar */
interface Holiday { id: number; day: string; name: string }
interface Leave { id: number; number: number; employee: number; employee_name: string; date_from: string; date_to: string; reason: string }

export function HrCalendarPage() {
  const { can } = useAuth();
  const { data: holidays } = useAll<Holiday>("hr/holidays", { upcoming: "1" });
  const { data: leaves } = useAll<Leave>("hr/leaves");
  const { data: emps } = useAll<Employee>("hr/employees", { active: "1" });
  const [h, setH] = useState({ day: "", name: "" });
  const [l, setL] = useState({ employee: "", date_from: "", date_to: "", reason: "ta'til" });
  const addH = useAction(() => api.post("/hr/holidays/", h), { success: "Qo'shildi", invalidate: ["hr"], onSuccess: () => setH({ day: "", name: "" }) });
  const delH = useAction((id: number) => api.delete(`/hr/holidays/${id}/`), { success: "O'chirildi", invalidate: ["hr"] });
  const addL = useAction(() => api.post("/hr/leaves/", { ...l, employee: Number(l.employee) }), { success: "Qo'shildi", invalidate: ["hr"], onSuccess: () => setL({ employee: "", date_from: "", date_to: "", reason: "ta'til" }) });
  const delL = useAction((id: number) => api.delete(`/hr/leaves/${id}/`), { success: "O'chirildi", invalidate: ["hr"] });
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div>
      <PageHeader title="Bayramlar va ta'tillar" subtitle="Bu kunlarda otchet so'ralmaydi va «kelmadi» yozilmaydi. Bayramdan 3 kun oldin bot o'zi so'raydi." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="🎉 Bayramlar (dam kunlari)" padded={false}>
          {can("hr.add_holiday") && (
            <div className="flex gap-2 border-b border-slate-100 p-4 dark:border-slate-800">
              <Input type="date" value={h.day} onChange={(e) => setH({ ...h, day: e.target.value })} />
              <Input placeholder="Yangi yil" value={h.name} onChange={(e) => setH({ ...h, name: e.target.value })} />
              <Button disabled={!h.day || !h.name} onClick={() => addH.mutate()}>Qo'shish</Button>
            </div>
          )}
          <DataTable
            rows={holidays}
            rowKey={(r) => r.id}
            columns={[
              { key: "d", header: "Sana", cell: (r) => date(r.day) },
              { key: "n", header: "Bayram", cell: (r) => r.name },
              { key: "x", header: "", cell: (r) => can("hr.delete_holiday") && <IconButton label="O'chirish" onClick={() => delH.mutate(r.id)}><Trash2 className="h-4 w-4" /></IconButton> },
            ]}
          />
        </Card>
        <Card title="🏖 Ta'til / kasallik" padded={false}>
          {can("hr.add_leave") && (
            <div className="grid gap-2 border-b border-slate-100 p-4 sm:grid-cols-2 dark:border-slate-800">
              <Select value={l.employee} onChange={(e) => setL({ ...l, employee: e.target.value })}>
                <option value="">Xodim</option>
                {emps?.map((e) => <option key={e.id} value={e.id}>#{e.number} {e.name}</option>)}
              </Select>
              <Input placeholder="Sabab" value={l.reason} onChange={(e) => setL({ ...l, reason: e.target.value })} />
              <Input type="date" value={l.date_from} onChange={(e) => setL({ ...l, date_from: e.target.value, date_to: l.date_to || e.target.value })} />
              <Input type="date" value={l.date_to} onChange={(e) => setL({ ...l, date_to: e.target.value })} />
              <Button className="sm:col-span-2" disabled={!l.employee || !l.date_from} onClick={() => addL.mutate()}>Qo'shish</Button>
            </div>
          )}
          <DataTable
            rows={leaves?.filter((x) => x.date_to >= today)}
            rowKey={(r) => r.id}
            columns={[
              { key: "n", header: "Xodim", cell: (r) => r.employee_name },
              { key: "d", header: "Davr", cell: (r) => `${date(r.date_from)} — ${date(r.date_to)}` },
              { key: "r", header: "Sabab", cell: (r) => r.reason },
              { key: "x", header: "", cell: (r) => can("hr.delete_leave") && <IconButton label="O'chirish" onClick={() => delL.mutate(r.id)}><Trash2 className="h-4 w-4" /></IconButton> },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ settings */
export function HrSettingsPage() {
  const { can } = useAuth();
  const { data } = useGet<{ values: Record<string, string>; labels: Record<string, string> }>("/hr/settings/");
  const { data: groups } = useAll<Group>("hr/groups");
  const [f, setF] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => data && setF(data.values), [data]);
  const save = useAction(() => api.patch("/hr/settings/", f), { success: "Saqlandi", invalidate: ["hr"] });
  const toggleGroup = useAction((g: Group) => api.patch(`/hr/groups/${g.id}/`, { is_active: !g.is_active }), { success: "Saqlandi", invalidate: ["hr"] });
  const select: Record<string, string[]> = {
    CHECKIN_MODE: ["video_note", "media", "keyword", "media_or_keyword", "any"],
    GROUP_ACK: ["reaction", "reply", "none"],
  };
  const bools = ["UNIFORM_CHECK", "GROUP_REMIND", "GROUP_LIST_MISSING", "MANAGER_LIVE_ALERTS"];
  return (
    <div>
      <PageHeader title="Davomat sozlamalari" subtitle="Botdagi /dsozla bilan bir xil" />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Parametrlar" actions={can("hr.change_workgroup") && <Button size="sm" loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}>
          <div className="grid gap-4 sm:grid-cols-2">
            {Object.keys(data?.values ?? {}).map((k) => (
              <Field key={k} label={data!.labels[k] ?? k} error={errors[k]}>
                {select[k] ? (
                  <Select value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
                    {select[k].map((o) => <option key={o} value={o}>{o}</option>)}
                  </Select>
                ) : bools.includes(k) ? (
                  <Select value={f[k] ?? "0"} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
                    <option value="1">Ha</option>
                    <option value="0">Yo'q</option>
                  </Select>
                ) : (
                  <Input value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder={k === "OFF_DAYS" ? "6,7 (1=Du … 7=Ya)" : undefined} />
                )}
              </Field>
            ))}
          </div>
        </Card>
        <Card title="🏢 Ish guruhlari" padded={false}>
          <p className="muted border-b border-slate-100 p-4 text-xs dark:border-slate-800">
            Yangi guruh: botni guruhga qo'shing, admin qiling va guruhda /ulash yozing.
          </p>
          <DataTable
            rows={groups}
            rowKey={(r) => r.id}
            columns={[
              { key: "t", header: "Guruh", cell: (r) => <span className="font-medium">{r.title}</span> },
              { key: "e", header: "Xodim", cell: (r) => r.employees },
              {
                key: "a",
                header: "Kuzatish",
                cell: (r) => <input type="checkbox" checked={r.is_active} disabled={!can("hr.change_workgroup")} onChange={() => toggleGroup.mutate(r)} />,
              },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
