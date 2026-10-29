import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  ImageOff,
  ImagePlus,
  LayoutGrid,
  Pencil,
  Plus,
  Sofa,
  Table2,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, errorMessage, fetchBlob } from "@/api/client";
import { useAction, useAll, useGet } from "@/api/hooks";
import type { Calculation, InventoryType, ObjectType, OfferSheet, Price, Room, RoomImage, RoomType } from "@/api/types";
import { BackLink, DeadlinePill, FolderButton, OrderStatusBadge, PhoneLink } from "@/components/domain";
import {
  Badge,
  Button,
  Card,
  Confirm,
  Empty,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  PageLoader,
  Segmented,
  Select,
  Spinner,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { money, num, phone } from "@/lib/format";
import { useUrlState } from "@/lib/useUrlState";

const PdfViewer = lazy(() => import("@/components/PdfViewer"));
const INV = ["prices", "meterings", "orders"];
const usd = (amount: number) => money({ amount, currency: "USD" });

/* =================================================================== page */
export function PriceDetailPage() {
  const { id } = useParams();
  const { data: p, isLoading } = useGet<Price>(`/prices/${id}/`);
  const { data: objects } = useAll<ObjectType>("object-types");
  const { data: roomTypes } = useAll<RoomType>("room-types");
  const { state, set } = useUrlState({ view: "rooms" });
  const [editing, setEditing] = useState<{ calc?: Calculation; objectType: ObjectType; room: number | null } | null>(null);
  const [addingRoom, setAddingRoom] = useState(false);
  const [confirmDone, setConfirmDone] = useState(false);
  const [pdfOpen, setPdfOpen] = useState(false);

  const done = useAction(() => api.post(`/prices/${id}/done/`), { success: "Hisob-kitob bajarildi", invalidate: INV, onSuccess: () => setConfirmDone(false) });

  if (isLoading || !p || !objects || !roomTypes) return <PageLoader />;
  const title = p.metering?.client.fio ?? p.desc ?? `Hisob-kitob #${p.id}`;
  const canEdit = !!p.actions?.edit;
  const rooms = p.rooms ?? [];
  const calcs = p.calculations ?? [];
  const loose = calcs.filter((c) => c.room === null);
  const sheet = p.sheet;
  const roomTotal = (roomId: number | null) => sheet?.rooms.find((r) => r.id === roomId)?.total ?? 0;
  const pdfName = `Taklif — ${title}.pdf`;

  return (
    <div>
      <PageHeader
        back={<BackLink to="/prices">Narx hisoblash</BackLink>}
        title={title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {p.done ? <Badge tone="ok">Bajarildi</Badge> : <Badge tone="warn">Ishda</Badge>}
            {p.user_detail && <span>Smetchik: {p.user_detail.name || phone(p.user_detail.phone)}</span>}
          </span>
        }
        actions={
          <>
            <FolderButton folderId={p.metering?.folder} label="O'lchov fayllari" />
            <FolderButton folderId={p.folder} label="Hisob-kitob fayllari" />
            {p.actions?.done && (
              <Button variant="success" icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirmDone(true)}>
                Bajarish
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented
              value={state.view}
              onChange={(view) => set({ view })}
              options={[
                { value: "rooms", label: <span className="flex items-center gap-1.5"><LayoutGrid className="h-4 w-4" /> Xonalar</span>, count: rooms.length },
                { value: "sheet", label: <span className="flex items-center gap-1.5"><Table2 className="h-4 w-4" /> Jadval (Excel)</span> },
              ]}
            />
            {canEdit && state.view === "rooms" && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setAddingRoom(true)}>
                Xona qo'shish
              </Button>
            )}
          </div>

          {state.view === "sheet" ? (
            <SheetView sheet={sheet} priceId={p.id} title={title} />
          ) : (
            <>
              {!rooms.length && !loose.length && (
                <Card>
                  <Empty
                    icon={<Sofa className="h-10 w-10" />}
                    title="Hali xona qo'shilmagan"
                    text={canEdit ? "Hisobni xonadan boshlang: oshxona, yotoqxona, sanuzel … Bir xil xonadan bir nechta qo'shish mumkin." : undefined}
                  />
                  {canEdit && (
                    <div className="mt-2">
                      <RoomTypeGrid roomTypes={roomTypes} priceId={p.id} onDone={() => undefined} />
                    </div>
                  )}
                </Card>
              )}
              {rooms.map((room, i) => (
                <RoomCard
                  key={room.id}
                  priceId={p.id}
                  room={room}
                  index={i}
                  roomIds={rooms.map((r) => r.id)}
                  roomType={roomTypes.find((t) => t.id === room.room_type)}
                  objects={objects}
                  calcs={calcs.filter((c) => c.room === room.id)}
                  total={roomTotal(room.id)}
                  canEdit={canEdit}
                  onEdit={(calc, objectType) => setEditing({ calc, objectType, room: room.id })}
                />
              ))}
              {loose.length > 0 && (
                <Card title="📦 Boshqa (xonasiz)" actions={<span className="font-semibold tabular-nums">{usd(roomTotal(null))}</span>} padded={false}>
                  <p className="muted px-5 pb-1 pt-3 text-xs">Xonalar paydo bo'lishidan oldin qilingan hisoblar. Tahrirlab, xonaga o'tkazish mumkin.</p>
                  <CalcList
                    priceId={p.id}
                    calcs={loose}
                    objects={objects}
                    canEdit={canEdit}
                    onEdit={(calc, objectType) => setEditing({ calc, objectType, room: null })}
                  />
                </Card>
              )}
            </>
          )}
        </div>

        {/* ---------------------------------------------------------- side */}
        <div className="space-y-4">
          <Card>
            <div className="muted text-xs font-medium uppercase tracking-wide">Jami</div>
            <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900 dark:text-white">{money(p.price, "$0")}</div>
            {!!sheet?.rooms.length && (
              <ul className="mt-3 space-y-1.5 border-t border-slate-100 pt-3 text-sm dark:border-slate-800">
                {sheet.rooms.map((r) => (
                  <li key={r.id ?? "loose"} className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      {r.icon} {r.name}
                    </span>
                    <span className="font-medium tabular-nums">{usd(r.total)}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="muted mt-3 text-xs">Summa shu o'lchovning buyurtmasiga o'tadi</div>
          </Card>

          <OfferCard price={p} canEdit={canEdit} onPreview={() => setPdfOpen(true)} pdfName={pdfName} />

          {p.metering && (
            <Card title="O'lchov">
              <div className="space-y-1 text-sm">
                <Link to={`/meterings/${p.metering.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
                  {p.metering.client.fio}
                </Link>
                <div><PhoneLink value={p.metering.client.phone} /></div>
                <div className="muted">{p.metering.address}</div>
              </div>
            </Card>
          )}
          {p.order && (
            <Card title={`Buyurtma №${p.order.order_number}`}>
              <div className="flex flex-wrap gap-2">
                <OrderStatusBadge status={p.order.status} label={p.order.status_label} />
                <DeadlinePill deadline={p.order.deadline} />
              </div>
            </Card>
          )}
          <DescCard price={p} canEdit={canEdit} />
        </div>
      </div>

      {editing && (
        <CalculationEditor
          priceId={p.id}
          objectType={editing.objectType}
          calc={editing.calc}
          room={editing.room}
          rooms={rooms}
          onClose={() => setEditing(null)}
        />
      )}
      <Modal open={addingRoom} onClose={() => setAddingRoom(false)} title="Xona qo'shish" size="lg">
        <RoomTypeGrid roomTypes={roomTypes} priceId={p.id} onDone={() => setAddingRoom(false)} withName />
      </Modal>
      {pdfOpen && (
        <Suspense fallback={null}>
          <PdfViewer url={`/prices/${p.id}/pdf/`} name={pdfName} downloadName={pdfName} onClose={() => setPdfOpen(false)} />
        </Suspense>
      )}
      <Confirm
        open={confirmDone}
        onClose={() => setConfirmDone(false)}
        title="Hisob-kitob yakunlansinmi?"
        text="Hisob-kitob «Bajarilgan» bo'limiga o'tadi."
        variant="success"
        loading={done.isPending}
        onConfirm={() => done.mutate()}
      />
    </div>
  );
}

/* =================================================================== add a room */
function RoomTypeGrid({ roomTypes, priceId, onDone, withName }: { roomTypes: RoomType[]; priceId: number; onDone: () => void; withName?: boolean }) {
  const [name, setName] = useState("");
  const add = useAction((room_type: number) => api.post(`/prices/${priceId}/rooms/`, { room_type, name }), {
    success: "Xona qo'shildi",
    invalidate: INV,
    onSuccess: () => {
      setName("");
      onDone();
    },
  });
  if (!roomTypes.length) return <Empty title="Xona turlari yo'q" text="Ularni «Mahsulotlar» bo'limida qo'shing." />;
  return (
    <div className="space-y-4">
      {withName && (
        <Field label="Nomi (ixtiyoriy)" hint="Bo'sh qolsa — xona turi nomi, ikkinchisi «… 2» bo'ladi">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Masalan: Master-spalnya" />
        </Field>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
        {roomTypes.map((t) => (
          <button
            key={t.id}
            disabled={add.isPending}
            onClick={() => add.mutate(t.id)}
            className="flex flex-col items-center gap-1.5 rounded-2xl border border-slate-200 bg-white px-3 py-4 text-sm font-medium transition hover:-translate-y-0.5 hover:border-brand-400 hover:shadow-card disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900"
          >
            <span className="text-3xl leading-none">{t.icon || "🏠"}</span>
            <span className="text-center">{t.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* =================================================================== one room */
function RoomCard({
  priceId,
  room,
  index,
  roomIds,
  roomType,
  objects,
  calcs,
  total,
  canEdit,
  onEdit,
}: {
  priceId: number;
  room: Room;
  index: number;
  roomIds: number[];
  roomType?: RoomType;
  objects: ObjectType[];
  calcs: Calculation[];
  total: number;
  canEdit: boolean;
  onEdit: (calc: Calculation | undefined, objectType: ObjectType) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [askDelete, setAskDelete] = useState(false);
  const [picking, setPicking] = useState(false);
  const base = `/prices/${priceId}/rooms/${room.id}/`;
  const rename = useAction(() => api.patch(base, { name: renaming }), { success: "Saqlandi", invalidate: INV, onSuccess: () => setRenaming(null) });
  const remove = useAction(() => api.delete(base), { success: "Xona o'chirildi", invalidate: INV, onSuccess: () => setAskDelete(false) });
  const move = useAction(
    (dir: -1 | 1) => {
      const ids = [...roomIds];
      const j = index + dir;
      [ids[index], ids[j]] = [ids[j], ids[index]];
      return api.post(`/prices/${priceId}/rooms/reorder/`, { ids });
    },
    { invalidate: INV },
  );
  const allowed = roomType?.object_types.length ? objects.filter((o) => roomType.object_types.includes(o.id)) : objects;

  return (
    <Card padded={false}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3 dark:border-slate-800">
        {renaming !== null ? (
          <form
            className="flex flex-1 items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              rename.mutate();
            }}
          >
            <Input autoFocus value={renaming} onChange={(e) => setRenaming(e.target.value)} className="max-w-xs" />
            <Button size="sm" type="submit" loading={rename.isPending}>Saqlash</Button>
            <Button size="sm" variant="ghost" onClick={() => setRenaming(null)}>Bekor</Button>
          </form>
        ) : (
          <h3 className="flex min-w-0 items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
            <span className="text-2xl leading-none">{room.icon || "🏠"}</span>
            <span className="truncate">{room.name}</span>
            {room.name !== room.room_type_name && <span className="muted text-xs font-normal">{room.room_type_name}</span>}
          </h3>
        )}
        <div className="flex items-center gap-1">
          <span className="mr-2 text-lg font-semibold tabular-nums">{usd(total)}</span>
          {canEdit && renaming === null && (
            <>
              <IconButton label="Yuqoriga" disabled={index === 0} onClick={() => move.mutate(-1)}><ArrowUp className="h-4 w-4" /></IconButton>
              <IconButton label="Pastga" disabled={index === roomIds.length - 1} onClick={() => move.mutate(1)}><ArrowDown className="h-4 w-4" /></IconButton>
              <IconButton label="Nomini o'zgartirish" onClick={() => setRenaming(room.name)}><Pencil className="h-4 w-4" /></IconButton>
              <IconButton label="Xonani o'chirish" onClick={() => setAskDelete(true)}><Trash2 className="h-4 w-4" /></IconButton>
            </>
          )}
        </div>
      </header>

      <RoomImages priceId={priceId} room={room} canEdit={canEdit} />

      <div className="border-t border-slate-100 dark:border-slate-800">
        {!calcs.length && <p className="muted px-5 py-4 text-sm">Bu xonada hali mebel yo'q.</p>}
        <CalcList priceId={priceId} calcs={calcs} objects={objects} canEdit={canEdit} onEdit={onEdit} />
      </div>

      {canEdit && (
        <div className="border-t border-slate-100 px-5 py-3 dark:border-slate-800">
          {picking ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="muted text-xs">Qaysi mebel?</span>
              {allowed.map((o) => (
                <Button
                  key={o.id}
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setPicking(false);
                    onEdit(undefined, o);
                  }}
                >
                  {o.name}
                </Button>
              ))}
              <IconButton label="Yopish" onClick={() => setPicking(false)}><X className="h-4 w-4" /></IconButton>
            </div>
          ) : (
            <Button size="sm" variant="ghost" icon={<Plus className="h-4 w-4" />} onClick={() => (allowed.length === 1 ? onEdit(undefined, allowed[0]) : setPicking(true))}>
              Mebel qo'shish
            </Button>
          )}
        </div>
      )}
      <Confirm
        open={askDelete}
        onClose={() => setAskDelete(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        variant="danger"
        confirmLabel="O'chirish"
        title={`«${room.name}» o'chirilsinmi?`}
        text="Xonadagi barcha mebel hisoblari ham o'chadi, jami summa qayta hisoblanadi. Rasmlar fayllar papkasida qoladi."
      />
    </Card>
  );
}

/* =================================================================== furniture list */
function CalcList({
  priceId,
  calcs,
  objects,
  canEdit,
  onEdit,
}: {
  priceId: number;
  calcs: Calculation[];
  objects: ObjectType[];
  canEdit: boolean;
  onEdit: (calc: Calculation, objectType: ObjectType) => void;
}) {
  const remove = useAction((calcId: number) => api.delete(`/prices/${priceId}/calculations/${calcId}/`), { success: "O'chirildi", invalidate: INV });
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {calcs.map((c) => {
        const obj = objects.find((o) => o.id === c.obj);
        return (
          <li key={c.id} className="group grid gap-2 px-5 py-3 sm:grid-cols-[1fr_auto]">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{c.name}</span>
                {obj && <Badge dot={false}>{obj.name}</Badge>}
                {!!c.count && (
                  <span className="muted text-xs tabular-nums">
                    {num(c.count)} {obj?.count_label}
                  </span>
                )}
              </div>
              {!!c.items.length && (
                <dl className="mt-1.5 grid gap-x-4 gap-y-0.5 text-sm sm:grid-cols-[auto_1fr]">
                  {c.items.map((it) => (
                    <div key={it.id} className="contents">
                      <dt className="muted text-xs leading-5">{it.inventory_type_name}</dt>
                      <dd className="leading-5">
                        {it.inventory_name}
                        {it.count !== 1 && it.count !== c.count && <span className="muted"> × {num(it.count)}</span>}
                        <span className="muted ml-2 text-xs tabular-nums">{money(it.price)}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {c.note && <p className="muted mt-1 text-xs">➕ {c.note}</p>}
            </div>
            <div className="flex items-start justify-end gap-1">
              <span className="mr-1 whitespace-nowrap pt-1 font-semibold tabular-nums">{money(c.amount)}</span>
              {canEdit && obj && (
                <>
                  <IconButton label="Tahrirlash" onClick={() => onEdit(c, obj)}><Pencil className="h-4 w-4" /></IconButton>
                  <IconButton label="O'chirish" onClick={() => confirm(`«${c.name}» o'chirilsinmi?`) && remove.mutate(c.id)}><Trash2 className="h-4 w-4" /></IconButton>
                </>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* =================================================================== room images */
function RoomImages({ priceId, room, canEdit }: { priceId: number; room: Room; canEdit: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<RoomImage | null>(null);
  const upload = useAction(
    (files: File[]) => {
      const form = new FormData();
      files.forEach((f) => form.append("file", f));
      return api.post(`/prices/${priceId}/rooms/${room.id}/images/`, form);
    },
    { success: "Rasm qo'shildi", invalidate: INV },
  );
  const remove = useAction((imageId: number) => api.delete(`/prices/${priceId}/rooms/${room.id}/images/${imageId}/`), { invalidate: INV });
  if (!room.images.length && !canEdit) return null;
  return (
    <div className="px-5 py-3">
      <div className="muted mb-2 text-xs">Rasmlar va chizmalar — PDF'da xona sahifasiga chiqadi</div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {room.images.map((img) => (
          <div key={img.id} className="group relative h-24 w-32 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
            <button className="h-full w-full" onClick={() => setPreview(img)}>
              <Thumb img={img} />
            </button>
            {canEdit && (
              <button
                title="Olib tashlash"
                onClick={() => remove.mutate(img.id)}
                className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition group-hover:opacity-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
        {canEdit && (
          <button
            onClick={() => input.current?.click()}
            disabled={upload.isPending}
            className="flex h-24 w-32 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-slate-300 text-xs text-slate-500 hover:border-brand-400 hover:text-brand-700 dark:border-slate-700"
          >
            {upload.isPending ? <Spinner /> : <ImagePlus className="h-6 w-6" />}
            Rasm qo'shish
          </button>
        )}
        <input
          ref={input}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            // copy first: the FileList is live and clearing the input empties it
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) upload.mutate(files);
          }}
        />
      </div>
      {preview && <ImagePreview img={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function Thumb({ img }: { img: RoomImage }) {
  const [broken, setBroken] = useState(false);
  if (broken || !img.thumbnail)
    return (
      <span className="flex h-full w-full items-center justify-center text-slate-400">
        <ImageOff className="h-6 w-6" />
      </span>
    );
  return <img src={img.thumbnail} alt={img.name} loading="lazy" className="h-full w-full object-cover" onError={() => setBroken(true)} />;
}

function ImagePreview({ img, onClose }: { img: RoomImage; onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    fetchBlob(`/files/${img.file}/`).then(
      (b) => {
        url = URL.createObjectURL(b);
        if (!cancelled) setSrc(url);
      },
      (e) => !cancelled && setError(errorMessage(e)),
    );
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [img.file]);
  return (
    <div className="fixed inset-0 z-[60] flex animate-fade-in items-center justify-center bg-black/80 p-4" onClick={onClose}>
      {error ? (
        <p className="max-w-sm rounded-xl bg-white/10 p-4 text-center text-sm text-rose-200">⚠️ {error}</p>
      ) : src ? (
        <img src={src} className="max-h-full max-w-full rounded-xl" alt={img.name} />
      ) : (
        <Spinner className="h-8 w-8 text-white" />
      )}
    </div>
  );
}

/* =================================================================== the «Excel» view */
function SheetView({ sheet, priceId, title }: { sheet?: OfferSheet; priceId: number; title: string }) {
  if (!sheet) return <PageLoader />;
  const cell = "border border-slate-200 px-3 py-2 align-top dark:border-slate-700";
  return (
    <Card
      padded={false}
      title="Hisob-kitob jadvali"
      actions={
        <Button
          size="sm"
          variant="outline"
          icon={<FileSpreadsheet className="h-4 w-4" />}
          onClick={() => downloadFile(`/prices/${priceId}/excel/`, `${title}.xlsx`).catch((e) => toast.error(errorMessage(e)))}
        >
          Excel yuklab olish
        </Button>
      }
    >
      {!sheet.rooms.length ? (
        <Empty title="Jadval bo'sh" text="Xona va mebel qo'shilgach shu yerda ko'rinadi." />
      ) : (
        <div className="overflow-x-auto p-3">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
                <th className={cell}>Mebel</th>
                <th className={cell}>Parametr</th>
                <th className={cell}>Material</th>
                <th className={cn(cell, "text-right")}>Narx</th>
              </tr>
            </thead>
            <tbody>
              {sheet.rooms.map((r) => (
                <RoomRows key={r.id ?? "loose"} room={r} cell={cell} />
              ))}
              <tr className="bg-brand-700 text-white">
                <td className={cn(cell, "border-brand-700 font-semibold")} colSpan={3}>
                  Umumiy itog{sheet.variant ? ` — ${sheet.variant}` : ""}
                </td>
                <td className={cn(cell, "border-brand-700 text-right text-base font-bold tabular-nums")}>{usd(sheet.total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RoomRows({ room, cell }: { room: OfferSheet["rooms"][number]; cell: string }) {
  return (
    <>
      <tr className="bg-slate-800 text-white dark:bg-slate-700">
        <td className={cn(cell, "border-slate-800 font-semibold")} colSpan={4}>
          {room.icon} {room.name}
        </td>
      </tr>
      {room.items.map((it) => {
        const lines = [...it.params, ...(it.note ? [{ label: "Qo'shimcha", value: it.note }] : [])];
        const rows = lines.length ? lines : [{ label: "", value: "" }];
        return rows.map((ln, i) => (
          <tr key={`${it.id}-${i}`} className={i === 0 ? "border-t-2 border-slate-300 dark:border-slate-600" : undefined}>
            {i === 0 && (
              <td className={cn(cell, "font-semibold")} rowSpan={rows.length}>
                {it.name}
                {it.count_text && <div className="muted text-xs font-normal">{it.count_text}</div>}
              </td>
            )}
            <td className={cn(cell, "muted text-xs")}>{ln.label}</td>
            <td className={cell}>{ln.value}</td>
            {i === 0 && (
              <td className={cn(cell, "text-right font-semibold tabular-nums")} rowSpan={rows.length}>
                {usd(it.amount)}
              </td>
            )}
          </tr>
        ));
      })}
      <tr className="bg-emerald-50 dark:bg-emerald-500/10">
        <td className={cn(cell, "font-semibold text-emerald-700 dark:text-emerald-300")} colSpan={3}>
          Itogo — {room.name}
        </td>
        <td className={cn(cell, "text-right font-bold tabular-nums text-emerald-700 dark:text-emerald-300")}>{usd(room.total)}</td>
      </tr>
    </>
  );
}

/* =================================================================== offer (PDF) */
function OfferCard({ price, canEdit, onPreview, pdfName }: { price: Price; canEdit: boolean; onPreview: () => void; pdfName: string }) {
  const [f, setF] = useState({ client_title: price.client_title, variant: price.variant });
  useEffect(() => setF({ client_title: price.client_title, variant: price.variant }), [price.client_title, price.variant]);
  const dirty = f.client_title !== price.client_title || f.variant !== price.variant;
  const save = useAction(() => api.patch(`/prices/${price.id}/`, f), { success: "Saqlandi", invalidate: INV });
  const [busy, setBusy] = useState(false);
  return (
    <Card title={<span className="flex items-center gap-2"><FileText className="h-4 w-4 text-slate-400" /> Tijorat taklifi (PDF)</span>}>
      <div className="space-y-3">
        <Field label="Murojaat" hint="«Хурматли …» dan keyin. Bo'sh — mijoz ismi">
          <Input disabled={!canEdit} value={f.client_title} placeholder={price.metering?.client.fio ?? "Зилола опа"} onChange={(e) => setF({ ...f, client_title: e.target.value })} />
        </Field>
        <Field label="Variant" hint="Itog sahifasida chiqadi, masalan «Премиум»">
          <Input disabled={!canEdit} value={f.variant} placeholder="—" onChange={(e) => setF({ ...f, variant: e.target.value })} />
        </Field>
        {dirty && (
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
            Saqlash
          </Button>
        )}
        <div className="grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <Button variant="outline" icon={<Eye className="h-4 w-4" />} disabled={dirty} onClick={onPreview}>
            Ko'rish
          </Button>
          <Button
            icon={<Download className="h-4 w-4" />}
            loading={busy}
            disabled={dirty}
            onClick={() => {
              setBusy(true);
              downloadFile(`/prices/${price.id}/pdf/`, pdfName)
                .catch((e) => toast.error(errorMessage(e)))
                .finally(() => setBusy(false));
            }}
          >
            PDF
          </Button>
        </div>
        {dirty && <p className="muted text-xs">Avval o'zgarishni saqlang.</p>}
      </div>
    </Card>
  );
}

function DescCard({ price, canEdit }: { price: Price; canEdit: boolean }) {
  const [draft, setDraft] = useState<string | null>(null);
  const save = useAction(() => api.patch(`/prices/${price.id}/`, { desc: draft }), { success: "Saqlandi", invalidate: INV, onSuccess: () => setDraft(null) });
  return (
    <Card title="Tavsif">
      <Textarea disabled={!canEdit} value={draft ?? price.desc ?? ""} onChange={(e) => setDraft(e.target.value)} />
      {draft !== null && (
        <Button className="mt-3" size="sm" loading={save.isPending} onClick={() => save.mutate()}>
          Saqlash
        </Button>
      )}
    </Card>
  );
}

/* =================================================================== furniture editor */
type Line = { inventory: string; count: string };

function CalculationEditor({
  priceId,
  objectType,
  calc,
  room,
  rooms,
  onClose,
}: {
  priceId: number;
  objectType: ObjectType;
  calc?: Calculation;
  room: number | null;
  rooms: Room[];
  onClose: () => void;
}) {
  const { data: types } = useAll<InventoryType>("inventory-types", { obj: objectType.id });
  const [name, setName] = useState(calc?.name ?? objectType.name);
  const [count, setCount] = useState(calc?.count != null ? String(calc.count) : "");
  const [note, setNote] = useState(calc?.note ?? "");
  const [roomId, setRoomId] = useState(room !== null ? String(room) : "");
  const [lines, setLines] = useState<Record<number, Line>>(() => {
    const init: Record<number, Line> = {};
    calc?.items.forEach((it) => (init[it.inventory_type] = { inventory: String(it.inventory), count: String(it.count) }));
    return init;
  });

  const total = useMemo(() => {
    if (!types) return 0;
    return types.reduce((sum, t) => {
      const line = lines[t.id];
      const inv = t.inventories.find((i) => String(i.id) === line?.inventory);
      if (!inv?.price) return sum;
      const qty = t.type === 1 ? Number(count || 0) : Number(line?.count || 0);
      return sum + qty * inv.price.amount;
    }, 0);
  }, [types, lines, count]);

  const save = useAction(
    () => {
      const body = {
        name,
        count: Number(count || 0),
        object_type: objectType.id,
        room: roomId ? Number(roomId) : null,
        note,
        items: (types ?? []).map((t) => ({
          inventory_type: t.id,
          inventory: lines[t.id]?.inventory ? Number(lines[t.id].inventory) : null,
          count: t.type === 2 ? Number(lines[t.id]?.count || 0) : null,
        })),
      };
      return calc ? api.patch(`/prices/${priceId}/calculations/${calc.id}/`, body) : api.post(`/prices/${priceId}/calculations/`, body);
    },
    { success: "Saqlandi", invalidate: INV, onSuccess: onClose },
  );

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={`${calc ? "Mebelni tahrirlash" : "Yangi mebel"} · ${objectType.name}`}
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <div className="text-sm">
            Narx: <b className="text-lg tabular-nums">{usd(total)}</b>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
            <Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>Saqlash</Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Nomi (PDF'da shunday chiqadi)">
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Под ТВ" />
        </Field>
        <Field label={objectType.count_label}>
          <Input type="number" inputMode="decimal" value={count} onChange={(e) => setCount(e.target.value)} />
        </Field>
        <Field label="Xona">
          <Select value={roomId} onChange={(e) => setRoomId(e.target.value)}>
            <option value="">— xonasiz —</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.icon} {r.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="mt-5 space-y-3">
        {!types && <PageLoader />}
        {types?.map((t) => {
          const line = lines[t.id] ?? { inventory: "", count: "" };
          const inv = t.inventories.find((i) => String(i.id) === line.inventory);
          const qty = t.type === 1 ? Number(count || 0) : Number(line.count || 0);
          return (
            <div key={t.id} className="grid items-end gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-700 sm:grid-cols-[1fr_120px_110px]">
              <Field label={t.name}>
                <Select value={line.inventory} onChange={(e) => setLines({ ...lines, [t.id]: { ...line, inventory: e.target.value } })}>
                  <option value="">— tanlanmagan —</option>
                  {t.inventories.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} — {money(i.price)}
                    </option>
                  ))}
                </Select>
              </Field>
              {t.type === 2 ? (
                <Field label="Soni">
                  <Input type="number" inputMode="decimal" value={line.count} onChange={(e) => setLines({ ...lines, [t.id]: { ...line, count: e.target.value } })} />
                </Field>
              ) : (
                <div className="muted pb-2 text-xs">× {objectType.count_label}</div>
              )}
              <div className="pb-2 text-right text-sm font-medium tabular-nums">{inv?.price ? money({ amount: qty * inv.price.amount, currency: inv.price.currency }) : "—"}</div>
            </div>
          );
        })}
        {types && !types.length && <Empty title="Bu mebel uchun parametrlar yo'q" text="Ularni «Mahsulotlar» bo'limida qo'shing." />}
        <Field label="Qo'shimcha (PDF'da «Допол.» bo'lib chiqadi)" hint="Masalan: подсветка, зеркало + пуфик">
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
