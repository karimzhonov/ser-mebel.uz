import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, Download, ImageIcon, Pencil, Plus, Star, Trash2, Undo2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage, fieldErrors } from "@/api/client";
import { useAction, useGet, useList } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DateRangeFilter, iso, monthStartISO } from "@/components/DateRangeFilter";
import { Badge, Button, Card, DataTable, Empty, Field, IconButton, Input, Modal, PageHeader, Pagination, SearchInput, Segmented, Select, StatTile, Textarea } from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { downscale } from "@/lib/image";
import { useUrlState } from "@/lib/useUrlState";
import { downloadFile } from "@/pages/finance/shared";

// ---------------------------------------------------------------- types
const MAX_PHOTOS = 5;
interface Photo {
  id: number;
  url: string;
  thumb: string;
  position: number;
  width: number;
  height: number;
}
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
  photos: Photo[];
  cover: Photo | null;
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
  allocations: { ref: string; client: string; quantity: string; total: string; order_id: number | null }[];
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

interface OrderOption {
  ref: string;
  client: string;
  bucket: string;
  status_label: string;
}

/** «406×4 · SM-003×2» chips for a chiqim's clients */
function AllocChips({ items }: { items: Movement["allocations"] }) {
  if (!items?.length) return null;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {items.map((a) => (
        <Badge key={a.ref} tone="info">{a.ref}×{nf.format(Number(a.quantity))}</Badge>
      ))}
    </span>
  );
}

