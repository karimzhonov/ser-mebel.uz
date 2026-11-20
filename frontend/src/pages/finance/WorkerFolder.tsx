import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, FileText, Image as ImageIcon, Paperclip, Trash2, Upload } from "lucide-react";
import { api, downloadFile, errorMessage, fieldErrors } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { Badge, Button, Card, Empty, Field, IconButton, Input, Modal, Select, Skeleton, Textarea } from "@/components/ui";
import { cn } from "@/lib/cn";
import { date } from "@/lib/format";
import { som } from "./shared";
import type { WorkerCard, WorkerFile, WorkerFileKind, WorkerMonth, WorkerProfile } from "./types";

/* «👷 Ishchi kartasi» → the worker's own folder: month-by-month salaries with the
 * salary sheets (past months uploaded by hand too), personal data (pasport, prava,
 * ish staji) and every file. Reading needs «every wallet» like the card; writing also
 * accounting.change_worker (the same rule is enforced by the API). */

const MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"];
const KINDS: { value: WorkerFileKind; label: string }[] = [
  { value: "salary", label: "🧾 Oylik varaqasi" },
  { value: "passport", label: "🪪 Pasport" },
  { value: "license", label: "🚗 Prava" },
  { value: "contract", label: "📄 Shartnoma" },
  { value: "other", label: "📎 Boshqa" },
];
const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.doc,.docx,.xls,.xlsx";
// local time, not UTC: in Tashkent the 1st begins 5 hours before UTC's
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export function monthLabel(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS[m - 1] ?? ym} ${y}`;
}

function staj(months: number) {
  const y = Math.floor(months / 12);
  const m = months % 12;
  if (!y && !m) return "—";
  return [y && `${y} yil`, m && `${m} oy`].filter(Boolean).join(" ");
}

function kb(size: number) {
  return size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
}

/** Until when a document is valid: red when expired, amber within 30 days. */
function Expiry({ value }: { value: string | null }) {
  if (!value) return null;
  const days = Math.floor((new Date(value).getTime() - Date.now()) / 86400000);
  if (days < 0) return <Badge tone="danger">muddati o'tgan</Badge>;
  if (days <= 30) return <Badge tone="warn">{days} kun qoldi</Badge>;
  return null;
}

/* ------------------------------------------------------------------ files */
function useFileActions(workerId: number) {
  const [busy, setBusy] = useState<number | null>(null);
  const remove = useAction((id: number) => api.delete(`/finance/workers/${workerId}/files/${id}/`), {
    success: "Fayl o'chirildi",
    invalidate: ["/finance/workers/"],
  });
  const download = async (f: WorkerFile) => {
    setBusy(f.id);
    try {
      await downloadFile(`/finance/workers/${workerId}/files/${f.id}/`, f.name);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  return { busy, download, remove };
}

function FileChips({ workerId, files, canEdit }: { workerId: number; files: WorkerFile[]; canEdit: boolean }) {
  const { busy, download, remove } = useFileActions(workerId);
  if (!files.length) return <span className="muted text-xs">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {files.map((f) => (
        <span key={f.id} className="inline-flex max-w-full items-center gap-1 rounded-lg border border-slate-200 bg-white pl-2 text-xs dark:border-slate-700 dark:bg-slate-900">
          <button className="flex min-w-0 items-center gap-1 py-1 hover:text-brand-600" title={f.comment || f.name} onClick={() => download(f)} disabled={busy === f.id}>
            <Download className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{f.name}</span>
          </button>
          {canEdit && (
            <button className="px-1.5 py-1 text-slate-400 hover:text-rose-600" title="O'chirish" onClick={() => confirm(`«${f.name}» o'chirilsinmi?`) && remove.mutate(f.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

