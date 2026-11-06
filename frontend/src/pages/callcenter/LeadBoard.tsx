import { useEffect, useState, type DragEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "@/api/client";
import { cleanParams, useGet, useMeta } from "@/api/hooks";
import type { Invoice, LeadBoard as LeadBoardData, LeadBoardColumn } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { MeteringCreateModal } from "../Meterings";
import { SolutionCommentModal } from "./SolutionCommentModal";
import { AddressLink, PhoneLink } from "@/components/domain";
import { Empty, PageLoader, TONES } from "@/components/ui";
import { cn } from "@/lib/cn";
import { CRM_INVALIDATE, DueText, GO_FOR_MEASURED, NoTaskBadge, SOLD_OUT, SourceBadge } from "./shared";

const BOARD_PATH = "/invoices/board/";

/** Phones and tablets have no drag-and-drop worth the name: they get a select instead. */
function useCoarsePointer() {
  const query = "(pointer: coarse)";
  const [coarse, setCoarse] = useState(() => typeof window !== "undefined" && window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setCoarse(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return coarse;
}

function colSolution(col: LeadBoardColumn): number | null {
  return col.solution ?? null;
}

export function LeadBoard({ filters, onOpen }: { filters: Record<string, string>; onOpen: (id: number) => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { data: meta } = useMeta();
  const coarse = useCoarsePointer();
  const { data, isLoading } = useGet<LeadBoardData>(BOARD_PATH, filters);
  const queryKey = [BOARD_PATH, cleanParams(filters)];
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [dragging, setDragging] = useState<{ id: number; from: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [metering, setMetering] = useState<Invoice | null>(null);
  // a drop waits for its comment before it is saved
  const [pending, setPending] = useState<{ card: Invoice; to: LeadBoardColumn; solution: number; label: string } | null>(null);

  const canChange = can("call_center.change_invoice");
  const canMeter = can("metering.add_metering");

  if (isLoading || !data) return <PageLoader />;
  if (!data.columns.length) return <Empty title="Arizalar yo'q" />;

  const draggable = (card: Invoice) =>
    canChange && card.solution !== GO_FOR_MEASURED && card.solution !== SOLD_OUT;
  const accepts = (col: LeadBoardColumn) =>
    col.droppable && colSolution(col) !== null && colSolution(col) !== SOLD_OUT && (colSolution(col) !== GO_FOR_MEASURED || canMeter);
  /** where a card may go: every droppable column except the one it is in */
  const targets = (card: Invoice) => data.columns.filter((c) => accepts(c) && colSolution(c) !== card.solution);

  async function move(card: Invoice, to: LeadBoardColumn) {
    const solution = colSolution(to);
    if (solution === null || solution === card.solution || !accepts(to)) return;
    if (solution === GO_FOR_MEASURED) {
      // the zamer flow stays as it was: the solution is set by creating the metering
      setMetering(card);
      return;
    }
    const label = meta?.solutions.find((s) => s.value === solution)?.label ?? to.title;
    setPending({ card, to, solution, label });
  }

  async function save(card: Invoice, to: LeadBoardColumn, solution: number, label: string, comment: string) {
    setPending(null);
    // stop an in-flight board refetch from overwriting the optimistic move
    await qc.cancelQueries({ queryKey });
    const previous = qc.getQueryData<LeadBoardData>(queryKey);
    if (previous)
      qc.setQueryData<LeadBoardData>(queryKey, {
        ...previous,
        columns: previous.columns.map((c) => {
          const has = c.cards.some((x) => x.id === card.id);
          if (c.key === to.key)
            return { ...c, count: c.count + 1, cards: [{ ...card, solution, solution_label: label }, ...c.cards] };
          if (has) return { ...c, count: Math.max(c.count - 1, 0), cards: c.cards.filter((x) => x.id !== card.id) };
          return c;
        }),
      });
    try {
      await api.post(`/invoices/${card.id}/solution/`, { solution, comment });
      toast.success(`#${card.id} → ${label}`);
    } catch (e) {
      // don't restore a snapshot (it may be stale by now) — the refetch below brings the real board back
      toast.error(errorMessage(e));
    } finally {
      CRM_INVALIDATE.forEach((key) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes(key) }));
    }
  }

  const findCard = (id: number) => data.columns.flatMap((c) => c.cards).find((c) => c.id === id);

  const dropProps = (col: LeadBoardColumn) => {
    const ok = !!dragging && accepts(col) && col.key !== dragging.from;
    return {
      onDragOver: (e: DragEvent) => {
        if (!ok) return; // no preventDefault → the browser shows "not allowed"
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (over !== col.key) setOver(col.key);
      },
      onDragLeave: (e: DragEvent) => {
        if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) setOver((o) => (o === col.key ? null : o));
      },
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        setOver(null);
        const id = Number(e.dataTransfer.getData("text/plain")) || dragging?.id;
        setDragging(null);
        const card = id ? findCard(id) : undefined;
        if (ok && card) void move(card, col);
      },
      ok,
    };
  };

  return (
    <>
      {canChange && !coarse && (
        <p className="muted mb-2 text-xs">Kartani boshqa ustunga sudrab o'tkazing — javob kodi o'zgaradi.</p>
      )}
      <div className="scrollbar-thin -mx-4 flex gap-3 overflow-x-auto px-4 pb-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        {data.columns.map((col) => {
          const tone = TONES[col.tone] ? col.tone : "idle";
          const { ok: canDrop, ...drop } = dropProps(col);
          const collapsed = col.collapsed && !expanded[col.key];
          const highlight = canDrop && over === col.key;
          if (collapsed)
            return (
              <button
                key={col.key}
                {...drop}
                onClick={() => setExpanded({ ...expanded, [col.key]: true })}
                className={cn(
                  "flex w-12 shrink-0 flex-col items-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-white/50 py-4 transition dark:border-slate-700 dark:bg-slate-900/40",
                  canDrop && "border-brand-400",
                  highlight && "bg-brand-50 ring-2 ring-brand-500 dark:bg-brand-500/10",
                )}
              >
                <span className={cn("h-2 w-2 rounded-full", TONES[tone].dot)} />
                <span className="text-xs font-semibold tabular-nums">{col.count}</span>
                <span className="text-xs font-medium text-slate-500 [writing-mode:vertical-rl]">{col.title}</span>
              </button>
            );
          return (
            <section
              key={col.key}
              {...drop}
              className={cn(
                "flex w-[290px] shrink-0 flex-col rounded-2xl bg-slate-100/70 transition dark:bg-slate-900/60",
                dragging && !canDrop && col.key !== dragging.from && "opacity-50",
                canDrop && "ring-1 ring-brand-300",
                highlight && "bg-brand-50 ring-2 ring-brand-500 dark:bg-brand-500/10",
              )}
            >
              <header className="flex items-center justify-between gap-2 px-3.5 py-3">
                <button
                  className="flex min-w-0 items-center gap-2 text-left"
                  onClick={() => col.collapsed && setExpanded({ ...expanded, [col.key]: false })}
                  title={col.collapsed ? "Yig'ish" : undefined}
                >
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", TONES[tone].dot)} />
                  <h3 className="truncate text-sm font-semibold">{col.title}</h3>
                </button>
                <span className="rounded-md bg-white px-1.5 text-xs font-semibold tabular-nums text-slate-600 shadow-sm dark:bg-slate-800 dark:text-slate-300">
                  {col.count}
                </span>
              </header>
              <div className="scrollbar-thin flex max-h-[calc(100vh-300px)] min-h-[80px] flex-col gap-2 overflow-y-auto px-2 pb-2">
                {!col.cards.length && <p className="muted px-2 py-6 text-center text-xs">Bo'sh</p>}
                {col.cards.map((card) => (
                  <LeadCard
                    key={card.id}
                    card={card}
                    draggable={draggable(card) && !coarse}
                    dragging={dragging?.id === card.id}
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", String(card.id));
                      e.dataTransfer.effectAllowed = "move";
                      setDragging({ id: card.id, from: col.key });
                    }}
                    onDragEnd={() => {
                      setDragging(null);
                      setOver(null);
                    }}
                    moveOptions={draggable(card) && coarse ? targets(card) : []}
                    onMove={(to) => void move(card, to)}
                    onOpen={() => onOpen(card.id)}
                  />
                ))}
                {col.count > col.cards.length && (
                  <p className="muted py-2 text-center text-xs">
                    Yana {col.count - col.cards.length} ta — «Ro'yxat» ko'rinishida yoki qidiruv bilan toping
                  </p>
                )}
              </div>
            </section>
          );
        })}
      </div>

      {pending && (
        <SolutionCommentModal
          label={pending.label}
          onSubmit={(comment) => save(pending.card, pending.to, pending.solution, pending.label, comment)}
          onClose={() => setPending(null)}
        />
      )}
      {metering && (
        <MeteringCreateModal
          initial={{ client_phone: metering.client.phone, client_fio: metering.client.fio, invoice: metering.id }}
          onClose={() => setMetering(null)}
        />
      )}
    </>
  );
}