/** Pick a client / order ID (debounced search over the active orders). */
function OrderPicker({ taken, onPick }: { taken: string[]; onPick: (o: OrderOption) => void }) {
  const [text, setText] = useState("");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setTerm(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);
  const { data, isFetching } = useGet<OrderOption[]>("/warehouse/orders/", { search: term });
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const options = (data ?? []).filter((o) => !taken.includes(o.ref));
  return (
    <div ref={box} className="relative flex-1">
      <Input value={text} placeholder="ID yoki mijoz ismi" onFocus={() => setOpen(true)} onChange={(e) => (setText(e.target.value), setOpen(true))} />
      {open && (
        <div className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-pop dark:border-slate-700 dark:bg-slate-900">
          {options.length === 0 && <div className="muted px-3 py-2 text-sm">{isFetching || text.trim() !== term ? "Yuklanmoqda…" : "Topilmadi"}</div>}
          {options.map((o) => (
            <button
              key={o.ref}
              type="button"
              className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
              onClick={() => (onPick(o), setText(""), setOpen(false))}
            >
              <b>{o.ref}</b> · {o.client || "—"} <span className="muted">({o.status_label})</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
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

/** 40x40 cover in the stock table; a click opens the picture (not the history). */
function CoverThumb({ product, onOpen }: { product: Product; onOpen: (p: Product) => void }) {
  if (!product.cover)
    return (
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-400 dark:bg-slate-800">
        <ImageIcon className="h-4 w-4" />
      </div>
    );
  return (
    <button type="button" className="block" onClick={(e) => (e.stopPropagation(), onOpen(product))}>
      <img src={product.cover.thumb} alt={product.name} loading="lazy" className="h-10 w-10 rounded-lg object-cover" />
    </button>
  );
}

/** Big view of one picture (arrows through the product's pictures). */
function Lightbox({ name, photos, start, onClose }: { name: string; photos: Photo[]; start: number; onClose: () => void }) {
  const [i, setI] = useState(Math.min(start, Math.max(photos.length - 1, 0)));
  const ph = photos[i];
  return (
    <Modal open onClose={onClose} title={name} size="lg" footer={photos.length > 1 ? (
      <>
        <Button variant="outline" disabled={i === 0} onClick={() => setI(i - 1)}>←</Button>
        <span className="self-center text-sm tabular-nums">{i + 1} / {photos.length}</span>
        <Button variant="outline" disabled={i >= photos.length - 1} onClick={() => setI(i + 1)}>→</Button>
      </>
    ) : undefined}>
      {ph ? <img src={ph.url} alt={name} className="mx-auto max-h-[70vh] w-auto rounded-lg object-contain" /> : <Empty title="Rasm yo'q" />}
    </Modal>
  );
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
  const [zoom, setZoom] = useState<Product | null>(null);
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
            { key: "p", header: "", cell: (r) => <CoverThumb product={r} onOpen={setZoom} /> },
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
      {zoom && <Lightbox name={zoom.name} photos={zoom.photos} start={0} onClose={() => setZoom(null)} />}
    </div>
  );
}

/** «Rasmlar (n/5)»: thumbnails, cover mark, upload / cover / delete for the omborchi. */
function PhotosSection({ product }: { product: Product }) {
  const isKeeper = useKeeper();
  const [photos, setPhotos] = useState<Photo[]>(product.photos ?? []);
  const [view, setView] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const done = (data: { photos: Photo[] }) => setPhotos(data.photos);
  const cover = useAction((pid: number) => api.post<{ photos: Photo[] }>(`/warehouse/products/${product.id}/photos/${pid}/cover/`).then((r) => r.data), {
    success: "Asosiy rasm o'zgardi",
    invalidate: ["warehouse"],
    onSuccess: done,
  });
  const remove = useAction((pid: number) => api.delete<{ photos: Photo[] }>(`/warehouse/products/${product.id}/photos/${pid}/`).then((r) => r.data), {
    success: "Rasm o'chirildi",
    invalidate: ["warehouse"],
    onSuccess: done,
  });
  const qc = useQueryClient();
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    let room = MAX_PHOTOS - photos.length;
    try {
      for (const file of Array.from(files)) {
        if (room <= 0) {
          toast.error(`Bitta mahsulotga ${MAX_PHOTOS} tadan ortiq rasm bo'lmaydi.`);
          break;
        }
        try {
          const blob = await downscale(file, 1600, 0.85);
          const body = new FormData();
          body.append("file", blob, "photo.jpg");
          const { data } = await api.post<{ photos: Photo[] }>(`/warehouse/products/${product.id}/photos/`, body);
          setPhotos(data.photos);
          room -= 1;
        } catch (e) {
          toast.error(`${file.name}: ${errorMessage(e)}`);
        }
      }
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
      qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes("warehouse") });
    }
  };
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">Rasmlar ({photos.length}/{MAX_PHOTOS})</span>
        {isKeeper && photos.length < MAX_PHOTOS && (
          <>
            <input ref={input} type="file" multiple accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => upload(e.target.files)} />
            <Button variant="outline" size="sm" icon={<Plus className="h-4 w-4" />} loading={uploading} onClick={() => input.current?.click()}>
              Rasm qo'shish
            </Button>
          </>
        )}
      </div>
      {photos.length === 0 ? (
        <div className="muted rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm dark:border-slate-700">Rasm yo'q</div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {photos.map((ph, idx) => (
            <div key={ph.id} className="group relative overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
              <button type="button" className="block w-full" onClick={() => setView(idx)}>
                <img src={ph.thumb} alt="" loading="lazy" className="aspect-square w-full object-cover" />
              </button>
              {idx === 0 && <Badge tone="primary" className="absolute left-1 top-1">Asosiy</Badge>}
              {isKeeper && (
                <div className="absolute right-1 top-1 flex gap-1">
                  {idx !== 0 && (
                    <IconButton label="Asosiy qilish" className="h-7 w-7 bg-white/90 dark:bg-slate-900/90" onClick={() => cover.mutate(ph.id)}>
                      <Star className="h-4 w-4" />
                    </IconButton>
                  )}
                  <IconButton label="O'chirish" className="h-7 w-7 bg-white/90 dark:bg-slate-900/90" onClick={() => confirm("Rasm o'chirilsinmi?") && remove.mutate(ph.id)}>
                    <Trash2 className="h-4 w-4" />
                  </IconButton>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {view !== null && <Lightbox name={product.name} photos={photos} start={view} onClose={() => setView(null)} />}
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
        {product ? <PhotosSection product={product} /> : <p className="muted text-xs">Rasmni saqlagandan keyin qo'shasiz</p>}
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
    comment: "",
  });
  const [rows, setRows] = useState<{ ref: string; client: string; quantity: string }[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const p = list.find((x) => String(x.id) === f.product);
  const rate = Number(f.rate || sm?.usd_rate || 0) || 0; // "." → 0, not NaN
  const withRows = f.kind === "out" && rows.length > 0;
  const rowsSum = rows.reduce((a, r) => a + (Number(r.quantity) || 0), 0);
  const effQty = withRows ? rowsSum : Number(f.quantity || 0);
  const stock = p ? Number(p.quantity) : null;
  const over = withRows && stock !== null && Math.round(rowsSum * 1000) > Math.round(stock * 1000);
  const unitSom = Number(f.unit_price || 0) * (f.currency === "USD" ? rate : 1);
  const totalIn = effQty * Number(f.unit_price || 0); // in the chosen currency
  const totalSom = f.currency === "USD" ? totalIn * rate : totalIn;
  const save = useAction(
    () =>
      api.post("/warehouse/movements/", {
        kind: f.kind,
        product: Number(f.product),
        ...(withRows ? { allocations: rows.map((r) => ({ ref: r.ref, quantity: r.quantity })) } : { quantity: f.quantity }),
        date: f.date,
        counterparty: f.counterparty,
        comment: f.comment,
        currency: f.currency,
        ...(f.currency === "USD" ? { orig_price: f.unit_price, rate: f.rate ? f.rate : rate || undefined } : { unit_price: f.unit_price }),
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
      footer={<Button disabled={!f.product || (withRows ? rows.some((r) => !Number(r.quantity)) || over : !f.quantity) || f.unit_price === ""} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>Saqlash</Button>}
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
            <Input inputMode="decimal" readOnly={withRows} value={withRows ? String(Math.round(rowsSum * 1000) / 1000) : f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value.replace(/[^\d.]/g, "") })} />
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
          <Field label="Mijozlar (ID)" hint="Ixtiyoriy: har bir ID uchun miqdor — furnitura xarajati sifatida hisoblanadi" error={errors.allocations}>
            <div className="space-y-2">
              {rows.map((r, i) => (
                <div key={r.ref} className="flex items-start gap-2">
                  <div className="flex-1 pt-2 text-sm"><b>{r.ref}</b> · {r.client || "—"}</div>
                  <div className="w-28">
                    <Input inputMode="decimal" placeholder="Miqdor" value={r.quantity} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, quantity: e.target.value.replace(/[^\d.]/g, "") } : x)))} />
                    {unitSom > 0 && Number(r.quantity) > 0 && <div className="muted mt-0.5 text-xs">≈ {som(Number(r.quantity) * unitSom)}</div>}
                  </div>
                  <IconButton label="Olib tashlash" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></IconButton>
                </div>
              ))}
              {rows.length < 20 && <OrderPicker taken={rows.map((r) => r.ref)} onPick={(o) => setRows([...rows, { ref: o.ref, client: o.client, quantity: "" }])} />}
              {withRows && (
                <p className={`text-sm ${over ? "font-medium text-rose-600" : ""}`}>
                  Jami: {qty(rowsSum, p?.unit_label)}{stock !== null && ` / omborda ${qty(stock, p?.unit_label)}`}
                </p>
              )}
            </div>
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
          { key: "c", header: "Kimdan / kimga", cell: (r) => <span>{r.counterparty || "—"}<AllocChips items={r.allocations} /></span> },
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
            { key: "c", header: "Kimdan / kimga", cell: (r) => <span className="text-sm">{r.counterparty || "—"}<AllocChips items={r.allocations} /></span>, hideOnMobile: true },
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
