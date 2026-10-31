import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download, FileSpreadsheet, Trash2, Upload } from "lucide-react";
import { api, downloadFile, errorMessage } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { Button, Empty, Field, Input, Modal, Skeleton } from "@/components/ui";
import { date } from "@/lib/format";
import { som } from "./shared";
import type { SalaryInfo, WorkerCard } from "./types";

const PLACEHOLDERS: [string, string][] = [
  ["{ism}", "ism"],
  ["{lavozim} {bolim}", "lavozim, bo'lim"],
  ["{oy} {sana}", "oy nomi, oylik sanasi"],
  ["{davr}", "avanslar davri"],
  ["{avans}", "avanslar jami"],
  ["{avans_soni}", "nechta avans"],
  [
    "{avans_n} {avans_sana} {avans_valyuta} {avans_asl} {avans_kurs} {avans_summa} {avans_kim} {avans_izoh}",
    "bitta qatorga — har avans uchun pastga takrorlanadi",
  ],
];

/** «Oylik chiqarish»: the worker's own Excel template with the advances filled in;
 * the accountant fills in the rest. Also the pay day and the template itself. */
export function SalaryModal({ card, onClose }: { card: WorkerCard; onClose: () => void }) {
  const { can } = useAuth();
  const id = card.worker_id!;
  const canEdit = can("accounting.change_worker");
  const [month, setMonth] = useState("");
  const [payDay, setPayDay] = useState(card.pay_day ? String(card.pay_day) : "");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: info, isLoading } = useGet<SalaryInfo>(`/finance/workers/${id}/salary/`, { month });
  const ym = month || info?.month || "";

  const savePayDay = useAction(
    () => api.patch(`/finance/workers/${id}/`, { pay_day: payDay ? Number(payDay) : null }),
    { success: "Oylik kuni saqlandi", invalidate: ["/finance/"] },
  );
  const upload = useAction(
    (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post(`/finance/workers/${id}/template/`, fd);
    },
    { success: "Shablon yuklandi", invalidate: ["/finance/"] },
  );
  const remove = useAction(() => api.delete(`/finance/workers/${id}/template/`), {
    success: "Shablon o'chirildi",
    invalidate: ["/finance/"],
  });

  const download = async (url: string, name: string) => {
    setBusy(true);
    try {
      await downloadFile(url, name);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={`🧾 Oylik chiqarish — ${card.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Yopish
          </Button>
          <Button
            icon={<Download className="h-4 w-4" />}
            loading={busy}
            disabled={!info}
            onClick={() =>
              download(`/finance/workers/${id}/salary/excel/?month=${ym}`, `Oylik_${ym}_${card.name}.xlsx`)
            }
          >
            Excel yuklab olish
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Oylik beriladigan oy" hint="Bo'sh — keyingi oylik kuni">
            <Input type="month" value={ym} onChange={(e) => setMonth(e.target.value)} />
          </Field>
          <Field label="Oylik kuni (oyning sanasi)" hint="Bir kun oldin bugalterga botda eslatma keladi">
            <div className="flex gap-2">
              <Input
                type="number"
                min={1}
                max={31}
                placeholder="masalan 5"
                value={payDay}
                disabled={!canEdit}
                onChange={(e) => setPayDay(e.target.value)}
              />
              {canEdit && (
                <Button
                  variant="outline"
                  loading={savePayDay.isPending}
                  disabled={payDay === (card.pay_day ? String(card.pay_day) : "")}
                  onClick={() => savePayDay.mutate()}
                >
                  Saqlash
                </Button>
              )}
            </div>
          </Field>
        </div>

        <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
          {isLoading || !info ? (
            <Skeleton className="h-16" />
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-sm">
                  📅 Oylik sanasi: <b>{date(info.pay_date)}</b>
                  <span className="muted"> · avanslar {date(info.date_from)} — {date(info.date_to)}</span>
                </div>
                <div className="text-sm">
                  💵 Avans jami: <b>{som(info.advance_total)}</b>
                </div>
              </div>
              {info.advances.length ? (
                <div className="max-h-48 overflow-auto">
                  <table className="w-full text-sm">
                    <tbody>
                      {info.advances.map((a) => (
                        <tr key={a.id} className="border-t border-slate-100 dark:border-slate-800">
                          <td className="py-1.5 pr-3 whitespace-nowrap">{date(a.date)}</td>
                          <td className="py-1.5 pr-3 text-right font-medium tabular-nums whitespace-nowrap">{som(a.amount)}</td>
                          <td className="py-1.5 pr-3 whitespace-nowrap">{a.member}</td>
                          <td className="muted py-1.5">{a.comment}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="Bu davrda avans berilmagan" />
              )}
            </>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
          <div className="mb-2 flex items-center gap-2 font-medium">
            <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> Shablon
          </div>
          <p className="muted mb-3 text-sm">
            {card.template_name
              ? `Yuklangan: ${card.template_name}`
              : "Shablon yuklanmagan — standart shablon ishlatiladi. Yuklab olib, o'zingizga moslab qayta yuklang."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              icon={<Download className="h-4 w-4" />}
              onClick={() =>
                download(`/finance/workers/${id}/template/`, card.template_name || `Oylik_shablon_${card.name}.xlsx`)
              }
            >
              {card.template_name ? "Shablonni yuklab olish" : "Standart shablon"}
            </Button>
            {canEdit && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) upload.mutate(f);
                    e.target.value = "";
                  }}
                />
                <Button
                  variant="outline"
                  size="sm"
                  icon={<Upload className="h-4 w-4" />}
                  loading={upload.isPending}
                  onClick={() => fileRef.current?.click()}
                >
                  {card.template_name ? "Almashtirish" : "Shablon yuklash"}
                </Button>
                {card.template_name && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 className="h-4 w-4" />}
                    loading={remove.isPending}
                    onClick={() => confirm("Shablon o'chirilsinmi?") && remove.mutate()}
                  >
                    O'chirish
                  </Button>
                )}
              </>
            )}
          </div>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-slate-500">Shablonda nimalar avtomatik to'ldiriladi?</summary>
            <p className="mt-2">
              Ofis shablonlari (ODDIY, OFIS, MENEJER, ZAMER, SBORKA) o'zgartirmasdan ishlaydi: «Xodim», «Lavozim»,
              «Davr», «Hisob sanasi», dollar kursi va «OLINGAN AVANSLAR» jadvali (sana, izoh, valyuta, summa, kurs)
              o'zi to'ldiriladi — formulalar o'z joyida qoladi. Avans jadvalga sig'masa, ortiqchasi oxirgi qatorga
              bitta summa bo'lib yoziladi.
            </p>
            <p className="mt-2">Boshqa shablon uchun kataklarga quyidagilarni yozing:</p>
            <ul className="mt-2 space-y-1">
              {PLACEHOLDERS.map(([k, v]) => (
                <li key={k}>
                  <code className="rounded bg-slate-100 px-1 text-xs dark:bg-slate-800">{k}</code> — {v}
                </li>
              ))}
            </ul>
            <p className="muted mt-2">
              Shu so'zlarni Excel katagiga yozing — chiqarishda o'rniga qiymat qo'yiladi. Qolgan kataklarni bugalter
              to'ldiradi. Har doim «Avanslar» varag'i ham qo'shiladi. Faqat .xlsx.
            </p>
          </details>
        </div>
      </div>
    </Modal>
  );
}
