import { useSearchParams } from "react-router-dom";
import { AlarmClockOff, CalendarClock, CalendarDays, PartyPopper } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { InvoiceTask, TaskAgenda } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Card, Empty, PageHeader, PageLoader, StatTile } from "@/components/ui";
import { useUrlState } from "@/lib/useUrlState";
import { LeadDetailModal } from "./LeadDetailModal";
import { AssigneeSelect, TaskRow, useAssignees } from "./shared";

export default function MyTasksPage() {
  const { user, can } = useAuth();
  const manager = can("call_center.manage_invoice");
  const assignees = useAssignees(manager);
  const { state, set } = useUrlState({ assigned_to: "" });
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");
  const open = (id: number) => setSearchParams((p) => (p.set("open", String(id)), p));

  const { data, isLoading } = useGet<TaskAgenda>("/invoice-tasks/agenda/", { assigned_to: manager ? state.assigned_to : "" });
  const who = state.assigned_to && Number(state.assigned_to) !== user?.id ? assignees.find((a) => String(a.id) === state.assigned_to)?.name : null;

  return (
    <div>
      <PageHeader
        title="Bugungi ishlarim"
        subtitle={who ? `${who} — vazifalar` : "Qo'ng'iroq qilish kerak bo'lgan mijozlar"}
        actions={
          manager &&
          assignees.length > 0 && (
            <AssigneeSelect
              className="w-auto min-w-[220px]"
              value={state.assigned_to ? Number(state.assigned_to) : ""}
              onChange={(id) => set({ assigned_to: id && id !== user?.id ? String(id) : "" })}
              assignees={assignees}
              emptyLabel="Mening vazifalarim"
              allowEmpty
            />
          )
        }
      />
      {isLoading || !data ? (
        <PageLoader />
      ) : (
        <>
          <div className="mb-5 grid grid-cols-3 gap-3">
            <StatTile label="Muddati o'tgan" value={data.overdue.length} tone="danger" icon={<AlarmClockOff className="h-5 w-5" />} />
            <StatTile label="Bugun" value={data.today.length} tone="warn" icon={<CalendarClock className="h-5 w-5" />} />
            <StatTile label="Keyingi" value={data.upcoming.length} tone="info" icon={<CalendarDays className="h-5 w-5" />} />
          </div>
          {!data.overdue.length && !data.today.length && !data.upcoming.length ? (
            <Card>
              <Empty icon={<PartyPopper className="h-6 w-6" />} title="Vazifalar yo'q" text="Hamma qo'ng'iroqlar bajarilgan. Yangi arizalarni Call-center doskasida ko'ring." />
            </Card>
          ) : (
            <div className="space-y-5">
              <Section title="Muddati o'tgan" danger tasks={data.overdue} onOpen={open} />
              <Section title="Bugun" tasks={data.today} onOpen={open} />
              <Section title="Keyingi" tasks={data.upcoming} onOpen={open} />
            </div>
          )}
        </>
      )}
      {openId && <LeadDetailModal id={Number(openId)} onClose={() => setSearchParams((p) => (p.delete("open"), p))} />}
    </div>
  );
}

function Section({ title, tasks, danger, onOpen }: { title: string; tasks: InvoiceTask[]; danger?: boolean; onOpen: (id: number) => void }) {
  if (!tasks.length) return null;
  return (
    <section>
      <h2 className={danger ? "mb-2 text-sm font-semibold text-rose-600 dark:text-rose-400" : "mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200"}>
        {title} · {tasks.length}
      </h2>
      <div className="grid gap-2 lg:grid-cols-2">
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} showClient onOpen={() => onOpen(t.invoice.id)} />
        ))}
      </div>
    </section>
  );
}
