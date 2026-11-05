import { useState } from "react";
import { api } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { AccessLevel, AccessSection, UserAccess } from "@/api/types";
import { Button, Empty, PageLoader, Switch } from "./ui";

const LEVEL_LABEL: Record<string, string> = { none: "Yo'q", view: "Ko'rish", edit: "O'zgartirish", custom: "Qo'lda sozlangan" };
const FLAGS_TITLE = "Vazifalar (bot)";

/** Per-section access as switches («Ko'rish» / «O'zgartirish») and one switch per task flag.
 * The same editor for a person (`/users/{id}/access/`) and a lavozim (`/groups/{id}/access/`):
 * GET returns {sections}, POST takes {levels: {key: none|view|edit}} with only the changed keys.
 * Coupling: «O'zgartirish» on ⇒ «Ko'rish» on; «Ko'rish» off ⇒ «O'zgartirish» off. */
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

  const setLevel = (s: AccessSection, v: AccessLevel) =>
    setChanged((c) => {
      const next = { ...c };
      if (v === s.level) delete next[s.key];
      else next[s.key] = v;
      return next;
    });
  const sections = data.sections.filter((s) => !s.is_flag);
  const flags = data.sections.filter((s) => s.is_flag);
  const titles = [...new Set(sections.map((s) => s.title))];
  const groups: { title: string; rows: AccessSection[] }[] = [
    ...titles.map((title) => ({ title, rows: sections.filter((s) => s.title === title) })),
    ...(flags.length ? [{ title: FLAGS_TITLE, rows: flags }] : []),
  ];

  return (
    <div className="space-y-5">
      <p className="muted text-xs">
        «Ko'rish» — bo'limni ochadi, lekin hech narsani o'zgartira olmaydi. «O'zgartirish» — qo'shish, tahrirlash va o'chirish ham mumkin (u «Ko'rish»ni ham yoqadi).{" "}
        {subject === "user"
          ? "Lavozimdan kelgan huquqlar shu yerda o'zgarmaydi — ular yonida ko'rsatilgan."
          : "Lavozimdagi har bir xodim shu huquqlarni oladi; Telegram'ga ulangan bo'lsa, vazifalar unga bot orqali boradi."}
      </p>
      {groups.map(({ title, rows }) => (
        <section key={title}>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
          {title === FLAGS_TITLE && <p className="muted mb-1 text-xs">Yoqilgan vazifa bo'yicha xodimga bot orqali ish va eslatmalar keladi.</p>}
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
            {rows.map((s) => {
              const value: AccessLevel | "custom" = (changed[s.key] as AccessLevel | undefined) ?? s.level;
              const custom = value === "custom";
              const view: boolean | "mixed" = custom ? "mixed" : value !== "none";
              const edit: boolean | "mixed" = custom ? "mixed" : value === "edit";
              return (
                <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{s.label}</div>
                    <div className="muted flex flex-wrap gap-x-2 text-xs">
                      {s.hint && <span>{s.hint}</span>}
                      {s.is_flag && title === FLAGS_TITLE && s.title && <span>{s.title}</span>}
                      {s.from_groups && s.from_groups !== "none" && (
                        <span className="text-brand-700 dark:text-brand-300">lavozimdan: {s.is_flag && s.from_groups !== "custom" ? "yoqilgan" : LEVEL_LABEL[s.from_groups]}</span>
                      )}
                      {custom && <span className="text-amber-700 dark:text-amber-300">qo'lda sozlangan — kalitni bossangiz almashtiriladi</span>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4">
                    {s.is_flag ? (
                      <Switch label="Yoqilgan" checked={view} onChange={(on) => setLevel(s, on ? "view" : "none")} />
                    ) : (
                      <>
                        <Switch label="Ko'rish" checked={view} onChange={(on) => setLevel(s, on ? "view" : "none")} />
                        {s.can_edit && <Switch label="O'zgartirish" checked={edit} onChange={(on) => setLevel(s, on ? "edit" : "view")} />}
                      </>
                    )}
                  </div>
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
