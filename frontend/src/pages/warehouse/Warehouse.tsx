import { useMemo, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, Download, Pencil, Plus, Undo2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Badge, Button, Card, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, Pagination, SearchInput, Segmented, Select, StatTile, Textarea } from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";
import { downloadFile } from "@/pages/finance/shared";

// ---------------------------------------------------------------- types
interface Product {
  id: number;
  name: string;
  code: string;
  category: string;
  unit: string;
  unit_label: string;
  min_quantity: string;
  quantity: string;
  avg_cost: string;
  value: number;
  avg_cost_usd: number | null;
  value_usd: number | null;
  low: boolean;
  is_active: boolean;
}
interface Movement {
  id: number;
  number: number;
  product: number;
  product_name: string;
  product_unit: string;
  kind: "in" | "out";
  kind_label: string;
  quantity: string;
  currency: "UZS" | "USD";
  orig_price: string | null;
  rate: string | null;
  unit_price: string;
  total: string;
  date: string;
  counterparty: string;
  order_number: number | null;
  comment: string;
  balance_after: string;
  created_by_detail: { id: number; name: string | null; phone: string } | null;
  created_at: string;
  is_cancelled: boolean;
}
interface Summary {
  products: number;
  stock_value: string;
  stock_value_usd: number | null;
  usd_rate: string;
  low_stock: { id: number; name: string; quantity: string; min_quantity: string; unit: string }[];
  period_in: string;
  period_out: string;
  keeper: { id: number; name: string | null; phone: string } | null;
  is_keeper: boolean;
}

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 });
const som = (v: number | string | null | undefined) => `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0))} so'm`;
const usd = (v: number | string | null | undefined) => `$${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(v ?? 0))}`;
/** price as it was typed: «$11.00 × 12 500» or «120 000 so'm» */
const priceText = (m: Pick<Movement, "currency" | "orig_price" | "rate" | "unit_price">) =>
  m.currency === "USD" ? `${usd(m.orig_price)} × ${new Intl.NumberFormat("ru-RU").format(Number(m.rate))}` : som(m.unit_price);
const qty = (v: number | string, unit?: string) => `${nf.format(Number(v))}${unit ? ` ${unit}` : ""}`;

function useKeeper() {
  const { user } = useAuth();
  return !!user?.is_warehouse_keeper;
}

