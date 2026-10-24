import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, Clock, Columns3, Factory, LayoutGrid, MapPin, Phone } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { Board } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { DeadlinePill, MoneyLeft } from "@/components/domain";
import { OverviewPanel } from "@/components/Overview";
import { useUrlState } from "@/lib/useUrlState";
import { Badge, Check, Empty, PageHeader, PageLoader, Segmented, TONES } from "@/components/ui";
import { cn } from "@/lib/cn";
import { dateTime, phone } from "@/lib/format";

const LIST_URL: Record<Board["id"], (col: string) => string> = {
  orders: () => "/orders",
  meterings: () => "/meterings",
  callcenter: () => "/call-center",
};

export default function DashboardPage() {
  const { user } = useAuth();
  const { state, set } = useUrlState({ tab: "overview", date_from: monthStartISO(), date_to: iso(new Date()) });
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Xayrli tong" : hour < 18 ? "Xayrli kun" : "Xayrli kech";

  return (
    <div>
      <PageHeader
        title={`${greet}${user?.name ? ", " + user.name : ""}`}
        subtitle="Ishlab chiqarishning barcha jarayonlari — bitta ekranda"
        actions={
          state.tab === "overview" && (
            <DateRangeFilter
              from={state.date_from}
              to={state.date_to}
              onChange={(date_from, date_to) => set({ date_from, date_to })}
            />
          )
        }
      />
      <Segmented
        className="mb-4"
        value={state.tab}
        onChange={(tab) => set({ tab })}
        options={[
          { value: "overview", label: <span className="flex items-center gap-1.5"><LayoutGrid className="h-4 w-4" /> Umumiy ko'rinish</span> },
          { value: "board", label: <span className="flex items-center gap-1.5"><Columns3 className="h-4 w-4" /> Doska</span> },
        ]}
      />
      {state.tab === "board" ? <Boards /> : <OverviewPanel from={state.date_from} to={state.date_to} />}
    </div>
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
      {card.address && (
        <div className="muted flex items-center gap-1 text-xs">
          <MapPin className="h-3 w-3" /> {card.address}
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
      {card.address && (
        <div className="muted flex items-center gap-1 text-xs">
          <MapPin className="h-3 w-3" /> {card.address}
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
