import { useEffect, useRef, useState } from "react";
import { AlertCircle, Brush, Calculator, Camera, CheckCircle2, FileText, Loader2, RotateCw, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage, fieldErrors, refreshNow } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { FolderFile, Metering, MeteringAssignees, MeteringNextStep, UserShort } from "@/api/types";
import { FolderButton } from "@/components/domain";
import { Button, Card, Field, Input, Select, Spinner, Textarea } from "@/components/ui";
import { cn } from "@/lib/cn";
import { fileSize, phone, toLocalInput } from "@/lib/format";
import { MAX_UPLOAD_MB, METERING_INVALIDATE, NEXT_STEP_LABEL } from "./actions";

type UploadRow = {
  key: string;
  name: string;
  size: number;
  progress: number;
  state: "queued" | "uploading" | "done" | "error";
  error?: string;
  /** over the size limit — retrying won't help */
  tooBig?: boolean;
};

const ACCEPT = "image/*,video/*,application/pdf";
/** above this size the access token is refreshed right before sending */
const BIG_UPLOAD = 50 * 1024 * 1024;

function asRows(data: unknown): FolderFile[] {
  if (Array.isArray(data)) return data as FolderFile[];
  const d = data as { files?: FolderFile[]; results?: FolderFile[] } | null;
  return d?.files ?? d?.results ?? [];
}

/** «Natija»: after measuring, the measurer uploads photos / videos / PDFs (one file per
 * request, one after another, with progress), writes what they saw and hands the zamer on
 * to the designer and/or the pricer. */
