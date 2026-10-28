import { useState } from "react";
import { ChevronLeft, ChevronRight, Download, Pencil } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useAll, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Button, Card, Chip, DataTable, IconButton, Input, PageHeader, Pagination, SearchInput, Select, StatTile } from "@/components/ui";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { downloadFile } from "@/pages/finance/shared";
import { AttendanceModal, STATUS, StatusBadge, hhmm, type Attendance, type DayBoard, type DayRow, type Employee, type Status } from "./shared";

function shift(d: string, n: number) {
  const x = new Date(d + "T00:00:00");
  x.setDate(x.getDate() + n);
  return iso(x);
}

function Times({ r }: { r: Pick<DayRow, "in_time" | "out_time" | "late_min" | "early_min" | "eta"> }) {
  return (
    <span className="whitespace-nowrap tabular-nums">
      {r.in_time || "—"} → {r.out_time || "—"}
      {!!r.late_min && <span className="ml-1 text-xs text-amber-600">+{r.late_min} daq</span>}
      {!!r.early_min && <span className="ml-1 text-xs text-rose-600">−{r.early_min} daq</span>}
      {!r.in_time && r.eta && <span className="muted ml-1 text-xs">({r.eta} da keladi)</span>}
    </span>
  );
}

export function HrTodayPage() {
  const { can } = useAuth();
  const today = iso(new Date());
  const { state, set } = useUrlState({ date: today, status: "" });
  const { data, isFetching } = useGet<DayBoard>("/hr/day/", { date: state.date });
  const [edit, setEdit] = useState<DayRow | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const ensure = useAction((r: DayRow) => api.post<Attendance>("/hr/attendance/ensure/", { employee: r.employee_id, day: state.date }), {
    onSuccess: (res) => setEditId((res as { data: Attendance }).data.id),
  });
  const rows = (data?.rows ?? []).filter((r) => !state.status || r.status === state.status);
  const c = data?.counts ?? {};
  const came = (c.on_time ?? 0) + (c.late ?? 0);
  const canEdit = can("hr.change_attendance");

  return (
    <div>
      <PageHeader
        title="Davomat"
        subtitle={data ? `${date(data.date)}${data.now ? ` · hozir ${data.now}` : ""}${data.holiday ? ` · 🎉 ${data.holiday}` : ""}` : ""}
        actions={
          <div className="flex items-center gap-1">
            <IconButton label="Oldingi kun" onClick={() => set({ date: shift(state.date, -1) })}>
              <ChevronLeft className="h-4 w-4" />
            </IconButton>
            <Input type="date" className="w-40" value={state.date} max={today} onChange={(e) => set({ date: e.target.value || today })} />
            <IconButton label="Keyingi kun" disabled={state.date >= today} onClick={() => set({ date: shift(state.date, 1) })}>
              <ChevronRight className="h-4 w-4" />
            </IconButton>
            {state.date !== today && <Button variant="outline" onClick={() => set({ date: today })}>Bugun</Button>}
          </div>
        }
      />
      <div className={`mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 ${isFetching ? "opacity-70" : ""}`}>
        <StatTile label="👥 Kutilgan" value={data?.expected ?? 0} tone="primary" hint={`keldi: ${came}`} />
        <StatTile label="✅ Vaqtida" value={c.on_time ?? 0} tone="ok" hint={data?.expected ? `${Math.round(((c.on_time ?? 0) * 100) / data.expected)}%` : undefined} />
        <StatTile label="⏰ Kech" value={c.late ?? 0} tone="warn" />
        <StatTile label="⏳ Hali kelmagan" value={c.waiting ?? 0} tone="info" />
        <StatTile label="❌ Kelmadi" value={c.absent ?? 0} tone="danger" />
        <StatTile label="📝 Sababli / dam" value={(c.excused ?? 0) + (c.off ?? 0) + (c.leave ?? 0) + (c.holiday ?? 0)} tone="idle" />
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        <Chip active={!state.status} onClick={() => set({ status: "" })}>Hammasi</Chip>
        {(Object.keys(STATUS) as Status[])
          .filter((s) => c[s])
          .map((s) => (
            <Chip key={s} active={state.status === s} tone={STATUS[s].tone} onClick={() => set({ status: s })}>
              {STATUS[s].label} · {c[s]}
            </Chip>
          ))}
      </div>
      <Card padded={false}>
        <DataTable
          rows={rows}
          loading={isFetching}
          rowKey={(r) => r.employee_id}
          columns={[
            {
              key: "n",
              header: "Xodim",
              cell: (r) => (
                <span>
                  <span className="muted mr-1 text-xs">#{r.number}</span>
                  <span className="font-medium">{r.name}</span>
                  {r.can_dm === false && <span title="Botga ulanmagan" className="ml-1">⚠️</span>}
                </span>
              ),
            },
            { key: "g", header: "Filial", cell: (r) => r.group || "—", hideOnMobile: true },
            { key: "s", header: "Holat", cell: (r) => <StatusBadge s={r.status} /> },
            { key: "t", header: "Keldi → ketdi", cell: (r) => <Times r={r} /> },
            {
              key: "r",
              header: "Sabab / izoh",
              cell: (r) => (
                <span className="line-clamp-2 max-w-xs text-sm">
                  {[r.late_reason && `${r.late_reason}${r.late_comment ? `: ${r.late_comment}` : ""}`, r.early_reason && `Erta: ${r.early_reason}${r.early_comment ? `: ${r.early_comment}` : ""}`, r.note]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </span>
              ),
              hideOnMobile: true,
            },
            { key: "u", header: "Forma", cell: (r) => (r.uniform === true ? "👕" : r.uniform === false ? "✗" : "—"), hideOnMobile: true },
            { key: "h", header: "Ish vaqti", cell: (r) => <span className="muted text-xs">{r.hours}</span>, hideOnMobile: true },
            { key: "p", header: "Ball", cell: (r) => (r.points === null ? "—" : <b className={r.points < 0 ? "text-rose-600" : "text-emerald-600"}>{r.points > 0 ? `+${r.points}` : r.points}</b>) },
            {
              key: "x",
              header: "",
              cell: (r) => (
                <div className="flex justify-end gap-1">
                  {r.link && (
                    <a className="text-xs text-brand-600 underline" href={r.link} target="_blank" rel="noreferrer">
                      otchet
                    </a>
                  )}
                  {canEdit && state.date <= today && (
                    <IconButton label="Tuzatish" onClick={() => (r.attendance_id ? (setEdit(r), setEditId(r.attendance_id)) : (setEdit(r), ensure.mutate(r)))}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>
      {edit && editId && (
        <AttendanceModal
          id={editId}
          title={`${edit.name} · ${date(state.date)}`}
          initial={{ ...edit, in_time: edit.in_time || null, out_time: edit.out_time || null, excuse: edit.note } as Partial<Attendance>}
          onClose={() => (setEdit(null), setEditId(null))}
        />
      )}
    </div>
  );
}

export function HrJournalPage() {
  const { can } = useAuth();
  const { state, page, set } = useUrlState({ date_from: monthStartISO(), date_to: iso(new Date()), employee: "", status: "", search: "" });
  const { data, isFetching } = useList<Attendance>("hr/attendance", { ...state, page });
  const { data: emps } = useAll<Employee>("hr/employees");
  const [edit, setEdit] = useState<Attendance | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <PageHeader
        title="Davomat jurnali"
        subtitle="Har kungi keldi-ketdi yozuvlari (eski Google «Davomat» varag'i)"
        actions={
          <Button
            variant="outline"
            icon={<Download className="h-4 w-4" />}
            loading={busy}
            onClick={() => {
              setBusy(true);
              downloadFile("/hr/export/", { date_from: state.date_from, date_to: state.date_to }, "Davomat.xlsx").finally(() => setBusy(false));
            }}
          >
            Excel
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(search) => set({ search })} placeholder="Ism yoki izoh" />
          <Select className="sm:w-56" value={state.employee} onChange={(e) => set({ employee: e.target.value })}>
            <option value="">Barcha xodimlar</option>
            {emps?.map((e) => <option key={e.id} value={e.id}>#{e.number} {e.name}</option>)}
          </Select>
          <Select className="sm:w-48" value={state.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">Barcha holatlar</option>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={can("hr.change_attendance") ? setEdit : undefined}
          columns={[
            { key: "d", header: "Sana", cell: (r) => date(r.day) },
            { key: "n", header: "Xodim", cell: (r) => <span className="font-medium">{r.employee_name}</span> },
            { key: "s", header: "Holat", cell: (r) => <StatusBadge s={r.status} /> },
            { key: "t", header: "Keldi → ketdi", cell: (r) => <Times r={{ in_time: hhmm(r.in_time), out_time: hhmm(r.out_time), late_min: r.late_min, early_min: r.early_min, eta: hhmm(r.eta) }} /> },
            { key: "c", header: "Izoh", cell: (r) => <span className="line-clamp-1 max-w-xs text-sm">{r.late_comment || r.early_comment || r.excuse || r.note || "—"}</span>, hideOnMobile: true },
            { key: "p", header: "Ball", cell: (r) => (r.points ?? (r.finalized ? "—" : <span className="muted text-xs">bugun</span>)) },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {edit && <AttendanceModal id={edit.id} title={`${edit.employee_name} · ${date(edit.day)}`} initial={edit} onClose={() => setEdit(null)} />}
    </div>
  );
}