export function UploadModal({
  workerId,
  kind: initialKind = "salary",
  month: initialMonth = "",
  lockKind = false,
  onClose,
}: {
  workerId: number;
  kind?: WorkerFileKind;
  month?: string;
  lockKind?: boolean;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<WorkerFileKind>(initialKind);
  const [month, setMonth] = useState(initialMonth || thisMonth());
  const [comment, setComment] = useState("");
  const [picked, setPicked] = useState<File[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAction(
    async () => {
      for (const file of picked) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("kind", kind);
        if (kind === "salary") fd.append("month", month);
        if (comment) fd.append("comment", comment);
        await api.post(`/finance/workers/${workerId}/files/`, fd);
        // a retry after a failure must not upload the saved ones again
        setPicked((rest) => rest.filter((x) => x !== file));
      }
    },
    { success: "Papkaga saqlandi", invalidate: ["/finance/workers/"], onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title="📁 Papkaga fayl yuklash"
      footer={
        <Button icon={<Upload className="h-4 w-4" />} disabled={!picked.length || (kind === "salary" && !month)} loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
          Saqlash
        </Button>
      }
    >
      <div className="space-y-3">
        {!lockKind && (
          <Field label="Turi" error={errors.kind}>
            <Select value={kind} onChange={(e) => setKind(e.target.value as WorkerFileKind)}>
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {kind === "salary" && (
          <Field label="Qaysi oyning oyligi" hint="O'tgan oylarni ham yuklash mumkin" error={errors.month}>
            <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </Field>
        )}
        <Field label="Fayl(lar)" hint={picked.length ? `Tanlangan: ${picked.length} ta` : "PDF, rasm, Word yoki Excel — 10 MB gacha"} error={errors.file}>
          <Input type="file" multiple accept={ACCEPT} onChange={(e) => setPicked(Array.from(e.target.files ?? []))} />
        </Field>
        <Field label="Izoh">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder={kind === "salary" ? "Imzolangan vedomost" : ""} />
        </Field>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ month by month */
export function WorkerMonths({ card }: { card: WorkerCard }) {
  const { can } = useAuth();
  const id = card.worker_id!;
  const canEdit = can("accounting.change_worker");
  const { data, isLoading } = useGet<WorkerMonth[]>(`/finance/workers/${id}/months/`);
  const [upload, setUpload] = useState<string | null>(null);
  const withHome = card.is_boss || !!data?.some((m) => m.home);
  const cell = "whitespace-nowrap border-b border-slate-100 px-3 py-2 dark:border-slate-800";
  return (
    <Card
      title="📅 Oyma-oy oyliklar (barcha davr)"
      padded={false}
      className="overflow-hidden"
      actions={
        canEdit && (
          <Button size="sm" icon={<Upload className="h-4 w-4" />} onClick={() => setUpload("")}>
            Oylik varaqasi yuklash
          </Button>
        )
      }
    >
      {upload !== null && <UploadModal workerId={id} kind="salary" month={upload} lockKind onClose={() => setUpload(null)} />}
      {isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
        </div>
      ) : !data?.length ? (
        <Empty title="Hali oylik yo'q" text="Bot orqali berilgan avans / oyliklar shu yerda oyma-oy saqlanadi. Eski oylarning varaqasini «Oylik varaqasi yuklash» bilan qo'shing." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500 dark:bg-slate-900/60">
              <tr>
                <th className={cell}>Oylik oyi</th>
                <th className={cn(cell, "text-right")}>💵 Avans</th>
                <th className={cn(cell, "text-right")}>🧾 Oylik</th>
                {withHome && <th className={cn(cell, "text-right")}>🏠 Uy uchun</th>}
                <th className={cn(cell, "text-right")}>💰 Jami</th>
                <th className={cell}>Oylik varaqasi</th>
                {canEdit && <th className={cell} />}
              </tr>
            </thead>
            <tbody>
              {data.map((m) => (
                <tr key={m.month} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                  <td className={cn(cell, "font-medium")}>{monthLabel(m.month)}</td>
                  <td className={cn(cell, "text-right tabular-nums")}>{m.advance ? som(m.advance).replace(" so'm", "") : "—"}</td>
                  <td className={cn(cell, "text-right tabular-nums")}>{m.salary ? som(m.salary).replace(" so'm", "") : "—"}</td>
                  {withHome && <td className={cn(cell, "text-right tabular-nums")}>{m.home ? som(m.home).replace(" so'm", "") : "—"}</td>}
                  <td className={cn(cell, "text-right font-semibold tabular-nums")}>
                    {m.total ? som(m.total).replace(" so'm", "") : "—"}
                    {m.other > 0 && <div className="muted text-[11px] font-normal">turi yozilmagan: {som(m.other).replace(" so'm", "")}</div>}
                  </td>
                  <td className={cn(cell, "min-w-[180px] whitespace-normal")}>
                    <FileChips workerId={id} files={m.files} canEdit={canEdit} />
                  </td>
                  {canEdit && (
                    <td className={cn(cell, "w-10")}>
                      <IconButton label="Shu oy varaqasini yuklash" onClick={() => setUpload(m.month)}>
                        <Paperclip className="h-4 w-4" />
                      </IconButton>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted border-t border-slate-100 px-4 py-2 text-xs dark:border-slate-800">
        Summalar — shu oy oyligi hisobiga berilgan to'lovlar (oylik kuni bo'yicha, «Oylik chiqarish» davri bilan bir xil). Varaqa — shu oy uchun yuklangan oylik hisob fayli.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ personal data */
type ProfileForm = Omit<WorkerProfile, "experience" | "prior_experience_months"> & { prior_years: string; prior_months: string };

function toForm(p: WorkerProfile): ProfileForm {
  const { experience: _e, prior_experience_months: prior, ...rest } = p;
  return { ...rest, prior_years: prior >= 12 ? String(Math.floor(prior / 12)) : "", prior_months: prior % 12 ? String(prior % 12) : "" };
}

export function WorkerProfilePanel({ card }: { card: WorkerCard }) {
  const { can } = useAuth();
  const id = card.worker_id!;
  const canEdit = can("accounting.change_worker");
  const { data, isLoading } = useGet<WorkerProfile>(`/finance/workers/${id}/profile/`);
  const { data: files } = useGet<WorkerFile[]>(`/finance/workers/${id}/files/`);
  const [f, setF] = useState<ProfileForm | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [upload, setUpload] = useState<WorkerFileKind | null>(null);
  useEffect(() => {
    if (data) setF(toForm(data));
  }, [data]);
  const save = useAction(
    () => {
      const { prior_years, prior_months, ...rest } = f!;
      const body: Record<string, unknown> = { ...rest, prior_experience_months: Number(prior_years || 0) * 12 + Number(prior_months || 0) };
      for (const k of ["birth_date", "passport_issued_on", "passport_expires", "license_expires", "hired_on"]) body[k] = body[k] || null;
      return api.patch(`/finance/workers/${id}/profile/`, body);
    },
    { success: "Ma'lumotlar saqlandi", invalidate: ["/finance/workers/"], onSuccess: () => setErrors({}) },
  );
  if (isLoading || !f || !data) return <Skeleton className="h-64" />;
  const input = (key: keyof ProfileForm, props: Record<string, unknown> = {}) => (
    <Input value={(f[key] as string | null) ?? ""} disabled={!canEdit} onChange={(e) => setF({ ...f, [key]: e.target.value })} {...props} />
  );
  const docs = (kind: WorkerFileKind) => (
    <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
      <FileChips workerId={id} files={(files ?? []).filter((x) => x.kind === kind)} canEdit={canEdit} />
      {canEdit && (
        <Button size="sm" variant="outline" icon={<Upload className="h-4 w-4" />} onClick={() => setUpload(kind)}>
          Nusxasini yuklash
        </Button>
      )}
    </div>
  );
  return (
    <div className="space-y-4">
      {upload && <UploadModal workerId={id} kind={upload} lockKind onClose={() => setUpload(null)} />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="👤 Shaxsiy ma'lumotlar">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Tug'ilgan sana" error={errors.birth_date}>{input("birth_date", { type: "date" })}</Field>
            <Field label="Telefon" error={errors.phone}>{input("phone", { placeholder: "+998 90 123 45 67" })}</Field>
            <Field label="Manzil" className="sm:col-span-2" error={errors.address}>{input("address")}</Field>
          </div>
        </Card>
        <Card title="🧭 Ish staji">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Ishga kirgan sana" hint={`Bizda: ${staj(data.experience.here)}`} error={errors.hired_on}>{input("hired_on", { type: "date" })}</Field>
            <Field label="Oldingi staj (boshqa joyda)" error={errors.prior_experience_months}>
              <div className="flex gap-2">
                {input("prior_years", { type: "number", min: 0, placeholder: "yil" })}
                {input("prior_months", { type: "number", min: 0, max: 11, placeholder: "oy" })}
              </div>
            </Field>
            <div className="sm:col-span-2">
              <Badge tone="primary">Umumiy staj: {staj(data.experience.total)}</Badge>
            </div>
            <Field label="Oldingi ish joylari / izoh" className="sm:col-span-2" error={errors.experience_note}>
              <Textarea value={f.experience_note} disabled={!canEdit} onChange={(e) => setF({ ...f, experience_note: e.target.value })} placeholder="2018–2022 «Mebel-X» — yig'uvchi" />
            </Field>
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-2">🪪 Pasport <Expiry value={data.passport_expires} /></span>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Seriya va raqam" error={errors.passport_number}>{input("passport_number", { placeholder: "AA 1234567" })}</Field>
            <Field label="JShShIR (PINFL)" error={errors.pinfl}>{input("pinfl", { inputMode: "numeric", maxLength: 14, placeholder: "14 ta raqam" })}</Field>
            <Field label="Kim tomonidan berilgan" className="sm:col-span-2" error={errors.passport_issued_by}>{input("passport_issued_by")}</Field>
            <Field label="Berilgan sana" error={errors.passport_issued_on}>{input("passport_issued_on", { type: "date" })}</Field>
            <Field label="Amal qilish muddati" error={errors.passport_expires}>{input("passport_expires", { type: "date" })}</Field>
            {docs("passport")}
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-2">🚗 Haydovchilik guvohnomasi (prava) <Expiry value={data.license_expires} /></span>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Raqami" error={errors.license_number}>{input("license_number", { placeholder: "AF 1234567" })}</Field>
            <Field label="Toifalari" error={errors.license_categories}>{input("license_categories", { placeholder: "B, C" })}</Field>
            <Field label="Amal qilish muddati" error={errors.license_expires}>{input("license_expires", { type: "date" })}</Field>
            {docs("license")}
          </div>
        </Card>
      </div>
      {canEdit && (
        <div className="flex justify-end">
          <Button loading={save.isPending} onClick={() => save.mutateAsync().catch((e) => setErrors(fieldErrors(e)))}>
            Saqlash
          </Button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ every file */
export function WorkerFiles({ card }: { card: WorkerCard }) {
  const { can } = useAuth();
  const id = card.worker_id!;
  const canEdit = can("accounting.change_worker");
  const { data, isLoading } = useGet<WorkerFile[]>(`/finance/workers/${id}/files/`);
  const { busy, download, remove } = useFileActions(id);
  const [upload, setUpload] = useState(false);
  return (
    <Card
      title="📁 Ishchi papkasi"
      padded={false}
      className="overflow-hidden"
      actions={
        canEdit && (
          <Button size="sm" icon={<Upload className="h-4 w-4" />} onClick={() => setUpload(true)}>
            Fayl yuklash
          </Button>
        )
      }
    >
      {upload && <UploadModal workerId={id} kind="other" onClose={() => setUpload(false)} />}
      {isLoading ? (
        <Skeleton className="m-4 h-24" />
      ) : !data?.length ? (
        <Empty title="Papka bo'sh" text="Pasport, prava nusxalari, shartnoma va oylik varaqalarini shu yerga yuklang." />
      ) : (
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {KINDS.map((k) => {
            const items = data.filter((x) => x.kind === k.value);
            if (!items.length) return null;
            return (
              <div key={k.value} className="p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {k.label} · {items.length}
                </div>
                <ul className="space-y-1">
                  {items.map((x) => (
                    <li key={x.id} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/40">
                      {x.content_type.startsWith("image/") ? <ImageIcon className="h-4 w-4 shrink-0 text-slate-400" /> : <FileText className="h-4 w-4 shrink-0 text-slate-400" />}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{x.name}</div>
                        <div className="muted truncate text-xs">
                          {[x.month && monthLabel(x.month), x.comment, kb(x.size), date(x.uploaded_at), x.uploaded_by].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                      <IconButton label="Yuklab olish" onClick={() => download(x)} disabled={busy === x.id}>
                        <Download className="h-4 w-4" />
                      </IconButton>
                      {canEdit && (
                        <IconButton label="O'chirish" onClick={() => confirm(`«${x.name}» o'chirilsinmi?`) && remove.mutate(x.id)}>
                          <Trash2 className="h-4 w-4" />
                        </IconButton>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
