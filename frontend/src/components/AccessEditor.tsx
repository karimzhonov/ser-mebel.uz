import { useState } from "react";
import { api } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { AccessLevel, UserAccess } from "@/api/types";
import { Button, Empty, PageLoader, Segmented } from "./ui";

const LEVEL_LABEL: Record<string, string> = { none: "Yo'q", view: "Ko'rish", edit: "O'zgartirish", custom: "Qo'lda sozlangan" };

/** Per-section access (none / view / edit) and the yes/no task flags.
 * The same editor for a person (`/users/{id}/access/`) and a group-role (`/groups/{id}/access/`):
 * GET returns {sections}, POST takes {levels: {key: level}} with only the changed keys. */
export function AccessEditor({ path, subject, invalidate, onSaved }: { path: string; subject: "user" | "group"; invalidate: string[]; onSaved?: () => void }) {
  const { data } = useGet<UserAccess>(path);
  const [changed, setChanged] = useState<Record<string, AccessLevel>>({});
  const save = useAction(() => api.post(path, { levels: changed }), {
    success: "Huquqlar saqlandi",
    invalidate: [...invalidate, path],
    onSuccess: () => {
      setChanged({});
      onSaved?.();
    },
  });
  if (!data) return <PageLoader />;
  if (data.is_keeper) return <Empty title="Bu xodim — omborchi" text="Uning huquqlari Ombor → Omborchi sahifasida boshqariladi." />;
  const titles = [...new Set(data.sections.map((s) => s.title))];

  return (
    <div className="space-y-5">
      <p className="muted text-xs">
        «Ko'rish» — bo'limni ochadi, lekin hech narsani o'zgartira olmaydi. «O'zgartirish» — qo'shish, tahrirlash va o'chirish ham mumkin.{" "}
        {subject === "user"
          ? "Guruhdan kelgan huquqlar shu yerda o'zgarmaydi — ular yonida ko'rsatilgan."
          : "Guruhdagi har bir xodim shu huquqlarni oladi; Telegram'ga ulangan bo'lsa, vazifalar unga bot orqali boradi."}
      </p>
      {titles.map((title) => (
        <section key={title}>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
            {data.sections
              .filter((s) => s.title === title)
              .map((s) => {
                const value: string = (changed[s.key] as AccessLevel | undefined) ?? s.level;
                const options = [
                  { value: "none", label: "Yo'q" },
                  { value: "view", label: s.is_flag ? "Ha" : "Ko'rish" },
                  ...(s.can_edit ? [{ value: "edit", label: "O'zgartirish" }] : []),
                ];
                return (
                  <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{s.label}</div>
                      <div className="muted flex flex-wrap gap-x-2 text-xs">
                        {s.hint && <span>{s.hint}</span>}
                        {s.from_groups && s.from_groups !== "none" && (
                          <span className="text-brand-700 dark:text-brand-300">guruhdan: {LEVEL_LABEL[s.from_groups]}</span>
                        )}
                        {value === "custom" && <span className="text-amber-700">qo'lda sozlangan — tanlasangiz almashtiriladi</span>}
                      </div>
                    </div>
                    <Segmented
                      value={value}
                      options={options}
                      onChange={(v) =>
                        setChanged((c) => {
                          const next = { ...c };
                          if (v === s.level) delete next[s.key];
                          else next[s.key] = v as AccessLevel;
                          return next;
                        })
                      }
                    />
                  </li>
                );
              })}
          </ul>
        </section>
      ))}
      <div className="sticky bottom-0 -mb-4 flex justify-end border-t border-slate-100 bg-white py-3 dark:border-slate-800 dark:bg-slate-900">
        <Button disabled={!Object.keys(changed).length} loading={save.isPending} onClick={() => save.mutate()}>
          Saqlash{Object.keys(changed).length ? ` (${Object.keys(changed).length})` : ""}
        </Button>
      </div>
    </div>
  );
}
