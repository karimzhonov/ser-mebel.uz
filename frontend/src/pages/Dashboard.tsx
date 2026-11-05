import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlarmClockOff, CalendarClock, CalendarDays, ChevronRight, Clock, Columns3, Factory, LayoutGrid, ListChecks, PartyPopper, Phone } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { Board, TaskAgenda } from "@/api/types";
import { LeadDetailModal } from "@/pages/callcenter/LeadDetailModal";
import { TaskRow } from "@/pages/callcenter/shared";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { AddressLink, DeadlinePill, MoneyLeft } from "@/components/domain";
import { OverviewPanel } from "@/components/Overview";
import { useUrlState } from "@/lib/useUrlState";
import { Badge, Button, Card, Check, Empty, PageHeader, PageLoader, Segmented, StatTile, TONES } from "@/components/ui";
import { cn } from "@/lib/cn";
import { dateTime, phone } from "@/lib/format";

const LIST_URL: Record<Board["id"], (col: string) => string> = {
  orders: () => "/orders",
  meterings: () => "/meterings",
  callcenter: () => "/call-center",
};

export default function DashboardPage() {
  const { user, can } = useAuth();
  // owner's rule: the operator gets no boards — the overview plus a short note of today's work
  const operator = !!user && !user.is_superuser && can("oauth.user_call_center");
  const { state, set } = useUrlState({ tab: "overview", date_from: monthStartISO(), date_to: iso(new Date()) });
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Xayrli tong" : hour < 18 ? "Xayrli kun" : "Xayrli kech";
  const tab = operator ? "overview" : state.tab;

  return (
    <div>
      <PageHeader
        title={`${greet}${user?.name ? ", " + user.name : ""}`}
        subtitle="Ishlab chiqarishning barcha jarayonlari — bitta ekranda"
        actions={
          tab === "overview" && (
            <DateRangeFilter
              from={state.date_from}
              to={state.date_to}
              onChange={(date_from, date_to) => set({ date_from, date_to })}
            />
          )
        }
      />
      {operator ? (
        <TodayWork />
      ) : (
        <Segmented
          className="mb-4"
          value={tab}
          onChange={(tab) => set({ tab })}
          options={[
            { value: "overview", label: <span className="flex items-center gap-1.5"><LayoutGrid className="h-4 w-4" /> Umumiy ko'rinish</span> },
            { value: "board", label: <span className="flex items-center gap-1.5"><Columns3 className="h-4 w-4" /> Doska</span> },
          ]}
        />
      )}
      {tab === "board" ? <Boards /> : <OverviewPanel from={state.date_from} to={state.date_to} />}
    </div>
  );
}

/** The operator's calls: overdue / today / later, and the first ones of today. */
function TodayWork() {
  const navigate = useNavigate();
  const { data } = useGet<TaskAgenda>("/invoice-tasks/agenda/");
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");
  const open = (id: number) => setSearchParams((p) => (p.set("open", String(id)), p));
  const now = [...(data?.overdue ?? []), ...(data?.today ?? [])];
  return (
    <Card
      className="mb-4"
      title="Bugungi ishlaringiz"
      actions={
        <Button size="sm" variant="outline" icon={<ListChecks className="h-4 w-4" />} onClick={() => navigate("/call-center/tasks")}>
          Barcha vazifalar
        </Button>
      }
    >
      {!data ? (
        <PageLoader />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <StatTile label="Muddati o'tgan" value={data.overdue.length} tone="danger" icon={<AlarmClockOff className="h-5 w-5" />} />
            <StatTile label="Bugun" value={data.today.length} tone="warn" icon={<CalendarClock className="h-5 w-5" />} />
            <StatTile label="Keyingi kunlar" value={data.upcoming.length} tone="info" icon={<CalendarDays className="h-5 w-5" />} />
          </div>
          {now.length ? (
            <div className="mt-4 grid gap-2 lg:grid-cols-2">
              {now.slice(0, 6).map((t) => (
                <TaskRow key={t.id} task={t} showClient onOpen={() => open(t.invoice.id)} />
              ))}
            </div>
          ) : (
            <p className="muted mt-4 flex items-center gap-2 text-sm">
              <PartyPopper className="h-4 w-4" /> Bugunga qo'ng'iroq vazifasi yo'q.
            </p>
          )}
          {now.length > 6 && (
            <p className="muted mt-3 text-sm">
              Yana {now.length - 6} ta — <Link className="underline" to="/call-center/tasks">barcha vazifalar</Link>
            </p>
          )}
        </>
      )}
      {openId && <LeadDetailModal id={Number(openId)} onClose={() => setSearchParams((p) => (p.delete("open"), p))} />}
    </Card>
  );
}

function Boards() {
  const { data, isLoading } = useGet<{ boards: Board[] }>("/dashboard/boards/");
  const [active, setActive] = useState<string | null>(null);
  if (isLoading || !data) return <PageLoader />;
  const boards = data.boards;
  const board = boards.find((b) => b.id === active) ?? boards[0];
  if (!board) return <Empty title="Mavjud doskalar yo'q" text="Huquq olish uchun administratorga murojaat qiling." />;
  return (
    <>
      {boards.length > 1 && (
        <Segmented
          className="mb-4"
          value={board.id}
          onChange={setActive}
          options={boards.map((b) => ({ value: b.id, label: b.label, count: b.total }))}
        />
      )}
      <KanbanBoard board={board} />
    </>
  );
}

function KanbanBoard({ board }: { board: Board }) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const open = (id: number) =>
    navigate(board.id === "orders" ? `/orders/${id}` : board.id === "meterings" ? `/meterings/${id}` : `/call-center?open=${id}`);

  return (
    <div className="scrollbar-thin -mx-4 flex gap-3 overflow-x-auto px-4 pb-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      {board.columns.map((col) => {
        const collapsed = col.collapsed && !expanded[col.key];
        if (collapsed)
          return (
            <button
              key={col.key}
              onClick={() => setExpanded({ ...expanded, [col.key]: true })}
              className="flex w-12 shrink-0 flex-col items-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-white/50 py-4 dark:border-slate-700 dark:bg-slate-900/40"
            >
              <span className={cn("h-2 w-2 rounded-full", TONES[col.accent].dot)} />
              <span className="text-xs font-semibold tabular-nums">{col.count}</span>
              <span className="text-xs font-medium text-slate-500 [writing-mode:vertical-rl]">{col.title}</span>
            </button>
          );
        return (
          <section key={col.key} className="flex w-[290px] shrink-0 flex-col rounded-2xl bg-slate-100/70 dark:bg-slate-900/60">
            <header className="flex items-center justify-between gap-2 px-3.5 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", TONES[col.accent].dot)} />
                <h3 className="truncate text-sm font-semibold">{col.title}</h3>
              </div>
              <span className="rounded-md bg-white px-1.5 text-xs font-semibold tabular-nums text-slate-600 shadow-sm dark:bg-slate-800 dark:text-slate-300">
                {col.count}
              </span>
            </header>
            <div className="scrollbar-thin flex max-h-[calc(100vh-260px)] flex-col gap-2 overflow-y-auto px-2 pb-2">
              {!col.cards.length && <p className="muted px-2 py-6 text-center text-xs">Bo'sh</p>}
              {col.cards.map((card: any) => (
                <button
                  key={card.id}
                  onClick={() => open(card.id)}
                  className="card group w-full space-y-2 p-3 text-left text-sm transition hover:-translate-y-0.5 hover:shadow-pop"
                >
                  {board.id === "orders" && <OrderCard card={card} />}
                  {board.id === "meterings" && <MeteringCard card={card} />}
                  {board.id === "callcenter" && <InvoiceCard card={card} />}
                </button>
              ))}
              {col.more > 0 && (
                <Link
                  to={LIST_URL[board.id](col.key)}
                  className="flex items-center justify-center gap-1 rounded-xl py-2 text-xs font-medium text-brand-700 hover:bg-white dark:text-brand-300 dark:hover:bg-slate-800"
                >
                  Yana {col.more} <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function OrderCard({ card }: { card: any }) {
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-900 dark:text-white">№{card.number}</span>
        <DeadlinePill deadline={card.deadline} />
      </div>
      <div className="font-medium">{card.client}</div>
      {(card.address || card.map_url) && (
        <div className="text-xs">
          <AddressLink nested address={card.address} mapUrl={card.map_url} lat={card.lat} lon={card.lon} />
        </div>
      )}
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="muted flex items-center gap-1">
          <Factory className="h-3 w-3" /> {card.factory}
        </span>
        {card.left && (
          <span className="flex items-center gap-1">
            <span className="muted">Qoldiq</span>
            <MoneyLeft left={card.left} total={card.total} />
          </span>
        )}
      </div>
    </>
  );
}

function MeteringCard({ card }: { card: any }) {
  return (
    <>
      <div className="font-medium text-slate-900 dark:text-white">{card.client}</div>
      <div className="muted flex items-center gap-1 text-xs">
        <Phone className="h-3 w-3" /> {phone(card.phone)}
      </div>
      {(card.address || card.map_url) && (
        <div className="text-xs">
          <AddressLink nested address={card.address} mapUrl={card.map_url} lat={card.lat} lon={card.lon} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {card.when && (
          <Badge tone="info" dot={false}>
            <Clock className="h-3 w-3" /> {dateTime(card.when)}
          </Badge>
        )}
        {card.has_design && <Check ok={card.design_done} label="Dizayn" />}
        {card.has_price && <Check ok={card.price_done} label="Narx" />}
      </div>
    </>
  );
}

function InvoiceCard({ card }: { card: any }) {
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-900 dark:text-white">{card.client}</span>
        <span className="muted text-xs">#{card.id}</span>
      </div>
      <div className="muted flex items-center gap-1 text-xs">
        <Phone className="h-3 w-3" /> {phone(card.phone)}
      </div>
      {card.desc && <p className="line-clamp-2 text-xs text-slate-600 dark:text-slate-300">{card.desc}</p>}
      <div className="muted text-[11px]">{dateTime(card.when)}</div>
    </>
  );
}
