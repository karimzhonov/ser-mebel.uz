import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, UserPlus } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { MeteringAssignees, Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { OfferAgenda } from "./offers/OfferAgenda";

/** «Narx hisoblash» — the pricer's agenda (deadline first, overdue in red) + a price without a zamer. */
export function PricesPage() {
  const navigate = useNavigate();
  const { can, user } = useAuth();
  const boss = !!user?.is_superuser || can("metering.manage_metering");
  const { data: free } = useGet<{ unassigned: number }>(boss ? "/prices/assign/" : null);
  const [giving, setGiving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [desc, setDesc] = useState("");
  const create = useAction(() => api.post<Price>("/prices/", { desc }).then((r) => r.data), {
    success: "Hisob-kitob yaratildi",
    invalidate: ["prices"],
    onSuccess: (p) => navigate(`/prices/${p.id}`),
  });

  return (
    <>
      <OfferAgenda
        kind="price"
        actions={
          <div className="flex flex-wrap gap-2">
            {boss && !!free?.unassigned && (
              <Button variant="outline" icon={<UserPlus className="h-4 w-4" />} onClick={() => setGiving(true)}>
                Menejerga berish ({free.unassigned})
              </Button>
            )}
            {can("price.add_price") && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                O'lchovsiz hisob-kitob
              </Button>
            )}
          </div>
        }
      />
      {giving && free && <AssignPricesModal total={free.unassigned} onClose={() => setGiving(false)} />}
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="O'lchovsiz hisob-kitob"
        size="sm"
        footer={<Button loading={create.isPending} onClick={() => create.mutate()}>Yaratish</Button>}
      >
        <Field label="Tavsif" hint="Masalan, mijoz ismi yoki obyekt">
          <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} />
        </Field>
      </Modal>
    </>
  );
}

function tomorrow18() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T18:00`;
}

/** Prices in work nobody calculates (from before the managers got the price job): give the
 * oldest N of them to a manager with a deadline. The manager gets each one in the bot. */
function AssignPricesModal({ total, onClose }: { total: number; onClose: () => void }) {
  const { data: people } = useGet<MeteringAssignees>("/meterings/assignees/");
  const [f, setF] = useState({ user: "", due_at: tomorrow18(), count: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const give = useAction(
    () =>
      api
        .post<{ assigned: number; left: number }>("/prices/assign/", {
          user: Number(f.user),
          due_at: f.due_at,
          count: f.count ? Number(f.count) : null,
        })
        .then((r) => r.data),
    {
      invalidate: ["prices"],
      onSuccess: (r) => {
        toast.success(`${r.assigned} ta narx menejerga berildi${r.left ? `, ${r.left} tasi qoldi` : ""}`);
        onClose();
      },
    },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title="Narxlarni menejerga berish"
      size="sm"
      footer={
        <Button disabled={!f.user || !f.due_at} loading={give.isPending} onClick={() => give.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Berish
        </Button>
      }
    >
      <div className="space-y-3">
        <p className="muted text-sm">
          Hech kimga biriktirilmagan <b>{total}</b> ta narx ishi bor. Eng eskilaridan boshlab menejerga beriladi. Har biri unga botda vazifa bo'lib boradi va «Vazifalarim»da chiqadi.
        </p>
        <Field label="Menejer" error={errors.user}>
          <Select value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}>
            <option value="">— tanlang —</option>
            {people?.pricers.map((u) => (
              <option key={u.id} value={u.id}>{u.name || u.phone}</option>
            ))}
          </Select>
        </Field>
        <Field label="Muddat" error={errors.due_at}>
          <Input type="datetime-local" value={f.due_at} onChange={(e) => setF({ ...f, due_at: e.target.value })} />
        </Field>
        <Field label="Nechta" hint={`bo'sh — hammasi (${total} ta). Ikki menejerga bo'lish uchun avval birinchisiga yarmini bering.`} error={errors.count}>
          <Input type="number" min={1} max={total} value={f.count} onChange={(e) => setF({ ...f, count: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

export { PriceDetailPage } from "./PriceDetail";
