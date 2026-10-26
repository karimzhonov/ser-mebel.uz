import { useEffect, useMemo, useState } from "react";
import { api, fieldErrors } from "@/api/client";
import type { Tone } from "@/api/types";
import { useAction, useAll, useGet } from "@/api/hooks";
import { Badge, Button, Field, Input, Modal, Segmented, Select, Spinner, Textarea } from "@/components/ui";
import { iso } from "@/components/DateRangeFilter";
import type { Car, FinCategory, FinMe, Member, Operation, Worker } from "./types";

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** «1 250 000 so'm» */
export function som(v: number | string | null | undefined, sign = false) {
  const n = Number(v ?? 0);
  const s = nf.format(Math.abs(Math.round(n)));
  return `${n < 0 ? "−" : sign && n > 0 ? "+" : ""}${s} so'm`;
}

export function usd(v: number | string | null | undefined) {
  return `$${nf2.format(Number(v ?? 0))}`;
}

export function inCur(v: number | string | null | undefined, cur: string) {
  return cur === "USD" ? usd(v) : som(v);
}

export function useFinMe() {
  return useGet<FinMe>("/finance/me/");
}

export function useMembers(params: Record<string, unknown> = {}, enabled = true) {
  return useAll<Member>("finance/members", params, enabled);
}

export function useCategories() {
  return useAll<FinCategory>("finance/categories");
}

export function CatLabel({ c }: { c?: Pick<FinCategory, "emoji" | "name" | "color"> | null }) {
  if (!c) return <>—</>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c.color }} />
      <span>
        {c.emoji} {c.name}
      </span>
    </span>
  );
}

export function RoleBadge({ role, label }: { role: string; label: string }) {
  const tone: Tone = role === "admin" ? "primary" : role === "staff" ? "ok" : role === "pending" ? "warn" : "idle";
  return <Badge tone={tone}>{label}</Badge>;
}

/** GET a protected file (JWT) and hand it to the browser. */
export async function downloadFile(path: string, params: Record<string, string>, fallbackName: string) {
  const r = await api.get(path, { params, responseType: "blob" });
  const cd = String(r.headers["content-disposition"] || "");
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] || fallbackName;
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function ReceiptModal({ op, onClose }: { op: Operation; onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let url = "";
    api
      .get(`/finance/operations/${op.id}/receipt/`, { responseType: "blob" })
      .then((r) => setSrc((url = URL.createObjectURL(r.data as Blob))))
      .catch(() => setError(true));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [op.id]);
  return (
    <Modal open onClose={onClose} title={`Chek · #${op.number}`}>
      {error ? (
        <p className="muted text-sm">Chekni Telegram'dan olib bo'lmadi.</p>
      ) : src ? (
        <img src={src} alt="Chek" className="mx-auto max-h-[70vh] rounded-lg" />
      ) : (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      )}
    </Modal>
  );
}

interface OpForm {
  member: string;
  kind: "income" | "expense";
  category_code: string;
  currency: "UZS" | "USD";
  amount: string;
  orig_amount: string;
  rate: string;
  order_ref: string;
  comment: string;
  worker: string;
  pay_type: string;
  date: string;
}

