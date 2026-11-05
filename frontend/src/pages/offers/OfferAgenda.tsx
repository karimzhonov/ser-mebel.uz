import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { AlarmClockOff, CalendarCheck, ChevronRight } from "lucide-react";
import { useGet, useList } from "@/api/hooks";
import type { Design, OfferAgenda as Agenda, OfferKind, Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, PhoneLink } from "@/components/domain";
import { Button, Card, DataTable, Empty, PageHeader, PageLoader, Pagination, SearchInput, Segmented, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { date } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { dayLabel, personName, timeOnly } from "../meterings/actions";
import {
  ARCHIVE_STAGES,
  ASSIGNEE_LABEL,
  DueButton,
  DueLabel,
  OFFER_PATH,
  OFFER_TITLE,
  OfferStageBadge,
  useAssignees,
  useCanWork,
} from "./actions";

type Row = Design | Price;
type Tab = "overdue" | "today" | "work" | "review" | "archive";
const TABS: Tab[] = ["overdue", "today", "work", "review", "archive"];

function clientOf(r: Row) {
  const m = r.metering;
  return {
    fio: m?.client.fio ?? (r as Price).desc ?? `#${r.id}`,
    phone: m?.client.phone,
    metering: m,
  };
}

function assigneeOf(r: Row) {
  return r.user_detail;
}

/** «Dizayn» / «Narx hisoblash» — the designer's / pricer's task list: deadline first,
 * overdue on top in red, then today / everything in work / at the client / the archive.
 * The same look as the zamer agenda (big time on the left, big buttons on a phone). */
export function OfferAgenda({ kind, actions }: { kind: OfferKind; actions?: ReactNode }) {
  const navigate = useNavigate();
  const { can } = useAuth();
  // a superuser (can() is always true for them) or «Bosh menejer» sees everyone's rows
  const manager = can("metering.manage_metering");
  const { state, page, set } = useUrlState({ tab: "work", user: "", search: "" });
  const tab: Tab = (TABS as string[]).includes(state.tab) ? (state.tab as Tab) : "work";
  const people = useAssignees(manager);
  const staff = (kind === "design" ? people.data?.designers : people.data?.pricers) ?? [];
  const filter = { user: manager ? state.user : "", search: state.search };
  const { data: agenda, isLoading } = useGet<Agenda<Row>>(`/${OFFER_PATH[kind]}/agenda/`, filter);
  const archive = useList<Row>(OFFER_PATH[kind], { ...filter, stage: ARCHIVE_STAGES, page }, tab === "archive");
  const c = agenda?.counts;
  const open = (r: Row) => navigate(`/${OFFER_PATH[kind]}/${r.id}`);
  const overdueIds = new Set((agenda?.overdue ?? []).map((r) => r.id));

  const list = (rows: Row[], opts: { late?: boolean; review?: boolean } = {}) => (
    <OfferList kind={kind} rows={rows} showAssignee={manager} onOpen={open} {...opts} />
  );

  let body: ReactNode = null;
  if (tab === "archive") {
    body = (
      <Card padded={false}>
        <DataTable
          rows={archive.data?.results}
          loading={archive.isFetching}
          rowKey={(r) => r.id}
          onRowClick={open}
          columns={[
            { key: "client", header: "Mijoz", cell: (r) => <span className="font-medium">{clientOf(r).fio}</span> },
            { key: "stage", header: "Holat", cell: (r) => <OfferStageBadge stage={r.stage} label={r.stage_label} /> },
            ...(manager ? [{ key: "user", header: ASSIGNEE_LABEL[kind], cell: (r: Row) => personName(assigneeOf(r)) }] : []),
            { key: "done", header: "Tayyor bo'lgan", cell: (r) => <span className="muted">{date(r.done_at)}</span> },
            { key: "created", header: "Yaratilgan", cell: (r) => <span className="muted">{date(r.created_at)}</span>, hideOnMobile: true },
          ]}
          mobileCard={(r) => (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{clientOf(r).fio}</span>
                <OfferStageBadge stage={r.stage} label={r.stage_label} />
              </div>
              <div className="muted text-sm">
                {date(r.done_at ?? r.created_at)}
                {manager && ` · ${personName(assigneeOf(r))}`}
              </div>
            </div>
          )}
        />
        <Pagination page={page} count={archive.data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
    );
  } else if (isLoading || !agenda) {
    body = <PageLoader />;
  } else {
    const rows =
      tab === "work" ? agenda.work.filter((r) => !overdueIds.has(r.id)) : tab === "overdue" ? agenda.overdue : agenda[tab] ?? [];
    body = (
      <div className="space-y-4">
        <Card padded={false}>
          {rows.length ? (
            list(rows, { late: tab === "overdue", review: tab === "review" })
          ) : (
            <Empty
              icon={<CalendarCheck className="h-6 w-6" />}
              title={
                tab === "overdue"
                  ? "Muddati o'tgan ish yo'q"
                  : tab === "today"
                    ? "Bugunga muddat yo'q"
                    : tab === "review"
                      ? "Mijozda kutilayotgan ish yo'q"
                      : agenda.overdue.length
                        ? "Boshqa ish yo'q"
                        : "Ishda hech narsa yo'q"
              }
            />
          )}
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={OFFER_TITLE[kind]} subtitle={kind === "design" ? "Dizayn vazifalari — muddat bo'yicha" : "Narx hisoblash vazifalari — muddat bo'yicha"} actions={actions} />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <Segmented
          value={tab}
          onChange={(v) => set({ tab: v })}
          options={[
            { value: "overdue", label: <span className={cn(c?.overdue ? "text-rose-600 dark:text-rose-400" : "")}>Muddati o'tgan</span>, count: c?.overdue },
            { value: "today", label: "Bugun", count: c?.today },
            { value: "work", label: "Ishda", count: c?.work },
            { value: "review", label: "Mijozda — javob kutilmoqda", count: c?.review },
            { value: "archive", label: "Arxiv", count: c?.archive },
          ]}
        />
        <div className="flex flex-1 flex-col gap-2 sm:flex-row lg:justify-end">
          <SearchInput className="sm:max-w-xs sm:flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Mijoz yoki telefon" />
          {manager && (
            <Select className="sm:w-auto sm:min-w-[200px]" value={state.user} onChange={(e) => set({ user: e.target.value })}>
              <option value="">Barcha xodimlar</option>
              <option value="me">Mening vazifalarim</option>
              {staff.map((u) => (
                <option key={u.id} value={u.id}>{personName(u)}</option>
              ))}
            </Select>
          )}
        </div>
      </div>

      {(tab === "today" || tab === "work") && !!agenda?.overdue.length && (
        <Card
          className="mb-4 border-rose-200 dark:border-rose-500/30"
          padded={false}
          title={
            <span className="flex items-center gap-2 text-rose-600 dark:text-rose-400">
              <AlarmClockOff className="h-4 w-4" /> Muddati o'tdi · {agenda.overdue.length}
            </span>
          }
        >
          {list(agenda.overdue, { late: true })}
        </Card>
      )}
      {body}
    </div>
  );
}

function OfferList({
  kind,
  rows,
  late,
  review,
  showAssignee,
  onOpen,
}: {
  kind: OfferKind;
  rows: Row[];
  late?: boolean;
  review?: boolean;
  showAssignee?: boolean;
  onOpen: (r: Row) => void;
}) {
  const canWork = useCanWork(kind);
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {rows.map((r) => {
        const cl = clientOf(r);
        const m = cl.metering;
        const red = late || r.is_overdue;
        const when = review ? r.done_at : r.due_at;
        const moveDue = r.stage === "work" && (r.actions?.due ?? canWork(assigneeOf(r)));
        return (
          <li
            key={r.id}
            onClick={() => onOpen(r)}
            className={cn("cursor-pointer px-4 py-4 transition hover:bg-slate-50 sm:px-5 dark:hover:bg-slate-800/40", red && "bg-rose-50/40 dark:bg-rose-500/[.04]")}
          >
            <div className="flex gap-4">
              <div className="w-16 shrink-0 sm:w-20">
                {when ? (
                  <>
                    <div className={cn("text-2xl font-bold tabular-nums leading-none tracking-tight", red ? "text-rose-600 dark:text-rose-400" : "text-slate-900 dark:text-white")}>
                      {timeOnly(when)}
                    </div>
                    <div className={cn("mt-1 text-xs leading-tight", red ? "font-medium text-rose-600 dark:text-rose-400" : "muted")}>{dayLabel(when)}</div>
                    {review && <div className="muted mt-1 text-[11px] leading-tight">tayyor bo'ldi</div>}
                  </>
                ) : (
                  <div className="muted text-xs leading-tight">Muddat yo'q</div>
                )}
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-base font-semibold text-slate-900 dark:text-white">{cl.fio}</span>
                  {(r.round ?? 1) > 1 && (
                    <span className="rounded-md bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-200">
                      {r.round}-raund
                    </span>
                  )}
                  {review && <OfferStageBadge stage={r.stage} label={r.stage_label} />}
                </div>
                {cl.phone && (
                  <div className="text-sm">
                    <PhoneLink value={cl.phone} />
                  </div>
                )}
                {m && (
                  <div className="text-sm">
                    <AddressLink nested address={m.address} link={m.address_link} mapUrl={m.map_url} lat={m.lat} lon={m.lon} empty="Manzil yo'q" />
                  </div>
                )}
                {r.last_comment && (r.round ?? 1) > 1 && (
                  <div className="line-clamp-2 rounded-lg bg-amber-50 px-2.5 py-1 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
                    ✏️ {r.last_comment}
                  </div>
                )}
                <div className="muted flex flex-wrap gap-x-3 text-xs">
                  {!review && r.due_at && (
                    <span>
                      Muddat: <DueLabel value={r.due_at} overdue={red} className="text-xs" />
                    </span>
                  )}
                  {showAssignee && <span>{ASSIGNEE_LABEL[kind]}: {personName(assigneeOf(r), "tayinlanmagan")}</span>}
                  {r.manager && <span>Menejer: {personName(r.manager)}</span>}
                  {r.measurer && <span>Zamerchi: {personName(r.measurer)}</span>}
                </div>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 sm:pl-24" onClick={(e) => e.stopPropagation()}>
              <Button size="lg" className="flex-1 basis-[calc(50%-4px)] sm:flex-none sm:basis-auto" icon={<ChevronRight className="h-5 w-5" />} onClick={() => onOpen(r)}>
                Ochish
              </Button>
              {moveDue && <DueButton big kind={kind} id={r.id} dueAt={r.due_at ?? null} className="flex-1 basis-[calc(50%-4px)] sm:flex-none sm:basis-auto" />}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