function LeadCard({
  card,
  draggable,
  dragging,
  onDragStart,
  onDragEnd,
  moveOptions,
  onMove,
  onOpen,
}: {
  card: Invoice;
  draggable: boolean;
  dragging: boolean;
  onDragStart: (e: DragEvent) => void;
  onDragEnd: () => void;
  moveOptions: LeadBoardColumn[];
  onMove: (to: LeadBoardColumn) => void;
  onOpen: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      className={cn(
        "card group w-full space-y-1.5 p-3 text-left text-sm transition hover:shadow-pop",
        draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
        dragging && "opacity-40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate font-medium">{card.client.fio}</span>
        <span className="muted shrink-0 text-xs">#{card.id}</span>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs" onClick={(e) => e.stopPropagation()}>
        <PhoneLink value={card.client.phone} />
        <SourceBadge label={card.source_label} />
      </div>
      {card.desc && <p className="muted line-clamp-2 text-xs">{card.desc}</p>}
      {(card.address || card.map_url) && (
        <div className="text-xs">
          <AddressLink nested address={card.address} link={card.address_link} mapUrl={card.map_url} lat={card.lat} lon={card.lon} />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs">
        {card.next_task ? (
          <span className="flex min-w-0 items-center gap-1.5" title={card.next_task.text}>
            <DueText due={card.next_task.due_at} />
          </span>
        ) : card.needs_task ? (
          <NoTaskBadge />
        ) : (
          <span />
        )}
        {card.assigned_to && <span className="muted truncate">{card.assigned_to.name}</span>}
      </div>
      {moveOptions.length > 0 && (
        <select
          aria-label="Ko'chirish"
          className="input mt-1 h-8 py-0 text-xs"
          value=""
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            const to = moveOptions.find((c) => c.key === e.target.value);
            if (to) onMove(to);
          }}
        >
          <option value="">Ko'chirish…</option>
          {moveOptions.map((c) => (
            <option key={c.key} value={c.key}>
              {c.title}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