/** Create or edit an operation — the same rules as the bot (accounting/services.py). */
export function OperationModal({
  op,
  defaultMember,
  defaultKind = "expense",
  onClose,
}: {
  op?: Operation | null;
  defaultMember?: number | null;
  defaultKind?: "income" | "expense";
  onClose: () => void;
}) {
  const { data: me } = useFinMe();
  const { data: members } = useMembers({}, !!me?.view_all);
  const { data: cats } = useCategories();
  const { data: workers } = useAll<Worker>("finance/workers");
  const { data: cars } = useAll<Car>("finance/cars");
  const { data: usdRate } = useGet<{ usd_rate_effective: number }>("/finance/settings/");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [f, setF] = useState<OpForm>(() =>
    op
      ? {
          member: String(op.member),
          kind: op.kind,
          category_code: op.category_detail.code,
          currency: op.currency,
          amount: String(Math.round(Number(op.amount))),
          orig_amount: op.orig_amount ?? "",
          rate: op.rate ?? "",
          order_ref: op.order_ref,
          comment: op.comment,
          worker: op.worker,
          pay_type: op.pay_type,
          date: op.date,
        }
      : {
          member: defaultMember ? String(defaultMember) : "",
          kind: defaultKind,
          category_code: "",
          currency: "UZS",
          amount: "",
          orig_amount: "",
          rate: "",
          order_ref: "",
          comment: "",
          worker: "",
          pay_type: "",
          date: iso(new Date()),
        },
  );
  useEffect(() => {
    if (!f.member && me?.member) setF((x) => ({ ...x, member: String(me.member!.id) }));
  }, [me, f.member]);
  useEffect(() => {
    if (f.currency === "USD" && !f.rate && usdRate?.usd_rate_effective) setF((x) => ({ ...x, rate: String(usdRate.usd_rate_effective) }));
  }, [f.currency, f.rate, usdRate]);

  const cat = cats?.find((c) => c.code === f.category_code);
  const catOptions = useMemo(
    () => (cats ?? []).filter((c) => c.is_active && (c.kind === f.kind || (c.kind === "internal" && !!op)) || c.code === op?.category_detail.code),
    [cats, f.kind, op],
  );
  const needsOrder = !(f.kind === "expense" && (cat?.no_order || f.category_code === "oylik"));
  const bucket = f.kind === "income" ? (f.category_code === "qoldiq" ? "kutish,yakun" : "yangi,jarayonda,kutish,yakun") : f.category_code === "material" ? "jarayonda,yangi" : "jarayonda";
  const { data: orderOpts } = useGet<{ ref: string; client: string; bucket: string }[]>(needsOrder ? "/finance/order-options/" : null, { bucket });

  const save = useAction(
    async () => {
      const body: Record<string, unknown> = {
        kind: f.kind,
        category_code: f.category_code,
        currency: f.currency,
        order_ref: needsOrder ? f.order_ref : "",
        comment: f.comment,
        worker: f.worker,
        pay_type: f.category_code === "oylik" && f.kind === "expense" ? f.pay_type || "Avans" : "",
        date: f.date,
        member: Number(f.member),
      };
      if (f.currency === "USD") Object.assign(body, { orig_amount: f.orig_amount, rate: f.rate });
      else body.amount = f.amount;
      return op ? api.patch(`/finance/operations/${op.id}/`, body) : api.post("/finance/operations/", body);
    },
    { success: "Saqlandi", invalidate: ["finance"], onSuccess: onClose },
  );
  const set = (patch: Partial<OpForm>) => setF((x) => ({ ...x, ...patch }));
  const total = f.currency === "USD" ? Number(f.orig_amount || 0) * Number(f.rate || 0) : Number(f.amount || 0);
  const workerOptions = f.category_code === "zapravka" ? (cars ?? []).filter((c) => c.is_active).map((c) => c.name) : (workers ?? []).filter((w) => w.is_active).map((w) => w.name);

  return (
    <Modal
      open
      onClose={onClose}
      title={op ? `Amal #${op.number} — tahrirlash` : f.kind === "income" ? "Yangi kirim" : "Yangi chiqim"}
      footer={
        <Button loading={save.isPending} disabled={!f.member || !f.category_code || !total} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Saqlash
        </Button>
      }
    >
      <div className="space-y-4">
        {!op?.pair_number && (
          <Segmented
            value={f.kind}
            onChange={(kind) => set({ kind, category_code: "" })}
            options={[
              { value: "expense", label: "➖ Chiqim" },
              { value: "income", label: "➕ Kirim" },
            ]}
          />
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Hamyon (xodim)" error={errors.member}>
            <Select value={f.member} onChange={(e) => set({ member: e.target.value })} disabled={!me?.view_all}>
              <option value="">— tanlang —</option>
              {(me?.view_all ? members?.filter((m) => m.has_wallet || String(m.id) === f.member) : me?.member ? [me.member] : [])?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Sana" error={errors.date}>
            <Input type="date" value={f.date} onChange={(e) => set({ date: e.target.value })} />
          </Field>
        </div>
        <Field label="Kategoriya" error={errors.category_code}>
          <Select value={f.category_code} onChange={(e) => set({ category_code: e.target.value, worker: "", order_ref: "" })}>
            <option value="">— tanlang —</option>
            {catOptions.map((c) => (
              <option key={c.code} value={c.code}>
                {c.emoji} {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
          <Field label="Valyuta">
            <Segmented value={f.currency} onChange={(currency) => set({ currency })} options={[{ value: "UZS", label: "so'm" }, { value: "USD", label: "$" }]} />
          </Field>
          {f.currency === "UZS" ? (
            <Field label="Summa (so'm)" error={errors.amount}>
              <Input inputMode="numeric" value={f.amount} onChange={(e) => set({ amount: e.target.value.replace(/[^\d]/g, "") })} placeholder="250000" />
            </Field>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Summa ($)" error={errors.orig_amount}>
                <Input inputMode="decimal" value={f.orig_amount} onChange={(e) => set({ orig_amount: e.target.value.replace(/[^\d.]/g, "") })} />
              </Field>
              <Field label="Kurs" error={errors.rate}>
                <Input inputMode="decimal" value={f.rate} onChange={(e) => set({ rate: e.target.value.replace(/[^\d.]/g, "") })} />
              </Field>
            </div>
          )}
        </div>
        {total > 0 && <p className="muted -mt-2 text-sm">= {som(total)}</p>}
        {(f.category_code === "oylik" || f.category_code === "zapravka") && f.kind === "expense" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={f.category_code === "zapravka" ? "Mashina / kim" : "Kimga oylik"} error={errors.worker}>
              <Input list="fin-workers" value={f.worker} onChange={(e) => set({ worker: e.target.value })} />
              <datalist id="fin-workers">
                {workerOptions.map((n) => (
                  <option key={n} value={n} />
                ))}
              </datalist>
            </Field>
            {f.category_code === "oylik" && (
              <Field label="Turi">
                <Select value={f.pay_type || "Avans"} onChange={(e) => set({ pay_type: e.target.value })}>
                  <option value="Avans">💵 Avans</option>
                  <option value="Oylik">🧾 Oylik</option>
                </Select>
              </Field>
            )}
          </div>
        )}
        {needsOrder && (
          <Field label="Buyurtma ID" hint="Ro'yxatdan tanlang yoki ID yozing (bo'sh — umumiy)" error={errors.order_ref}>
            <Input list="fin-orders" value={f.order_ref} onChange={(e) => set({ order_ref: e.target.value.trim() })} placeholder="406" />
            <datalist id="fin-orders">
              {orderOpts?.map((o) => (
                <option key={o.ref} value={o.ref}>
                  {o.client}
                </option>
              ))}
            </datalist>
          </Field>
        )}
        <Field label="Izoh" error={errors.comment || errors.detail}>
          <Textarea value={f.comment} onChange={(e) => set({ comment: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

export function TransferModal({ onClose, defaultSender }: { onClose: () => void; defaultSender?: number | null }) {
  const { data: me } = useFinMe();
  const { data: members } = useMembers({}, !!me?.view_all);
  const wallets = me?.view_all ? (members ?? []).filter((m) => m.has_wallet) : [];
  const [f, setF] = useState({ sender: defaultSender ? String(defaultSender) : me?.member ? String(me.member.id) : "", receiver: "", amount: "", comment: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    () => api.post("/finance/operations/transfer/", { sender: Number(f.sender), receiver: Number(f.receiver), amount: f.amount, comment: f.comment }),
    { success: "O'tkazildi", invalidate: ["finance"], onSuccess: onClose },
  );
  const list = me?.view_all ? wallets : me?.member ? [me.member] : [];
  return (
    <Modal
      open
      onClose={onClose}
      title="🔄 Xodimga pul berish"
      size="sm"
      footer={
        <Button loading={save.isPending} disabled={!f.sender || !f.receiver || !f.amount} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          O'tkazish
        </Button>
      }
    >
      <div className="space-y-4">
        <Field label="Kimdan" error={errors.sender}>
          <Select value={f.sender} onChange={(e) => setF({ ...f, sender: e.target.value })}>
            <option value="">—</option>
            {list.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Kimga" error={errors.receiver || errors.detail}>
          <Select value={f.receiver} onChange={(e) => setF({ ...f, receiver: e.target.value })}>
            <option value="">—</option>
            {(me?.view_all ? wallets : members ?? []).filter((m) => String(m.id) !== f.sender).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Summa (so'm)" error={errors.amount}>
          <Input inputMode="numeric" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^\d]/g, "") })} />
        </Field>
        <Field label="Izoh">
          <Input value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} placeholder="zapravkaga" />
        </Field>
      </div>
    </Modal>
  );
}
