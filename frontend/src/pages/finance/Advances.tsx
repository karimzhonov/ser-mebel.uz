import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import { Badge, Button, Card, DataTable, Empty, Field, Input, Modal, PageHeader, Segmented } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

/** GET /finance/advances/ — accounting.dto.advance_dto */
interface Advance {
  id: number;
  order_ref: string;
  order_id: number;
  client: string;
  phone: string;
  price_text: string;
  amount: string;
  currency: string;
  sum_text: string;
  by_name: string;
  status: "pending" | "accepted" | "rejected";
  status_label: string;
  got_text: string;
  created_at: string | null;
}

const TONE = { pending: "warn", accepted: "ok", rejected: "danger" } as const;

/** «Avans tasdiqlash»: the advance a manager entered when creating an order counts only
 * once the boss confirms he got the money (the same buttons come to him in Telegram). */
export function FinanceAdvancesPage() {
  const { state, set } = useUrlState({ status: "pending" });
  const { data, isFetching } = useGet<Advance[]>("/finance/advances/", state);
  const [other, setOther] = useState<Advance | null>(null);
  const act = useAction(
    (v: { advance: number; action: "accept" | "reject"; amount_text?: string }) => api.post("/finance/advances/", v),
    { success: "Saqlandi", invalidate: ["finance", "orders"] },
  );
  return (
    <div>
      <PageHeader
        title="Avans tasdiqlash"
        subtitle="Buyurtma yaratilganda kiritilgan avans — pulni qo'lingizga olganingizda tasdiqlang, kassangizga yoziladi"
      />
      <Card padded={false}>
        <div className="border-b border-slate-100 p-4 dark:border-slate-800">
          <Segmented
            value={state.status}
            onChange={(status) => set({ status })}
            options={[
              { value: "pending", label: "⏳ Kutilmoqda" },
              { value: "accepted", label: "✅ Qabul qilingan" },
              { value: "rejected", label: "❌ Kelmagan" },
              { value: "all", label: "Hammasi" },
            ]}
          />
        </div>
        <DataTable
          rows={data}
          loading={isFetching}
          rowKey={(r) => r.id}
          empty={<Empty title="Tasdiq kutayotgan avans yo'q" />}
          columns={[
            {
              key: "o",
              header: "Buyurtma",
              cell: (r) => (
                <Link to={`/orders/${r.order_id}`} className="hover:underline">
                  <b>№{r.order_ref}</b> · {r.client}
                </Link>
              ),
            },
            { key: "p", header: "Narxi", cell: (r) => r.price_text || "—", hideOnMobile: true },
            { key: "a", header: "Avans", cell: (r) => <span className="font-semibold tabular-nums">{r.sum_text}</span> },
            { key: "b", header: "Kim yaratdi", cell: (r) => r.by_name || "—", hideOnMobile: true },
            { key: "d", header: "Qachon", cell: (r) => dateTime(r.created_at), hideOnMobile: true },
            {
              key: "s",
              header: "Holat",
              cell: (r) => (
                <Badge tone={TONE[r.status]}>
                  {r.status_label}
                  {r.got_text ? ` · ${r.got_text}` : ""}
                </Badge>
              ),
            },
            {
              key: "x",
              header: "",
              cell: (r) =>
                r.status === "pending" ? (
                  <div className="flex justify-end gap-2">
                    <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ advance: r.id, action: "accept" })}>
                      ✅ Qabul qildim
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setOther(r)}>
                      ✏️ Boshqa summa
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-rose-600"
                      onClick={() => confirm(`№${r.order_ref}: avans kelmadi deb belgilansinmi?`) && act.mutate({ advance: r.id, action: "reject" })}
                    >
                      ❌ Kelmadi
                    </Button>
                  </div>
                ) : null,
            },
          ]}
        />
      </Card>
      {other && <OtherAmountModal adv={other} onClose={() => setOther(null)} />}
    </div>
  );
}

function OtherAmountModal({ adv, onClose }: { adv: Advance; onClose: () => void }) {
  const [text, setText] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(() => api.post("/finance/advances/", { advance: adv.id, action: "accept", amount_text: text }), {
    success: "Avans qabul qilindi",
    invalidate: ["finance", "orders"],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`№${adv.order_ref} — boshqa summa`}
      size="sm"
      footer={
        <Button disabled={!text.trim()} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Qabul qildim
        </Button>
      }
    >
      <p className="muted mb-3 text-sm">Menejer kiritgan: <b>{adv.sum_text}</b>. Qancha oldingiz?</p>
      <Field label="Summa" hint="Masalan: 4500000, 4.5 mln yoki 450$" error={errors.amount_text}>
        <Input autoFocus value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
    </Modal>
  );
}