/** Shown instead of the Kirim/Chiqim buttons: only the omborchi books, so say why. */
function KeeperNote({ keeper }: { keeper?: Summary["keeper"] }) {
  const { user } = useAuth();
  if (user?.is_warehouse_keeper) return null;
  return (
    <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
      {keeper
        ? `Kirim va chiqimni faqat omborchi — ${keeper.name || keeper.phone} — kiritadi. Siz faqat ko'rasiz.`
        : "Omborchi hali tayinlanmagan, shuning uchun kirim va chiqim kiritib bo'lmaydi."}
      {user?.is_superuser && (
        <>
          {" "}
          <Link to="/warehouse/settings" className="font-medium underline">
            {keeper ? "Omborchini almashtirish" : "Omborchi tayinlash"} →
          </Link>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- stock
export function WarehouseStockPage() {
  const isKeeper = useKeeper();
  const { state, page, set } = useUrlState({ search: "", category: "", low: "", active: "1", cur: "UZS" });
  const inUsd = state.cur === "USD";
  const { data, isFetching } = useList<Product>("warehouse/products", { ...state, page, ordering: "name" });
  const { data: s } = useGet<Summary>("/warehouse/summary/", { date_from: monthStartISO(), date_to: iso(new Date()) });
  const { data: meta } = useGet<{ categories: string[]; units: { value: string; label: string }[] }>("/warehouse/products/categories/");
  const [product, setProduct] = useState<Product | "new" | null>(null);
  const [history, setHistory] = useState<Product | null>(null);
  const [move, setMove] = useState<{ kind: "in" | "out"; product?: Product } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <PageHeader
        title="Ombor — qoldiq"
        subtitle={s?.keeper ? `Omborchi: ${s.keeper.name || s.keeper.phone}` : "Omborchi tayinlanmagan"}
        actions={
          <>
            <Button variant="outline" icon={<Download className="h-4 w-4" />} loading={busy} onClick={() => (setBusy(true), downloadFile("/warehouse/export/", {}, "Ombor.xlsx").finally(() => setBusy(false)))}>
              Excel
            </Button>
            {isKeeper && (
              <>
                <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setProduct("new")}>Mahsulot</Button>
                <Button variant="outline" icon={<ArrowUpFromLine className="h-4 w-4" />} onClick={() => setMove({ kind: "out" })}>Chiqim</Button>
                <Button icon={<ArrowDownToLine className="h-4 w-4" />} onClick={() => setMove({ kind: "in" })}>Kirim</Button>
              </>
            )}
          </>
        }
      />
      {s && <KeeperNote keeper={s.keeper} />}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="📦 Mahsulotlar" value={s?.products ?? 0} tone="primary" />
        <StatTile
          label="💰 Ombordagi qiymat"
          value={inUsd ? usd(s?.stock_value_usd) : som(s?.stock_value)}
          tone="ok"
          hint={inUsd ? `kurs ${som(s?.usd_rate)} · ${som(s?.stock_value)}` : `o'rtacha tannarx bo'yicha · ${usd(s?.stock_value_usd)}`}
        />
        <StatTile label="⚠️ Kam qolgan" value={s?.low_stock.length ?? 0} tone={s?.low_stock.length ? "danger" : "idle"} onClick={() => set({ low: state.low ? "" : "1" })} active={!!state.low} />
        <StatTile label="Shu oy: kirim / chiqim" value={`${som(s?.period_in)}`} tone="info" hint={`chiqim ${som(s?.period_out)}`} />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 lg:flex-row dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(search) => set({ search })} placeholder="Nomi, kodi yoki turi" />
          <Select className="lg:w-52" value={state.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">Barcha turlar</option>
            {meta?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
          <Segmented value={state.cur} onChange={(cur) => set({ cur })} options={[{ value: "UZS", label: "so'm" }, { value: "USD", label: "$" }]} />
          <Segmented value={state.active} onChange={(active) => set({ active })} options={[{ value: "1", label: "Faol" }, { value: "0", label: "Faol emas" }, { value: "", label: "Hammasi" }]} />
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          onRowClick={setHistory}
          rowClassName={(r) => (r.low ? "bg-rose-50/60 dark:bg-rose-500/5" : undefined)}
          columns={[
            { key: "n", header: "Mahsulot", cell: (r) => <span><span className="font-medium">{r.name}</span>{r.code && <span className="muted ml-1 text-xs">{r.code}</span>}</span> },
            { key: "c", header: "Turi", cell: (r) => r.category || "—", hideOnMobile: true },
            { key: "q", header: "Qoldiq", cell: (r) => <span className={`font-semibold tabular-nums ${r.low ? "text-rose-600" : ""}`}>{qty(r.quantity, r.unit_label)}{r.low && <Badge tone="danger" className="ml-2">kam</Badge>}</span> },
            { key: "a", header: "O'rtacha narx", cell: (r) => <span className="tabular-nums">{inUsd ? usd(r.avg_cost_usd) : som(r.avg_cost)}</span>, hideOnMobile: true },
            { key: "v", header: "Qiymati", cell: (r) => <span className="tabular-nums">{inUsd ? usd(r.value_usd) : som(r.value)}</span> },
            {
              key: "x",
              header: "",
              cell: (r) =>
                isKeeper ? (
                  <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                    <IconButton label="Kirim" onClick={() => setMove({ kind: "in", product: r })}><ArrowDownToLine className="h-4 w-4" /></IconButton>
                    <IconButton label="Chiqim" onClick={() => setMove({ kind: "out", product: r })}><ArrowUpFromLine className="h-4 w-4" /></IconButton>
                    <IconButton label="Tahrirlash" onClick={() => setProduct(r)}><Pencil className="h-4 w-4" /></IconButton>
                  </div>
                ) : null,
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {product && <ProductModal product={product === "new" ? null : product} meta={meta} onClose={() => setProduct(null)} />}
      {move && <MovementModal kind={move.kind} product={move.product} onClose={() => setMove(null)} />}
      {history && <HistoryModal product={history} onClose={() => setHistory(null)} />}
    </div>
  );
}

function ProductModal({ product, meta, onClose }: { product: Product | null; meta?: { categories: string[]; units: { value: string; label: string }[] }; onClose: () => void }) {
  const [f, setF] = useState({
    name: product?.name ?? "",
    code: product?.code ?? "",
    category: product?.category ?? "",
    unit: product?.unit ?? "dona",
    min_quantity: product ? String(Number(product.min_quantity)) : "0",
    is_active: product?.is_active ?? true,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(() => (product ? api.patch(`/warehouse/products/${product.id}/`, f) : api.post("/warehouse/products/", f)), {
    success: "Saqlandi",
    invalidate: ["warehouse"],
    onSuccess: onClose,
  });
  return (
    <Modal open onClose={onClose} title={product ? product.name : "Yangi mahsulot"} size="sm" footer={<Button disabled={!f.name.trim()} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}>
      <div className="space-y-3">
        <Field label="Nomi" error={errors.name || errors.detail}>
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="LDSP oq 16 mm" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kod / artikul" error={errors.code}>
            <Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
          </Field>
          <Field label="Turi" error={errors.category}>
            <Input list="wh-cats" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} placeholder="LDSP, furnitura…" />
            <datalist id="wh-cats">{meta?.categories.map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
          <Field label="O'lchov birligi">
            <Select value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}>
              {meta?.units.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </Select>
          </Field>
          <Field label="Minimal qoldiq" hint="shundan kam qolsa ogohlantiradi" error={errors.min_quantity}>
            <Input inputMode="decimal" value={f.min_quantity} onChange={(e) => setF({ ...f, min_quantity: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
        </div>
        {product && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Faol
          </label>
        )}
      </div>
    </Modal>
  );
}

function MovementModal({ kind: initialKind, product: initial, onClose }: { kind: "in" | "out"; product?: Product; onClose: () => void }) {
  const [search, setSearch] = useState("");
  const { data: products } = useList<Product>("warehouse/products", { active: "1", page_size: 200, ordering: "name", search });
  const list = useMemo(() => {
    const l = products?.results ?? [];
    // keep the chosen product in the list even when the search hides it
    return initial && !l.some((x) => x.id === initial.id) ? [initial, ...l] : l;
  }, [products, initial]);
  const { data: sm } = useGet<Summary>("/warehouse/summary/");
  const defaultPrice = (x: Product | undefined, kind: string, cur: string) =>
    !x || kind !== "out" ? "" : cur === "USD" ? String(x.avg_cost_usd ?? "") : String(Math.round(Number(x.avg_cost)));
  const [f, setF] = useState({
    kind: initialKind,
    product: initial ? String(initial.id) : "",
    quantity: "",
    currency: "UZS" as "UZS" | "USD",
    rate: "",
    unit_price: defaultPrice(initial, initialKind, "UZS"),
    date: iso(new Date()),
    counterparty: "",
    order_number: "",
    comment: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const p = list.find((x) => String(x.id) === f.product);
  const rate = Number(f.rate || sm?.usd_rate || 0) || 0; // "." → 0, not NaN
  const totalIn = Number(f.quantity || 0) * Number(f.unit_price || 0); // in the chosen currency
  const totalSom = f.currency === "USD" ? totalIn * rate : totalIn;
  const save = useAction(
    () =>
      api.post("/warehouse/movements/", {
        kind: f.kind,
        product: Number(f.product),
        quantity: f.quantity,
        date: f.date,
        counterparty: f.counterparty,
        comment: f.comment,
        currency: f.currency,
        ...(f.currency === "USD" ? { orig_price: f.unit_price, rate: f.rate ? f.rate : rate || undefined } : { unit_price: f.unit_price }),
        order_number: f.order_number ? Number(f.order_number) : null,
      }),
    { success: f.kind === "in" ? "Kirim yozildi" : "Chiqim yozildi", invalidate: ["warehouse"], onSuccess: onClose },
  );
  const pick = (id: string) => {
    const x = list.find((y) => String(y.id) === id);
    setF({ ...f, product: id, unit_price: f.kind === "out" && x ? defaultPrice(x, "out", f.currency) : f.unit_price });
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={f.kind === "in" ? "📥 Omborga kirim" : "📤 Ombordan chiqim"}
      footer={<Button disabled={!f.product || !f.quantity || f.unit_price === ""} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}
    >
      <div className="space-y-3">
        <Segmented value={f.kind} onChange={(kind) => setF({ ...f, kind })} options={[{ value: "in", label: "📥 Kirim" }, { value: "out", label: "📤 Chiqim" }]} />
        <SearchInput value={search} onChange={setSearch} placeholder="Mahsulotni qidirish (nomi yoki kodi)" />
        <Field label="Mahsulot" error={errors.product} hint={p ? `Omborda: ${qty(p.quantity, p.unit_label)} · o'rtacha narx ${som(p.avg_cost)} (${usd(p.avg_cost_usd)})` : undefined}>
          <Select value={f.product} onChange={(e) => pick(e.target.value)}>
            <option value="">— tanlang —</option>
            {list.map((x) => <option key={x.id} value={x.id}>{x.name} ({qty(x.quantity, x.unit_label)})</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={`Miqdor${p ? ` (${p.unit_label})` : ""}`} error={errors.quantity}>
            <Input inputMode="decimal" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
          <Field label={`Narxi (1 birlik, ${f.currency === "USD" ? "$" : "so'm"})`} error={errors.unit_price || errors.orig_price}>
            <Input inputMode="decimal" value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
        </div>
        <div className="grid grid-cols-[auto_1fr] items-end gap-3">
          <Field label="Valyuta">
            <Segmented
              value={f.currency}
              onChange={(currency) => setF({ ...f, currency, unit_price: defaultPrice(p, f.kind, currency) })}
              options={[{ value: "UZS", label: "so'm" }, { value: "USD", label: "$" }]}
            />
          </Field>
          {f.currency === "USD" && (
            <Field label="Kurs (1 $ = so'm)" hint={`Moliya kursi: ${som(sm?.usd_rate)}`} error={errors.rate}>
              <Input inputMode="decimal" value={f.rate} placeholder={String(Number(sm?.usd_rate ?? 0))} onChange={(e) => setF({ ...f, rate: e.target.value.replace(/[^\d.]/g, "") })} />
            </Field>
          )}
        </div>
        {totalIn > 0 && (
          <p className="text-sm">
            Jami: <b>{f.currency === "USD" ? `${usd(totalIn)} = ${som(totalSom)}` : som(totalSom)}</b>
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={f.kind === "in" ? "Kimdan (yetkazib beruvchi)" : "Kimga / qayerga"} error={errors.counterparty}>
            <Input value={f.counterparty} onChange={(e) => setF({ ...f, counterparty: e.target.value })} placeholder={f.kind === "in" ? "Kronospan" : "Sex, usta Dilmurod"} />
          </Field>
          <Field label="Sana" error={errors.date}>
            <Input type="date" max={iso(new Date())} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
          </Field>
        </div>
        {f.kind === "out" && (
          <Field label="Buyurtma № (ixtiyoriy)" error={errors.order_number}>
            <Input inputMode="numeric" value={f.order_number} onChange={(e) => setF({ ...f, order_number: e.target.value.replace(/\D/g, "") })} placeholder="406" />
          </Field>
        )}
        <Field label="Izoh" error={errors.comment || errors.detail}>
          <Textarea value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

function HistoryModal({ product, onClose }: { product: Product; onClose: () => void }) {
  // by number: «Qoldiq» after each movement follows the booking order
  const { data } = useList<Movement>("warehouse/movements", { product: product.id, page_size: 100, ordering: "-number" });
  return (
    <Modal open onClose={onClose} title={`${product.name} — ${qty(product.quantity, product.unit_label)}`} size="lg">
      <DataTable
        rows={data?.results}
        rowKey={(r) => r.id}
        empty={<Empty title="Harakat yo'q" />}
        columns={[
          { key: "d", header: "Sana", cell: (r) => date(r.date) },
          { key: "k", header: "Turi", cell: (r) => <Badge tone={r.kind === "in" ? "ok" : "warn"}>{r.kind_label}</Badge> },
          { key: "q", header: "Miqdor", cell: (r) => `${r.kind === "in" ? "+" : "−"}${qty(r.quantity)}` },
          { key: "p", header: "Narx", cell: (r) => priceText(r) },
          { key: "c", header: "Kimdan / kimga", cell: (r) => r.counterparty || "—" },
          { key: "b", header: "Qoldiq", cell: (r) => qty(r.balance_after) },
        ]}
      />
    </Modal>
  );
}

// ---------------------------------------------------------------- movements
export function WarehouseMovementsPage() {
  const isKeeper = useKeeper();
  const { state, page, set } = useUrlState({ date_from: monthStartISO(), date_to: iso(new Date()), kind: "", search: "", cancelled: "0" });
  const { data, isFetching } = useList<Movement>("warehouse/movements", { ...state, page });
  const [move, setMove] = useState<"in" | "out" | null>(null);
  const { data: sm } = useGet<Summary>("/warehouse/summary/");
  const cancel = useAction((id: number) => api.post(`/warehouse/movements/${id}/cancel/`), { success: "Bekor qilindi", invalidate: ["warehouse"] });
  const totals = (data?.results ?? []).reduce((acc, m) => ((acc[m.kind] += Number(m.total)), acc), { in: 0, out: 0 } as Record<string, number>);
  return (
    <div>
      <PageHeader
        title="Ombor — kirim va chiqim"
        actions={
          isKeeper && (
            <>
              <Button variant="outline" icon={<ArrowUpFromLine className="h-4 w-4" />} onClick={() => setMove("out")}>Chiqim</Button>
              <Button icon={<ArrowDownToLine className="h-4 w-4" />} onClick={() => setMove("in")}>Kirim</Button>
            </>
          )
        }
      />
      {sm && <KeeperNote keeper={sm.keeper} />}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateRangeFilter from={state.date_from} to={state.date_to} onChange={(date_from, date_to) => set({ date_from, date_to })} />
        <Segmented value={state.kind} onChange={(kind) => set({ kind })} options={[{ value: "", label: "Hammasi" }, { value: "in", label: "📥 Kirim" }, { value: "out", label: "📤 Chiqim" }]} />
        <Segmented value={state.cancelled} onChange={(cancelled) => set({ cancelled })} options={[{ value: "0", label: "Amaldagi" }, { value: "1", label: "Bekor qilingan" }]} />
      </div>
      <Card padded={false}>
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center dark:border-slate-800">
          <SearchInput className="flex-1" value={state.search} onChange={(search) => set({ search })} placeholder="Mahsulot, kimdan/kimga, izoh" />
          <span className="text-sm">sahifada: kirim <b>{som(totals.in)}</b> · chiqim <b>{som(totals.out)}</b></span>
        </div>
        <DataTable
          rows={data?.results}
          loading={isFetching}
          rowKey={(r) => r.id}
          rowClassName={(r) => (r.is_cancelled ? "opacity-50 line-through" : undefined)}
          columns={[
            { key: "n", header: "№", cell: (r) => <span className="muted">#{r.number}</span> },
            { key: "d", header: "Sana", cell: (r) => date(r.date) },
            { key: "k", header: "Turi", cell: (r) => <Badge tone={r.kind === "in" ? "ok" : "warn"}>{r.kind_label}</Badge> },
            { key: "p", header: "Mahsulot", cell: (r) => <span className="font-medium">{r.product_name}</span> },
            { key: "q", header: "Miqdor", cell: (r) => <span className="tabular-nums">{qty(r.quantity, r.product_unit)}</span> },
            { key: "u", header: "Narx", cell: (r) => <span className="tabular-nums">{priceText(r)}</span>, hideOnMobile: true },
            {
              key: "t",
              header: "Summa",
              cell: (r) => (
                <span className="tabular-nums">
                  <b>{som(r.total)}</b>
                  {r.currency === "USD" && r.orig_price && <span className="muted ml-1 text-xs">({usd(Number(r.orig_price) * Number(r.quantity))})</span>}
                </span>
              ),
            },
            { key: "c", header: "Kimdan / kimga", cell: (r) => <span className="text-sm">{r.counterparty || "—"}{r.order_number && <span className="muted"> · №{r.order_number}</span>}</span>, hideOnMobile: true },
            { key: "w", header: "Kiritdi", cell: (r) => <span className="muted text-xs">{r.created_by_detail?.name || r.created_by_detail?.phone} · {dateTime(r.created_at)}</span>, hideOnMobile: true },
            {
              key: "x",
              header: "",
              cell: (r) =>
                isKeeper && !r.is_cancelled ? (
                  <IconButton label="Bekor qilish" onClick={() => confirm(`#${r.number} bekor qilinsinmi? Qoldiq qayta hisoblanadi.`) && cancel.mutate(r.id)}>
                    <Undo2 className="h-4 w-4" />
                  </IconButton>
                ) : null,
            },
          ]}
        />
        <Pagination page={page} count={data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </Card>
      {move && <MovementModal kind={move} onClose={() => setMove(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- keeper (owner only)
export function WarehouseSettingsPage() {
  const { data } = useGet<{ keeper: { id: number; name: string | null; phone: string } | null }>("/warehouse/keeper/");
  const { data: users } = useList<{ id: number; name: string | null; phone: string; is_superuser: boolean; is_active: boolean }>("users", { page_size: 200 });
  const [userId, setUserId] = useState("");
  const [error, setError] = useState("");
  const save = useAction((uid: number | null) => api.put("/warehouse/keeper/", { user: uid }), {
    success: "Saqlandi",
    invalidate: ["warehouse", "users"],
    onSuccess: () => setUserId(""),
  });
  const candidates = (users?.results ?? []).filter((u) => !u.is_superuser && u.is_active);
  return (
    <div>
      <PageHeader title="Omborga mas'ul xodim" subtitle="Faqat shu xodim omborga kirim va chiqim qiladi; unga faqat «Ombor» bo'limi ko'rinadi" />
      <Card>
        <div className="space-y-4">
          <p className="text-sm">
            Hozir: <b>{data?.keeper ? data.keeper.name || data.keeper.phone : "tayinlanmagan"}</b>
          </p>
          <Field label="Xodimlar ro'yxatidan tanlang" error={error} hint="Yangi xodimni avval «Xodimlar» bo'limida qo'shing (telefon va parol)">
            <Select value={userId} onChange={(e) => (setError(""), setUserId(e.target.value))}>
              <option value="">— tanlang —</option>
              {candidates.map((u) => <option key={u.id} value={u.id}>{u.name || u.phone}</option>)}
            </Select>
          </Field>
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
            ⚠️ Tanlangan xodimning boshqa barcha huquqlari olib tashlanadi — u faqat omborni ko'radi. Avvalgi omborchidan ombor huquqi olinadi.
          </p>
          <div className="flex gap-2">
            <Button
              disabled={!userId}
              loading={save.isPending}
              onClick={() =>
                confirm("Shu xodim omborchi bo'ladi va uning boshqa barcha huquqlari olib tashlanadi. Davom etasizmi?") &&
                save.mutateAsync(Number(userId)).catch((e) => setError(fieldErrors(e).user || fieldErrors(e).detail || ""))
              }
            >
              Omborchi qilish
            </Button>
            {data?.keeper && (
              <Button variant="outline" onClick={() => confirm("Omborchini olib tashlaysizmi?") && save.mutate(null)}>
                Olib tashlash
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
