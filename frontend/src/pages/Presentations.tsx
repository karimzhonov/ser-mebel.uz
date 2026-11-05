import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Brush, Calculator, CalendarCheck, FileText, FolderOpen, Package } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { OfferBrief, OfferKind, PresentationRow, Presentations } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, FolderModal, PhoneLink } from "@/components/domain";
import { Button, Card, Empty, PageHeader, PageLoader, SearchInput, Segmented, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { personName } from "./meterings/actions";
import { AnswerButtons, DueLabel, OfferStageBadge, useAssignees } from "./offers/actions";

const PdfViewer = lazy(() => import("@/components/PdfViewer"));

type Tab = "review" | "working" | "order_ready";
const TABS: Tab[] = ["review", "working", "order_ready"];

/** «Mijozga ko'rsatish» — the manager's list: designs / prices ready to show to the client
 * (answer right here: Tasdiqladi / O'zgartirish / Rad etdi, Rozi / Qayta hisoblash / Qoniqtirmadi),
 * what is still in work, and the clients who agreed and need an order. `?open=d12` / `?open=p5`
 * (the bot's «Saytda ochish») jumps to that row. */
export default function PresentationsPage() {
  const { can } = useAuth();
  const boss = can("metering.manage_metering");
  const { state, set } = useUrlState({ tab: "review", manager: "", search: "", open: "" });
  const tab: Tab = (TABS as string[]).includes(state.tab) ? (state.tab as Tab) : "review";
  const people = useAssignees(boss);
  const { data, isLoading } = useGet<Presentations>("/meterings/presentations/", { manager: boss ? state.manager : "", search: state.search });
  const c = data?.counts;

  // ?open=d12 → the tab that holds it, then scroll to the row
  const target = parseOpen(state.open);
  const [focused, setFocused] = useState<string | null>(null);
  useEffect(() => {
    if (!data || !target) return;
    const where = TABS.find((t) => data[t].some((r) => matches(r, target)));
    if (where && where !== tab) {
      set({ tab: where, open: state.open });
      return;
    }
    const key = target.kind + target.id;
    setFocused(key);
    setTimeout(() => document.getElementById(`pres-${key}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
  }, [data, state.open, tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = data?.[tab] ?? [];
  return (
    <div>
      <PageHeader title="Mijozga ko'rsatish" subtitle="Dizayn va narxni mijozga ko'rsating, javobini belgilang" />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <Segmented
          value={tab}
          onChange={(v) => set({ tab: v, open: "" })}
          options={[
            {
              value: "review",
              label: <span className={cn(data?.review?.some((r) => r.is_overdue) ? "text-rose-600 dark:text-rose-400" : "")}>Javob kutilmoqda</span>,
              count: c?.review,
            },
            { value: "working", label: "Ishda", count: c?.working },
            { value: "order_ready", label: "Buyurtmaga tayyor", count: c?.order_ready },
          ]}
        />
        <div className="flex flex-1 flex-col gap-2 sm:flex-row lg:justify-end">
          <SearchInput className="sm:max-w-xs sm:flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="Mijoz, telefon, manzil" />
          {boss && (
            <Select className="sm:w-auto sm:min-w-[200px]" value={state.manager} onChange={(e) => set({ manager: e.target.value })}>
              <option value="">Barcha menejerlar</option>
              <option value="me">Mening mijozlarim</option>
              {people.data?.managers?.map((u) => (
                <option key={u.id} value={u.id}>{personName(u)}</option>
              ))}
            </Select>
          )}
        </div>
      </div>

      {isLoading || !data ? (
        <PageLoader />
      ) : (
        <Card padded={false}>
          {rows.length ? (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((r) => (
                <PresentationItem key={r.metering.id} row={r} tab={tab} focused={focused} />
              ))}
            </ul>
          ) : (
            <Empty
              icon={<CalendarCheck className="h-6 w-6" />}
              title={tab === "review" ? "Ko'rsatadigan narsa yo'q" : tab === "working" ? "Ishda hech narsa yo'q" : "Buyurtmaga tayyor mijoz yo'q"}
              text={tab === "review" ? "Dizayn yoki narx tayyor bo'lganda shu yerda va Telegramda paydo bo'ladi." : undefined}
            />
          )}
        </Card>
      )}
    </div>
  );
}

function parseOpen(v: string): { kind: "d" | "p"; id: number } | null {
  const m = /^([dp])(\d+)$/.exec(v || "");
  return m ? { kind: m[1] as "d" | "p", id: Number(m[2]) } : null;
}

function matches(r: PresentationRow, t: { kind: "d" | "p"; id: number }) {
  return t.kind === "d" ? r.design?.id === t.id : r.price?.id === t.id;
}

function PresentationItem({ row: r, tab, focused }: { row: PresentationRow; tab: Tab; focused: string | null }) {
  const { can } = useAuth();
  const m = r.metering;
  const isFocused = (!!r.design && focused === `d${r.design.id}`) || (!!r.price && focused === `p${r.price.id}`);
  const anchor = r.design ? `d${r.design.id}` : r.price ? `p${r.price.id}` : `m${m.id}`;
  return (
    <li
      id={`pres-${anchor}`}
      className={cn(
        "scroll-mt-24 px-4 py-4 sm:px-5",
        r.is_overdue && "bg-rose-50/40 dark:bg-rose-500/[.04]",
        isFocused && "ring-2 ring-inset ring-brand-500",
      )}
    >
      {/* the price anchor too, when both exist */}
      {r.design && r.price && <span id={`pres-p${r.price.id}`} className="block scroll-mt-24" />}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <Link to={`/meterings/${m.id}`} className="text-base font-semibold text-slate-900 hover:underline dark:text-white">
            {m.client.fio}
          </Link>
          <div className="text-sm">
            <PhoneLink value={m.client.phone} />
          </div>
          <div className="text-sm">
            <AddressLink address={m.address} link={m.address_link} mapUrl={m.map_url} lat={m.lat} lon={m.lon} empty="Manzil yo'q" />
          </div>
        </div>
        {r.manager && <span className="muted text-xs">Menejer: {personName(r.manager)}</span>}
      </div>

      <div className="mt-3 space-y-3">
        {r.design && <OfferLine kind="design" offer={r.design} client={m.client.fio} />}
        {r.price && <OfferLine kind="price" offer={r.price} client={m.client.fio} />}
        {tab === "working" && r.waiting_for && (
          <p className="muted text-xs">{r.waiting_for === "design" ? "Dizayn tayyorlanmoqda" : "Narx hisoblanmoqda"} — tayyor bo'lsa xabar keladi.</p>
        )}
        {tab === "order_ready" && can("order.add_order") && (
          <Link
            to={`/orders/new?metering=${m.id}${r.design ? `&design=${r.design.id}` : ""}`}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-brand-700 px-5 text-base font-semibold text-white transition hover:bg-brand-800 sm:w-auto sm:inline-flex"
          >
            <Package className="h-5 w-5" /> Buyurtma yaratish
          </Link>
        )}
      </div>
    </li>
  );
}

/** one design / price of the client: stage, who, deadline, files / PDF, and the answer buttons when it's at the client */
function OfferLine({ kind, offer: o, client }: { kind: OfferKind; offer: OfferBrief; client: string }) {
  const [folder, setFolder] = useState<number | null>(null);
  const [pdf, setPdf] = useState(false);
  const Icon = kind === "design" ? Brush : Calculator;
  const review = o.stage === "review";
  const pdfName = `Taklif — ${client}.pdf`;
  let files: ReactNode = null;
  if (kind === "design" && o.types?.length)
    files = o.types
      .filter((t) => t.folder)
      .map((t) => (
        <Button key={t.id} size={review ? "lg" : "sm"} variant="outline" icon={<FolderOpen className="h-4 w-4" />} onClick={() => setFolder(t.folder)}>
          {t.name}
        </Button>
      ));
  else if (kind === "design")
    files = (
      <Link to={`/designs/${o.id}`} className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">
        Dizaynni ochish →
      </Link>
    );
  else if (o.stage === "review" || o.stage === "approved")
    files = (
      <Button size={review ? "lg" : "sm"} variant="outline" icon={<FileText className="h-4 w-4" />} onClick={() => setPdf(true)}>
        Taklif (PDF)
      </Button>
    );

  return (
    <div className={cn("rounded-2xl border p-3", review ? "border-brand-200 bg-brand-50/30 dark:border-brand-500/30 dark:bg-brand-500/5" : "border-slate-200 dark:border-slate-700")}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Icon className="h-4 w-4 text-brand-600" />
        <Link to={`/${kind === "design" ? "designs" : "prices"}/${o.id}`} className="font-semibold hover:underline">
          {kind === "design" ? "Dizayn" : "Narx"}
        </Link>
        <OfferStageBadge stage={o.stage} label={o.stage_label} overdue={o.is_overdue} />
        {o.round > 1 && <span className="muted text-xs">{o.round}-raund</span>}
        {kind === "price" && o.price && <span className="font-semibold tabular-nums">{money(o.price)}</span>}
        <span className="muted ml-auto text-xs">{personName(o.user, "tayinlanmagan")}</span>
      </div>
      {o.stage === "work" && (
        <div className="mt-1 text-sm">
          Muddat: <DueLabel value={o.due_at} overdue={o.is_overdue} />
        </div>
      )}
      {o.last_comment && o.round > 1 && <div className="muted mt-1 line-clamp-2 text-xs">✏️ {o.last_comment}</div>}
      {files && <div className="mt-2 flex flex-wrap gap-2">{files}</div>}
      {review && <AnswerButtons big className="mt-3" kind={kind} id={o.id} client={client} />}
      {folder && <FolderModal folderId={folder} onClose={() => setFolder(null)} />}
      {pdf && (
        <Suspense fallback={null}>
          <PdfViewer url={`/prices/${o.id}/pdf/`} name={pdfName} downloadName={pdfName} onClose={() => setPdf(false)} />
        </Suspense>
      )}
    </div>
  );
}