export function MeteringResultCard({ metering, id }: { metering: Metering; id?: string }) {
  const a = metering.actions ?? {};
  const files = useGet<unknown>(`/meterings/${metering.id}/files/`);
  const rows = asRows(files.data);
  const [queue, setQueue] = useState<UploadRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  // don't lose a half-sent video by closing the tab
  useEffect(() => {
    if (!busy) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  const patch = (key: string, p: Partial<UploadRow>) => setQueue((q) => q.map((r) => (r.key === key ? { ...r, ...p } : r)));

  // the picked File of each row, so a failed one can be re-sent without picking it again
  const fileOf = useRef(new Map<string, File>());

  /** Sends one file; true on success. */
  async function sendOne(key: string, file: File): Promise<boolean> {
    patch(key, { state: "uploading", progress: 0, error: undefined });
    if (file.size > BIG_UPLOAD) await refreshNow();
    const form = new FormData();
    form.append("file", file);
    try {
      await api.post(`/meterings/${metering.id}/files/`, form, {
        onUploadProgress: (e) => patch(key, { progress: e.total ? Math.round((e.loaded / e.total) * 100) : 0 }),
      });
      patch(key, { state: "done", progress: 100 });
      fileOf.current.delete(key);
      files.refetch();
      return true;
    } catch (e) {
      patch(key, { state: "error", error: fieldErrors(e).files || errorMessage(e) });
      return false;
    }
  }

  async function upload(list: FileList | null) {
    const picked = Array.from(list ?? []);
    if (inputRef.current) inputRef.current.value = "";
    if (cameraRef.current) cameraRef.current.value = "";
    if (!picked.length) return;
    const stamp = Date.now();
    const items = picked.map((f, i) => {
      const tooBig = f.size > MAX_UPLOAD_MB * 1024 * 1024;
      const row: UploadRow = {
        key: `${stamp}-${i}`,
        name: f.name,
        size: f.size,
        progress: 0,
        state: tooBig ? "error" : "queued",
        error: tooBig ? `Juda katta (maks. ${MAX_UPLOAD_MB} MB)` : undefined,
        tooBig,
      };
      if (!tooBig) fileOf.current.set(row.key, f);
      return { file: f, row };
    });
    setQueue((q) => [...q.filter((r) => r.state !== "done"), ...items.map((x) => x.row)]);
    setBusy(true);
    setErrors((e) => ({ ...e, files: "" }));
    let ok = 0;
    for (const { file, row } of items) {
      if (row.state === "error") continue;
      if (await sendOne(row.key, file)) ok += 1;
    }
    setBusy(false);
    if (ok) toast.success(`Yuklandi: ${ok}`);
  }

  async function retry(key: string) {
    const file = fileOf.current.get(key);
    if (!file || busy) return;
    setBusy(true);
    const ok = await sendOne(key, file);
    setBusy(false);
    if (ok) toast.success("Yuklandi: 1");
  }

  const [note, setNote] = useState("");
  const [step, setStep] = useState<MeteringNextStep>("");
  const [designer, setDesigner] = useState("");
  const [pricer, setPricer] = useState("");
  const [manager, setManager] = useState("");
  const [designDue, setDesignDue] = useState("");
  const [priceDue, setPriceDue] = useState("");
  const people = useGet<MeteringAssignees>(a.finish ? "/meterings/assignees/" : null);
  // prefill the manager (the only one / the default) and the deadlines from the server's defaults
  useEffect(() => {
    const d = people.data;
    if (!d) return;
    const def = d.default_manager ?? (d.managers?.length === 1 ? d.managers[0].id : null);
    if (def && !manager) setManager(String(def));
    if (d.defaults) {
      if (!designDue) setDesignDue(toLocalInput(d.defaults.design_due_at));
      if (!priceDue) setPriceDue(toLocalInput(d.defaults.price_due_at));
    }
  }, [people.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const managers = people.data?.managers;
  const needsManager = !!managers?.length;
  const fileCount = files.data === undefined ? (metering.file_count ?? 0) : rows.length;
  const needsDesigner = step === "design_price";
  const isPast = (v: string) => !!v && new Date(v).getTime() <= Date.now();
  const dueBad = (needsDesigner && isPast(designDue)) || isPast(priceDue);
  const ready = fileCount > 0 && !!note.trim() && !!step && !!pricer && (!needsDesigner || !!designer) && (!needsManager || !!manager) && !dueBad && !busy;
  const finish = useAction(
    () =>
      api.post(`/meterings/${metering.id}/finish/`, {
        note: note.trim(),
        next_step: step,
        designer: needsDesigner && designer ? Number(designer) : null,
        pricer: pricer ? Number(pricer) : null,
        manager: manager ? Number(manager) : null,
        ...(needsDesigner && designDue ? { design_due_at: designDue } : {}),
        ...(priceDue ? { price_due_at: priceDue } : {}),
      }),
    { success: "Bajarildi — vazifalar yuborildi", invalidate: METERING_INVALIDATE },
  );

  const person = (u: UserShort) => u.name || phone(u.phone);
  const stepButton = (value: Exclude<MeteringNextStep, "">, icon: JSX.Element) => (
    <button
      type="button"
      onClick={() => setStep(value)}
      className={cn(
        "flex min-h-[52px] flex-1 items-center justify-center gap-2 rounded-xl border-2 px-4 text-sm font-semibold transition",
        step === value
          ? "border-brand-600 bg-brand-50 text-brand-800 dark:border-brand-400 dark:bg-brand-500/10 dark:text-brand-200"
          : "border-slate-200 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:text-slate-300",
      )}
    >
      {icon}
      {NEXT_STEP_LABEL[value]}
    </button>
  );

  return (
    <div id={id} className="scroll-mt-4">
      <Card title="Natija" actions={<FolderButton folderId={metering.folder} label="Papka" />}>
        <div className="space-y-5">
          {a.upload && (
            <div>
              <div className="label">Rasm, video, PDF</div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button size="lg" variant="outline" icon={<Upload className="h-5 w-5" />} disabled={busy} onClick={() => inputRef.current?.click()}>
                  Fayl tanlash
                </Button>
                <Button size="lg" variant="outline" className="sm:hidden" icon={<Camera className="h-5 w-5" />} disabled={busy} onClick={() => cameraRef.current?.click()}>
                  Suratga olish
                </Button>
              </div>
              <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => upload(e.target.files)} />
              <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => upload(e.target.files)} />
              <p className="muted mt-1.5 text-xs">Har bir fayl {MAX_UPLOAD_MB} MB gacha. Fayllar birma-bir yuklanadi — sahifani yopmang.</p>
              {errors.files && <p className="mt-1 text-xs text-rose-600">{errors.files}</p>}
              {queue.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {queue.map((r) => (
                    <li key={r.key} className="rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
                      <div className="flex items-center gap-2">
                        {r.state === "done" ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                        ) : r.state === "error" ? (
                          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
                        ) : (
                          <Loader2 className={cn("h-4 w-4 shrink-0", r.state === "uploading" ? "animate-spin text-brand-600" : "text-slate-300")} />
                        )}
                        <span className="min-w-0 flex-1 truncate">{r.name}</span>
                        <span className="muted shrink-0 text-xs tabular-nums">
                          {r.state === "uploading" ? `${r.progress}%` : fileSize(r.size)}
                        </span>
                      </div>
                      {(r.state === "uploading" || r.state === "queued") && (
                        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                          <div className="h-full rounded-full bg-brand-600 transition-[width]" style={{ width: `${r.progress}%` }} />
                        </div>
                      )}
                      {r.error && (
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <p className="min-w-0 flex-1 text-xs text-rose-600">{r.error}</p>
                          {r.state === "error" && !r.tooBig && fileOf.current.has(r.key) && (
                            <Button size="sm" variant="outline" icon={<RotateCw className="h-4 w-4" />} disabled={busy} onClick={() => retry(r.key)}>
                              Qayta urinish
                            </Button>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div>
            <div className="label">Yuklangan fayllar · {fileCount}</div>
            {files.isLoading ? (
              <Spinner />
            ) : rows.length ? (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {rows.map((f) => (
                  <div
                    key={f.id}
                    title={f.name}
                    className="group relative flex aspect-square flex-col items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-center dark:border-slate-700 dark:bg-slate-800/50"
                  >
                    {f.is_image && (f.thumbnail || f.url) ? (
                      <img src={f.thumbnail || f.url} alt={f.name} loading="lazy" className="h-full w-full object-cover" />
                    ) : (
                      <>
                        <FileText className="h-7 w-7 text-slate-400" />
                        <span className="mt-1 line-clamp-2 break-all px-1.5 text-[11px] text-slate-600 dark:text-slate-300">{f.name}</span>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted text-sm">Hali fayl yo'q</p>
            )}
            {rows.length > 0 && (
              <p className="muted mt-1.5 text-xs">Ko'rish va yuklab olish — «Papka» tugmasi orqali.</p>
            )}
          </div>

          {a.finish && (
            <>
              <Field label="Izoh: nima ko'rdingiz, mijoz nima xohlaydi" error={errors.note}>
                <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="O'lchamlar, material, rang, mijoz istaklari…" />
              </Field>
              <div>
                <div className="label">Keyingi qadam</div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  {stepButton("design_price", <Brush className="h-4 w-4" />)}
                  {stepButton("price", <Calculator className="h-4 w-4" />)}
                </div>
                {errors.next_step && <p className="mt-1 text-xs text-rose-600">{errors.next_step}</p>}
              </div>
              {step && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {needsDesigner && (
                    <Field label="Dizayner" error={errors.designer}>
                      {people.data && !people.data.designers.length ? (
                        <NoAssignee text={people.data.designer_hint || "Dizayner yo'q — Xodimlar → Guruhlar (rollar)da «Dizayner» roliga xodim qo'shing"} />
                      ) : (
                        <Select className="h-12" value={designer} onChange={(e) => setDesigner(e.target.value)}>
                          <option value="">— tanlang —</option>
                          {people.data?.designers.map((u) => (
                            <option key={u.id} value={u.id}>
                              {person(u)}
                            </option>
                          ))}
                        </Select>
                      )}
                    </Field>
                  )}
                  <Field label="Narx hisoblovchi" error={errors.pricer} className={needsDesigner ? undefined : "sm:col-span-2"}>
                    {people.data && !people.data.pricers.length ? (
                      <NoAssignee text={people.data.pricer_hint || "Narx hisoblovchi yo'q — Xodimlar → Guruhlar (rollar)da «Narxchi» roliga xodim qo'shing"} />
                    ) : (
                      <Select className="h-12" value={pricer} onChange={(e) => setPricer(e.target.value)}>
                        <option value="">— tanlang —</option>
                        {people.data?.pricers.map((u) => (
                          <option key={u.id} value={u.id}>
                            {person(u)}
                          </option>
                        ))}
                      </Select>
                    )}
                  </Field>
                  {needsDesigner && (
                    <Field
                      label="Dizayn muddati"
                      error={errors.design_due ?? errors.design_due_at ?? (isPast(designDue) ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}
                    >
                      <Input className="h-12 text-base" type="datetime-local" value={designDue} onChange={(e) => setDesignDue(e.target.value)} />
                    </Field>
                  )}
                  <Field
                    label="Narx muddati"
                    className={needsDesigner ? undefined : "sm:col-span-2"}
                    hint={needsDesigner ? "Dizayn va narx bir vaqtda boshlanadi" : undefined}
                    error={errors.price_due ?? errors.price_due_at ?? (isPast(priceDue) ? "O'tgan vaqt — kelajakdagi vaqtni kiriting" : undefined)}
                  >
                    <Input className="h-12 text-base" type="datetime-local" value={priceDue} onChange={(e) => setPriceDue(e.target.value)} />
                  </Field>
                  <Field
                    label="Menejer (mijozga ko'rsatadi)"
                    className="sm:col-span-2"
                    error={errors.manager}
                    hint={
                      people.data && !needsManager ? (
                        <span className="text-amber-700 dark:text-amber-300">{people.data.hint || "Menejer yo'q — xodimga «Menejer» huquqini bering"}</span>
                      ) : (
                        "Dizayn/narx tayyor bo'lganda unga xabar boradi"
                      )
                    }
                  >
                    <Select className="h-12" value={manager} disabled={!needsManager} onChange={(e) => setManager(e.target.value)}>
                      {(managers?.length ?? 0) !== 1 && <option value="">— tanlang —</option>}
                      {managers?.map((u) => (
                        <option key={u.id} value={u.id}>
                          {person(u)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
              )}
              {errors.non_field_errors && <p className="text-sm text-rose-600">{errors.non_field_errors}</p>}
              <Button
                size="lg"
                variant="success"
                className="w-full"
                icon={<CheckCircle2 className="h-5 w-5" />}
                disabled={!ready}
                loading={finish.isPending}
                onClick={() => {
                  setErrors({});
                  finish.mutateAsync().catch((e) => setErrors(fieldErrors(e)));
                }}
              >
                Bajarildi
              </Button>
              {!ready && !busy && (
                <p className="muted -mt-3 text-center text-xs">
                  {fileCount === 0
                    ? "Kamida bitta fayl yuklang"
                    : !note.trim()
                      ? "Izoh yozing"
                      : !step
                        ? "Keyingi qadamni tanlang"
                        : !pricer || (needsDesigner && !designer)
                          ? "Ijrochilarni tanlang"
                          : needsManager && !manager
                            ? "Menejerni tanlang"
                            : "Muddatni to'g'rilang"}
                </p>
              )}
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

/** nobody holds the role — say where to fix it instead of an empty select */
function NoAssignee({ text }: { text: string }) {
  return (
    <div className="flex min-h-12 items-center rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
      {text}
    </div>
  );
}
