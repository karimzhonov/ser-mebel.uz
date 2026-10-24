import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Folder as FolderIcon,
  FolderOpen,
  FolderPlus,
  MapPin,
  MessageSquare,
  Phone,
  Send,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/api/client";
import { useAction, useGet, useMeta } from "@/api/hooks";
import type { Deadline, Folder, FolderFile, Message, Tone } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { cn } from "@/lib/cn";
import { dateTime, fileSize, phone, relative } from "@/lib/format";
import { Badge, Button, Empty, IconButton, Input, Modal, Spinner, Textarea } from "./ui";

export function OrderStatusBadge({ status, label }: { status: string; label?: string }) {
  const { data: meta } = useMeta();
  const item = meta?.order_statuses.find((s) => s.value === status);
  return <Badge tone={item?.tone ?? "idle"}>{label ?? item?.label ?? status}</Badge>;
}

export function MeteringStatusBadge({ status, label }: { status: string; label?: string }) {
  const { data: meta } = useMeta();
  const item = meta?.metering_statuses.find((s) => s.value === status);
  return <Badge tone={item?.tone ?? "idle"}>{label ?? item?.label ?? status}</Badge>;
}

export function SolutionBadge({ solution, label }: { solution: number | null; label?: string | null }) {
  const { data: meta } = useMeta();
  if (solution === null || solution === undefined) return <Badge tone="primary">Yangi</Badge>;
  const item = meta?.solutions.find((s) => s.value === solution);
  return <Badge tone={item?.tone ?? "idle"}>{label ?? item?.label ?? solution}</Badge>;
}

export function DeadlinePill({ deadline }: { deadline: Deadline }) {
  return (
    <Badge tone={deadline.level} dot={false} className="tabular-nums">
      {deadline.text}
    </Badge>
  );
}

export const ROW_TONE: Partial<Record<Tone, string>> = {
  danger: "bg-rose-50/60 dark:bg-rose-500/[.06]",
  warn: "bg-amber-50/60 dark:bg-amber-500/[.06]",
};

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="muted mb-2 inline-flex items-center gap-1 text-sm hover:text-slate-800 dark:hover:text-slate-200"
    >
      <ArrowLeft className="h-4 w-4" /> {children}
    </Link>
  );
}

