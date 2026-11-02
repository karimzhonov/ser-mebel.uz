import { useGet, useList, useMeta } from "@/api/hooks";
import type { Invoice, StatusStats } from "@/api/types";
import { PhoneLink, SolutionBadge, TimelineChart } from "@/components/domain";
import { Card, Chip, DataTable, Pagination } from "@/components/ui";
import { relative } from "@/lib/format";
import { DueText, NoTaskBadge, SourceBadge } from "./shared";

function NextTask({ r }: { r: Invoice }) {
  if (r.next_task)
    return (
      <span className="flex min-w-0 flex-col" title={r.next_task.text}>
        <DueText due={r.next_task.due_at} className="text-xs" />
        <span className="muted line-clamp-1 max-w-[180px] text-xs">{r.next_task.text}</span>
      </span>
    );
  return r.needs_task ? <NoTaskBadge /> : <span className="muted">—</span>;
}

export function LeadList({
  filters,
  solution,
  page,
  set,
  onOpen,
}: {
  filters: Record<string, string>;
  solution: string;
  page: number;
  set: (patch: Record<string, string | number | undefined>) => void;
  onOpen: (id: number) => void;
}) {
  const { data: meta } = useMeta();
  const params = { ...filters, solution, page };
  const { data, isFetching } = useList<Invoice>("invoices", params);
  const { data: stats } = useGet<StatusStats>("/invoices/stats/", filters);

  const counts = Object.fromEntries((stats?.by_solution ?? []).map((s) => [s.key, s.count]));
  const selected = solution.split(",").filter(Boolean);
  const toggle = (key: string) =>
    set({ solution: (selected.includes(key) ? selected.filter((s) => s !== key) : [...selected, key]).join(",") });

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2">
        <Chip active={!selected.length} onClick={() => set({ solution: "" })}>
          Barchasi · {stats?.total ?? "…"}
        </Chip>
        <Chip tone="primary" active={selected.includes("new")} onClick={() => toggle("new")}>
          Yangi · {counts.new ?? 0}
        </Chip>
        {meta?.solutions.map((s) => (
          <Chip key={s.value} tone={s.tone} active={selected.includes(String(s.value))} onClick={() => toggle(String(s.value))}>
            {s.label} · {counts[String(s.value)] ?? 0}
          </Chip>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card padded={false}>
          <DataTable
            rows={data?.results}
            loading={isFetching}
            rowKey={(r) => r.id}
            onRowClick={(r) => onOpen(r.id)}
            rowClassName={(r) => (r.next_task && new Date(r.next_task.due_at).getTime() < Date.now() ? "bg-rose-50/40 dark:bg-rose-500/5" : undefined)}
            columns={[
              { key: "id", header: "#", cell: (r) => <span className="muted">{r.id}</span> },
              {
                key: "client",
                header: "Mijoz",
                cell: (r) => (
                  <div className="min-w-0">
                    <div className="font-medium">{r.client.fio}</div>
                    {r.desc && <div className="muted line-clamp-1 max-w-xs text-xs">{r.desc}</div>}
                  </div>
                ),
              },
              { key: "phone", header: "Telefon", cell: (r) => <span onClick={(e) => e.stopPropagation()}><PhoneLink value={r.client.phone} /></span> },
              { key: "source", header: "Manba", cell: (r) => <SourceBadge label={r.source_label} />, hideOnMobile: true },
              { key: "solution", header: "Javob kodi", cell: (r) => <SolutionBadge solution={r.solution} label={r.solution_label} /> },
              { key: "assigned", header: "Mas'ul", cell: (r) => <span className="whitespace-nowrap">{r.assigned_to?.name ?? "—"}</span>, hideOnMobile: true },
              { key: "next", header: "Keyingi vazifa", cell: (r) => <NextTask r={r} /> },
              { key: "date", header: "Yaratilgan", cell: (r) => <span className="muted whitespace-nowrap">{relative(r.create_date)}</span>, hideOnMobile: true },
            ]}
            mobileCard={(r) => (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{r.client.fio}</span>
                  <SolutionBadge solution={r.solution} label={r.solution_label} />
                </div>
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span onClick={(e) => e.stopPropagation()}>
                    <PhoneLink value={r.client.phone} />
                  </span>
                  <SourceBadge label={r.source_label} />
                </div>
                <div className="flex items-center justify-between gap-2 text-xs">
                  <NextTask r={r} />
                  <span className="muted">{r.assigned_to?.name ?? relative(r.create_date)}</span>
                </div>
                {r.desc && <p className="muted line-clamp-2 text-sm">{r.desc}</p>}
              </div>
            )}
          />
          <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
        <Card title="Kunlar bo'yicha arizalar">
          <TimelineChart data={stats?.timeline} />
        </Card>
      </div>
    </>
  );
}
