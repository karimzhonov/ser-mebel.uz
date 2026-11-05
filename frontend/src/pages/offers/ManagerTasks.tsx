import { Link } from "react-router-dom";
import { AlarmClockOff, Calculator, CalendarClock, PackageCheck, Presentation } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { OfferAgenda, Presentations, Price, PresentationRow } from "@/api/types";
import { Card, Empty, PageHeader, PageLoader, StatTile } from "@/components/ui";
import { dateTime, phone } from "@/lib/format";

/** «Vazifalarim» for a manager: the prices the zamerchi gave them to calculate (also sent
 * in the bot) and the clients waiting for them — a design / price to show, an order to make. */
export default function ManagerTasksPage() {
  const { data: prices } = useGet<OfferAgenda<Price>>("/prices/agenda/", { user: "me" });
  const { data: pres } = useGet<Presentations>("/meterings/presentations/", { manager: "me" });
  const toPrice = prices ? [...prices.overdue, ...prices.today, ...prices.work] : [];

  return (
    <div>
      <PageHeader title="Vazifalarim" subtitle="Narx hisoblash va mijozga ko'rsatish — sizga berilgan ishlar" />
      {!prices || !pres ? (
        <PageLoader />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Narx — muddati o'tgan" value={prices.counts.overdue} tone="danger" icon={<AlarmClockOff className="h-5 w-5" />} />
            <StatTile label="Narx hisoblash" value={toPrice.length} tone="warn" icon={<Calculator className="h-5 w-5" />} />
            <StatTile label="Mijozga ko'rsatish" value={pres.counts.review} tone="info" icon={<Presentation className="h-5 w-5" />} />
            <StatTile label="Buyurtma yaratish" value={pres.counts.order_ready} tone="ok" icon={<PackageCheck className="h-5 w-5" />} />
          </div>

          <Card title="Narxini hisoblash kerak" padded={false} actions={<Link className="text-sm underline" to="/prices">Narx hisoblash</Link>}>
            {!toPrice.length && <Empty title="Narx vazifasi yo'q" />}
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {toPrice.map((p) => (
                <li key={p.id}>
                  <Link to={`/prices/${p.id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{p.metering?.client.fio ?? p.desc ?? `#${p.id}`}</span>
                      <span className="muted block truncate text-xs">{p.metering ? phone(p.metering.client.phone) : ""}</span>
                    </span>
                    <span className={`flex items-center gap-1 whitespace-nowrap text-xs font-medium ${p.is_overdue ? "text-rose-600" : "text-brand-700 dark:text-accent-200"}`}>
                      <CalendarClock className="h-3.5 w-3.5" /> {p.due_at ? dateTime(p.due_at) : "muddatsiz"}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>

          <ClientList title="Mijozga ko'rsatish kerak" rows={pres.review} empty="Ko'rsatiladigan dizayn yoki narx yo'q" />
          <ClientList title="Buyurtma yaratish kerak" rows={pres.order_ready} empty="Buyurtma kutayotgan mijoz yo'q" />
        </div>
      )}
    </div>
  );
}

function ClientList({ title, rows, empty }: { title: string; rows: PresentationRow[]; empty: string }) {
  return (
    <Card title={`${title} · ${rows.length}`} padded={false} actions={<Link className="text-sm underline" to="/presentations">Mijozga ko'rsatish</Link>}>
      {!rows.length && <Empty title={empty} />}
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {rows.map((r) => (
          <li key={r.metering.id}>
            <Link to={`/meterings/${r.metering.id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
              <span className="min-w-0">
                <span className="block truncate font-medium">{r.metering.client.fio}</span>
                <span className="muted block truncate text-xs">{phone(r.metering.client.phone)}</span>
              </span>
              <span className={`whitespace-nowrap text-xs font-medium ${r.is_overdue ? "text-rose-600" : "muted"}`}>
                {[r.design && "dizayn", r.price && "narx"].filter(Boolean).join(" + ")}
                {r.is_overdue && " · kechikkan"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
