import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, PhoneCall, Ruler } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList, useMeta } from "@/api/hooks";
import type { Invoice, StatusStats } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PhoneLink, SolutionBadge, TimelineChart } from "@/components/domain";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import {
  Button,
  Card,
  Chip,
  DataTable,
  Field,
  Input,
  KV,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Textarea,
  TONES,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { dateTime, relative } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { MeteringCreateModal } from "./Meterings";

export default function CallCenterPage() {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { state, page, set } = useUrlState({ search: "", solution: "", date_from: "", date_to: "" });
  const [creating, setCreating] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");

  const params = { search: state.search, solution: state.solution, date_from: state.date_from, date_to: state.date_to, page };
  const { data, isFetching } = useList<Invoice>("invoices", params);
  const { data: stats } = useGet<StatusStats>("/invoices/stats/", { search: state.search, date_from: state.date_from, date_to: state.date_to });

  const counts = Object.fromEntries((stats?.by_solution ?? []).map((s) => [s.key, s.count]));
  const selected = state.solution.split(",").filter(Boolean);
  const toggle = (key: string) =>
    set({ solution: (selected.includes(key) ? selected.filter((s) => s !== key) : [...selected, key]).join(",") });

  return (
    <div>
      <PageHeader
        title="Call-center"
        subtitle="Заявки клиентов и результаты звонков"
        actions={
          can("call_center.add_invoice") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Новая заявка
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <Chip active={!selected.length} onClick={() => set({ solution: "" })}>
          Все · {stats?.total ?? "…"}
        </Chip>
        <Chip tone="primary" active={selected.includes("new")} onClick={() => toggle("new")}>
          Янги · {counts.new ?? 0}
        </Chip>
        {meta?.solutions.map((s) => (
          <Chip key={s.value} tone={s.tone} active={selected.includes(String(s.value))} onClick={() => toggle(String(s.value))}>
            {s.label} · {counts[String(s.value)] ?? 0}
          </Chip>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card padded={false}>
          <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row dark:border-slate-800">
            <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="ФИО, телефон, описание" />
            <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
          </div>
          <DataTable
            rows={data?.results}
            loading={isFetching}
            rowKey={(r) => r.id}
            onRowClick={(r) => setSearchParams((p) => (p.set("open", String(r.id)), p))}
            columns={[
              { key: "id", header: "#", cell: (r) => <span className="muted">{r.id}</span> },
              { key: "client", header: "Клиент", cell: (r) => <span className="font-medium">{r.client.fio}</span> },
              { key: "phone", header: "Телефон", cell: (r) => <PhoneLink value={r.client.phone} /> },
              { key: "desc", header: "Описание", cell: (r) => <span className="line-clamp-1 max-w-xs">{r.desc || "—"}</span>, hideOnMobile: true },
              { key: "solution", header: "Код ответа", cell: (r) => <SolutionBadge solution={r.solution} label={r.solution_label} /> },
              { key: "date", header: "Создана", cell: (r) => <span className="muted whitespace-nowrap">{relative(r.create_date)}</span> },
            ]}
            mobileCard={(r) => (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{r.client.fio}</span>
                  <SolutionBadge solution={r.solution} label={r.solution_label} />
                </div>
                <div className="flex items-center justify-between text-sm">
                  <PhoneLink value={r.client.phone} />
                  <span className="muted text-xs">{relative(r.create_date)}</span>
                </div>
                {r.desc && <p className="muted line-clamp-2 text-sm">{r.desc}</p>}
              </div>
            )}
          />
          <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
        </Card>
        <Card title="Заявки по дням">
          <TimelineChart data={stats?.timeline} />
        </Card>
      </div>

      {creating && <InvoiceCreateModal onClose={() => setCreating(false)} />}
      {openId && (
        <InvoiceModal id={Number(openId)} onClose={() => setSearchParams((p) => (p.delete("open"), p))} />
      )}
    </div>
  );
}

function InvoiceCreateModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ fio: "", phone: "+998", desc: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useAction(() => api.post("/invoices/", form), {
    success: "Заявка создана",
    invalidate: ["invoices", "dashboard"],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Новая заявка"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button
            loading={create.isPending}
            onClick={() => create.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}
          >
            Сохранить
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Телефон клиента" error={errors.phone}>
          <Input inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        <Field label="ФИО клиента" error={errors.fio} hint="Если клиент уже есть в базе — будет использован существующий.">
          <Input value={form.fio} onChange={(e) => setForm({ ...form, fio: e.target.value })} />
        </Field>
        <Field label="Описание" error={errors.desc}>
          <Textarea value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

function InvoiceModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { can } = useAuth();
  const { data: meta } = useMeta();
  const { data: invoice } = useGet<Invoice>(`/invoices/${id}/`);
  const [desc, setDesc] = useState("");
  const [metering, setMetering] = useState(false);
  useEffect(() => setDesc(invoice?.desc ?? ""), [invoice?.desc]);

  const setSolution = useAction(
    (solution: number) => api.post(`/invoices/${id}/solution/`, { solution }),
    { success: "Код ответа сохранён", invalidate: ["invoices", "dashboard"] },
  );
  const save = useAction(() => api.patch(`/invoices/${id}/`, { desc }), {
    success: "Сохранено",
    invalidate: ["invoices"],
  });

  if (!invoice) return null;
  const served = invoice.solution === 5 || invoice.solution === 6; // go_for_measured / sold_out
  const canChange = can("call_center.change_invoice");

  return (
    <Modal open onClose={onClose} title={`Заявка #${invoice.id}`} size="lg">
      <div className="space-y-5">
        <KV
          items={[
            ["Клиент", <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${encodeURIComponent(invoice.client.phone)}`}>{invoice.client.fio}</Link>],
            ["Телефон", <PhoneLink value={invoice.client.phone} />],
            ["Создана", dateTime(invoice.create_date)],
            ["Изменена", dateTime(invoice.update_date)],
            ["Код ответа", <SolutionBadge solution={invoice.solution} label={invoice.solution_label} />],
            ...(invoice.metering_id
              ? ([["Замер", <Link className="text-brand-700 hover:underline" to={`/meterings/${invoice.metering_id}`}>Открыть замер →</Link>]] as [string, JSX.Element][])
              : []),
          ]}
        />
        <Field label="Описание">
          <Textarea value={desc} disabled={!invoice.is_editable || !canChange} onChange={(e) => setDesc(e.target.value)} />
        </Field>
        {invoice.is_editable && canChange && desc !== (invoice.desc ?? "") && (
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Сохранить описание</Button>
        )}

        {canChange && !served && (
          <div>
            <div className="label">Результат звонка</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {meta?.solutions
                .filter((s) => s.value !== 6)
                .map((s) =>
                  s.value === 5 ? (
                    can("metering.add_metering") && (
                      <button
                        key={s.value}
                        onClick={() => setMetering(true)}
                        className={cn("flex items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-medium ring-1 ring-inset transition hover:brightness-95", TONES.ok.badge)}
                      >
                        <Ruler className="h-4 w-4" /> {s.label} → создать замер
                      </button>
                    )
                  ) : (
                    <button
                      key={s.value}
                      disabled={setSolution.isPending}
                      onClick={() => setSolution.mutate(Number(s.value))}
                      className={cn(
                        "flex items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-medium ring-1 ring-inset transition hover:brightness-95",
                        TONES[s.tone].badge,
                        invoice.solution === s.value && "ring-2",
                      )}
                    >
                      <PhoneCall className="h-4 w-4" /> {s.label}
                    </button>
                  ),
                )}
            </div>
          </div>
        )}
      </div>
      {metering && (
        <MeteringCreateModal
          initial={{ client_phone: invoice.client.phone, client_fio: invoice.client.fio, invoice: invoice.id }}
          onClose={() => setMetering(false)}
          onCreated={onClose}
        />
      )}
    </Modal>
  );
}
