import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, UserPlus } from "lucide-react";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { MeteringAssignees, Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Confirm, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { date } from "@/lib/format";
import { OfferAgenda } from "./offers/OfferAgenda";

/** «Narx hisoblash» — the pricer's agenda (deadline first, overdue in red) + a price without a zamer. */
export function PricesPage() {
  const navigate = useNavigate();
  const { can, user } = useAuth();
  const boss = !!user?.is_superuser || can("metering.manage_metering");
  const { data: free } = useGet<{ unassigned: number }>(boss ? "/prices/assign/" : null);
  const [giving, setGiving] = useState(false);
  const [cleaning, setCleaning] = useState(false);
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
            {user?.is_superuser && !!free?.unassigned && (
              <Button variant="ghost" className="text-rose-600" icon={<Trash2 className="h-4 w-4" />} onClick={() => setCleaning(true)}>
                Eskilarini o'chirish
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
      {cleaning && <DeleteOldPricesModal onClose={() => setCleaning(false)} />}
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

interface OldPrice { id: number; client: string; phone: string; created_at: string; has_order: boolean }

/** Admin: review the prices nobody calculates and delete the ones not needed any more. */
function DeleteOldPricesModal({ onClose }: { onClose: () => void }) {
  const { data: rows } = useGet<OldPrice[]>("/prices/unassigned/");
  const [picked, setPicked] = useState<number[]>([]);
  const [ask, setAsk] = useState(false);
  const can = (rows ?? []).filter((r) => !r.has_order);
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const remove = useAction(() => api.post<{ deleted: number; kept: number }>("/prices/unassigned/delete/", { ids: picked }).then((r) => r.data), {
    invalidate: ["prices"],
    onSuccess: (r) => {
      toast.success(`${r.deleted} ta narx o'chirildi${r.kept ? `, ${r.kept} tasi qoldi` : ""}`);
      setAsk(false);
      setPicked([]);
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Eski narxlarni o'chirish"
      size="lg"
      footer={
        <Button variant="danger" disabled={!picked.length} onClick={() => setAsk(true)}>
          O'chirish ({picked.length})
        </Button>
      }
    >
      <p className="muted mb-3 text-sm">
        Hech kimga biriktirilmagan narx ishlari. Keraksizlarini belgilang — ular hisob-kitoblari bilan butunlay o'chiriladi. Buyurtmaga aylangan zamerning narxini o'chirib bo'lmaydi.
      </p>
      {!rows ? (
        <p className="muted text-sm">Yuklanmoqda…</p>
      ) : (
        <>
          <label className="mb-2 flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={!!can.length && picked.length === can.length} onChange={(e) => setPicked(e.target.checked ? can.map((r) => r.id) : [])} />
            Hammasini belgilash ({can.length})
          </label>
          <ul className="max-h-[55vh] divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
            {rows.map((r) => (
              <li key={r.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm">
                  <input type="checkbox" disabled={r.has_order} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{r.client}</span>
                    <span className="muted block text-xs">{r.phone}</span>
                  </span>
                  {r.has_order ? <Badge tone="ok">buyurtma bor</Badge> : <span className="muted whitespace-nowrap text-xs">{date(r.created_at)}</span>}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
      <Confirm
        open={ask}
        onClose={() => setAsk(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        variant="danger"
        confirmLabel="O'chirish"
        title="Narxlarni o'chirish"
        text={<><b>{picked.length}</b> ta narx hisob-kitoblari bilan butunlay o'chiriladi. Buni qaytarib bo'lmaydi.</>}
      />
    </Modal>
  );
}

export { PriceDetailPage } from "./PriceDetail";