export function PhoneLink({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return (
    <a
      href={`tel:${value}`}
      onClick={(e) => e.stopPropagation()}
      className="inline-flex items-center gap-1 whitespace-nowrap text-brand-700 hover:underline dark:text-brand-300"
    >
      <Phone className="h-3.5 w-3.5" />
      {phone(value)}
    </a>
  );
}

export function AddressLink({ address, link }: { address: string | null | undefined; link?: string | null }) {
  if (!address && !link) return <span className="muted">—</span>;
  return (
    <span className="inline-flex items-center gap-1">
      <MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      <span>{address || "—"}</span>
      {link && (
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="ml-1 text-brand-700 hover:underline dark:text-brand-300"
          title="Xaritani ochish"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </span>
  );
}

/* ---------------------------------------------------------------- Charts */

export function TimelineChart({
  data,
  height = 220,
  valueFormatter = (v: number) => String(v),
}: {
  data: { date: string; value: number }[] | undefined;
  height?: number;
  valueFormatter?: (v: number) => string;
}) {
  if (!data?.length) return <Empty title="Davr uchun ma'lumot yo'q" />;
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="fillBrand" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1f747d" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#1f747d" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-800" vertical={false} />
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            fontSize={11}
            stroke="currentColor"
            className="text-slate-400"
            tickFormatter={(d: string) => (d ? d.slice(5).split("-").reverse().join(".") : "")}
            minTickGap={24}
          />
          <YAxis tickLine={false} axisLine={false} fontSize={11} stroke="currentColor" className="text-slate-400" allowDecimals={false} />
          <Tooltip
            formatter={(v: number) => [valueFormatter(v), ""]}
            labelFormatter={(d: string) => d}
            contentStyle={{ borderRadius: 12, border: "1px solid rgb(226 232 240)", fontSize: 12 }}
          />
          <Area type="monotone" dataKey="value" stroke="#1f747d" strokeWidth={2} fill="url(#fillBrand)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ShareBars({ rows }: { rows: { label: string; value: number; display: string; tone?: Tone }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <Empty title="Ma'lumot yo'q" />;
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="mb-1 flex justify-between gap-2 text-sm">
            <span className="truncate">{r.label}</span>
            <span className="font-medium tabular-nums">{r.display}</span>
          </div>
          <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-2 rounded-full bg-brand-500" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* --------------------------------------------------------- File browser */

/** Files saved before the upload fix may have no extension ("pdf (3)") and don't open
 * in the browser; the API then sends `download_name` (".pdf" added from the file's own
 * bytes) and the file is downloaded under that name instead of opened. */
function fileLinkProps(f: FolderFile) {
  if (f.download_name) return { download: f.download_name };
  return { target: "_blank", rel: "noreferrer" };
}

export function FolderButton({ folderId, label = "Fayllar" }: { folderId: number | null | undefined; label?: string }) {
  const [open, setOpen] = useState(false);
  if (!folderId) return null;
  return (
    <>
      <Button variant="outline" size="sm" icon={<FolderOpen className="h-4 w-4" />} onClick={() => setOpen(true)}>
        {label}
      </Button>
      {open && <FolderModal folderId={folderId} onClose={() => setOpen(false)} />}
    </>
  );
}

export function FolderModal({ folderId, onClose }: { folderId: number; onClose: () => void }) {
  const [current, setCurrent] = useState(folderId);
  return (
    <Modal open onClose={onClose} title="Fayllar" size="xl">
      <FolderBrowser folderId={current} onNavigate={setCurrent} />
    </Modal>
  );
}

export function FolderBrowser({
  folderId,
  onNavigate,
}: {
  folderId: number;
  onNavigate: (id: number) => void;
}) {
  const { can } = useAuth();
  const { data, isLoading, refetch } = useGet<Folder>(`/folders/${folderId}/`);
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("file", f));
    setUploading(true);
    try {
      await api.post(`/folders/${folderId}/`, form);
      toast.success(`Yuklandi: ${files.length}`);
      refetch();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const removeFile = useAction((id: number) => api.delete(`/files/${id}/`), {
    success: "Fayl o'chirildi",
    invalidate: [`/folders/${folderId}/`],
  });

  async function createFolder() {
    if (!newFolder?.trim()) return;
    try {
      await api.post(`/folders/${folderId}/`, { name: newFolder.trim() });
      setNewFolder(null);
      refetch();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (isLoading || !data) return <div className="py-10 text-center"><Spinner /></div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <nav className="flex flex-wrap items-center gap-1 text-sm">
          {data.breadcrumbs.map((b, i) => (
            <span key={b.id} className="flex items-center gap-1">
              {i > 0 && <span className="text-slate-300">/</span>}
              <button
                onClick={() => onNavigate(b.id)}
                className={cn(
                  "rounded-md px-1.5 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800",
                  b.id === data.id && "font-semibold",
                )}
              >
                {b.name}
              </button>
            </span>
          ))}
        </nav>
        <div className="flex gap-2">
          {can("filer.add_folder") && (
            <Button size="sm" variant="outline" icon={<FolderPlus className="h-4 w-4" />} onClick={() => setNewFolder("")}>
              Papka
            </Button>
          )}
          {can("filer.add_file") && (
            <>
              <input ref={inputRef} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
              <Button size="sm" icon={<Upload className="h-4 w-4" />} loading={uploading} onClick={() => inputRef.current?.click()}>
                Yuklash
              </Button>
            </>
          )}
        </div>
      </div>

      {newFolder !== null && (
        <div className="flex gap-2">
          <Input autoFocus placeholder="Papka nomi" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} onKeyDown={(e) => e.key === "Enter" && createFolder()} />
          <Button onClick={createFolder}>Yaratish</Button>
          <Button variant="ghost" onClick={() => setNewFolder(null)}>Bekor qilish</Button>
        </div>
      )}

      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (can("filer.add_file")) upload(e.dataTransfer.files);
        }}
      >
        {data.folders.map((f) => (
          <button
            key={f.id}
            onClick={() => onNavigate(f.id)}
            className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 hover:bg-brand-50/40 dark:border-slate-700 dark:hover:bg-brand-500/5"
          >
            <FolderIcon className="h-8 w-8 shrink-0 fill-amber-200 text-amber-500" />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{f.name}</div>
              <div className="muted text-xs">{f.file_count} ta fayl</div>
            </div>
          </button>
        ))}
        {data.files.map((f) => (
          <div key={f.id} className="group relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
            {f.is_image ? (
              <button className="block aspect-[4/3] w-full bg-slate-100 dark:bg-slate-800" onClick={() => setPreview(f.url)}>
                <img src={f.thumbnail || f.url} alt={f.name} loading="lazy" className="h-full w-full object-cover" />
              </button>
            ) : (
              <a href={f.url} {...fileLinkProps(f)} className="flex aspect-[4/3] items-center justify-center bg-slate-50 dark:bg-slate-800/60">
                <FileText className="h-10 w-10 text-slate-400" />
              </a>
            )}
            <div className="flex items-center justify-between gap-1 p-2">
              <a href={f.url} {...fileLinkProps(f)} className="min-w-0">
                <div className="truncate text-xs font-medium">{f.name}</div>
                <div className="muted text-[11px]">{fileSize(f.size)} · {relative(f.uploaded_at)}</div>
              </a>
              {can("filer.delete_file") && (
                <IconButton
                  label="O'chirish"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100"
                  onClick={() => confirm(`«${f.name}» o'chirilsinmi?`) && removeFile.mutate(f.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </IconButton>
              )}
            </div>
          </div>
        ))}
      </div>
      {!data.folders.length && !data.files.length && (
        <Empty title="Papka bo'sh" text={can("filer.add_file") ? "Fayllarni shu yerga tashlang yoki «Yuklash» tugmasini bosing." : undefined} />
      )}

      <FolderChat folderId={data.id} />

      {preview && (
        <div className="fixed inset-0 z-[60] flex animate-fade-in items-center justify-center bg-black/80 p-4" onClick={() => setPreview(null)}>
          <img src={preview} className="max-h-full max-w-full rounded-xl" alt="" />
        </div>
      )}
    </div>
  );
}

function FolderChat({ folderId }: { folderId: number }) {
  const { data, refetch } = useGet<Message[]>(`/folders/${folderId}/messages/`);
  const [text, setText] = useState("");
  const send = useAction(
    () => api.post(`/folders/${folderId}/messages/`, { message: text }),
    { onSuccess: () => { setText(""); refetch(); } },
  );
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5 text-sm font-medium dark:border-slate-800">
        <MessageSquare className="h-4 w-4 text-slate-400" /> Muhokama
      </div>
      <div className="max-h-64 space-y-3 overflow-y-auto px-4 py-3">
        {!data?.length && <p className="muted text-sm">Hozircha xabarlar yo'q.</p>}
        {data?.map((m) => (
          <div key={m.id} className="text-sm">
            <div className="flex items-baseline gap-2">
              <span className="font-medium">{m.author.name || phone(m.author.phone)}</span>
              <span className="muted text-xs">{dateTime(m.created_at)}</span>
            </div>
            <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-300">{m.message}</p>
          </div>
        ))}
      </div>
      <div className="flex gap-2 border-t border-slate-100 p-3 dark:border-slate-800">
        <Textarea
          rows={1}
          className="min-h-[40px]"
          placeholder="Xabar yozing…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && text.trim()) {
              e.preventDefault();
              send.mutate();
            }
          }}
        />
        <Button icon={<Send className="h-4 w-4" />} disabled={!text.trim()} loading={send.isPending} onClick={() => send.mutate()} />
      </div>
    </div>
  );
}
