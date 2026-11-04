import { useState } from "react";
import { ArrowRight, Eye } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { GroupMergePlan, GroupMergePreview, GroupMergeResult, StaffUser } from "@/api/types";
import { Badge, Button, Confirm, Empty, Modal, PageLoader, Select } from "@/components/ui";

type Item = GroupMergePlan["items"][number];
type Member = Pick<StaffUser, "id" | "phone" | "name">;
/** a target lavozim id, «personal» (add to each member's own rights) or «skip» */
type Choice = string;
const PERSONAL = "personal";
const SKIP = "skip";

const FILER_LIKE = /filer|файл|fayl/i;
const person = (m: Member | string) => (typeof m === "string" ? m : m.name || m.phone);

const defaultChoice = (it: Item): Choice =>
  it.suggested ? String(it.suggested.id) : it.to_personal || it.action === "to_personal" || FILER_LIKE.test(it.group.name) ? PERSONAL : SKIP;

/** «Eski guruhlarni ko'chirish» — the owner reviews where every old group goes before anything moves:
 * members join the target lavozim and the target also gets every right of the old group (nobody loses
 * a right), or — for Filer-like groups — the rights go to each member personally; then the old group is deleted. */
export function MergeModal({ plan, onClose }: { plan: GroupMergePlan; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title="Eski guruhlarni lavozimlarga ko'chirish" size="xl">
      <p className="muted mb-4 text-xs">
        Har bir eski guruh uchun qaysi lavozimga ko'chishini tanlang. «Ko'chirish» bosilganda guruh a'zolari tanlangan lavozimga qo'shiladi, lavozimga esa guruhning
        barcha huquqlari ham qo'shiladi — hech kim huquqini yo'qotmaydi. Shundan keyin eski guruh o'chiriladi. «Tegmaslik» — guruh o'z holicha qoladi.
      </p>
      {!plan.items.length ? (
        <Empty title="Ko'chiriladigan eski guruh yo'q" />
      ) : (
        <ul className="space-y-3">
          {plan.items.map((it) => (
            <MergeRow key={it.group.id} item={it} targets={plan.targets} />
          ))}
        </ul>
      )}
    </Modal>
  );
}

function MergeRow({ item, targets }: { item: Item; targets: GroupMergePlan["targets"] }) {
  const g = item.group;
  const [choice, setChoice] = useState<Choice>(() => defaultChoice(item));
  const [preview, setPreview] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const { data: membersData } = useGet<Member[] | { results: Member[] }>(`/groups/${g.id}/members/`);
  const members: Member[] = Array.isArray(membersData) ? membersData : membersData?.results ?? [];
  const target = targets.find((t) => String(t.id) === choice);
  const previewQ = useGet<GroupMergePreview>((preview || confirm) && target ? `/groups/${g.id}/merge-preview/` : null, { target: target?.id });

  const move = useAction(
    () => api.post<GroupMergeResult>(`/groups/${g.id}/merge-into/`, choice === PERSONAL ? { to_personal: true } : { target: Number(choice) }).then((r) => r.data),
    {
      invalidate: ["groups", "users"],
      onSuccess: (r) => {
        setConfirm(false);
        const added = r.added_permissions?.length ?? 0;
        toast.success(
          `«${r.deleted || g.name}» ko'chirildi: ${r.moved_members} ta xodim${choice === PERSONAL ? ", huquqlar shaxsiy qilib berildi" : target ? ` → ${target.name}` : ""}${added ? `, +${added} ta huquq` : ""}`,
        );
      },
    },
  );
  const rename = useAction(() => api.patch(`/groups/${g.id}/`, { name: item.rename_to }), {
    success: "Nomi o'zgartirildi",
    invalidate: ["groups", "users"],
  });

  const shown = members.slice(0, 8);
  return (
    <li className="rounded-xl border border-slate-100 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{g.name}</span>
            <Badge dot={false}>{g.member_count} ta xodim</Badge>
          </div>
          {shown.length > 0 && (
            <div className="muted mt-0.5 text-xs">
              {shown.map(person).join(", ")}
              {members.length > shown.length && ` va yana ${members.length - shown.length} ta`}
            </div>
          )}
          {item.reason && <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">{item.reason}</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ArrowRight className="muted hidden h-4 w-4 sm:block" />
          <Select className="w-56" value={choice} aria-label={`${g.name} — qayerga`} onChange={(e) => (setChoice(e.target.value), setPreview(false))}>
            <option value={SKIP}>Tegmaslik</option>
            <option value={PERSONAL}>Shaxsiy huquq sifatida</option>
            <optgroup label="Lavozimga">
              {targets
                .filter((t) => t.id !== g.id)
                .map((t) => (
                  <option key={t.id} value={String(t.id)}>
                    {t.name}
                    {item.suggested?.id === t.id ? " (tavsiya)" : ""}
                  </option>
                ))}
            </optgroup>
          </Select>
          {target && (
            <Button size="sm" variant="outline" icon={<Eye className="h-4 w-4" />} onClick={() => setPreview((v) => !v)}>
              Ko'rish
            </Button>
          )}
          {item.rename_to && (
            <Button size="sm" variant="outline" loading={rename.isPending} onClick={() => rename.mutate()}>
              «{item.rename_to}» deb nomlash
            </Button>
          )}
          <Button size="sm" disabled={choice === SKIP || g.locked} onClick={() => setConfirm(true)}>
            Ko'chirish
          </Button>
        </div>
      </div>

      {choice === PERSONAL && (
        <p className="muted mt-2 text-xs">
          Guruhning huquqlari har bir a'zoning shaxsiy huquqlariga qo'shiladi (masalan, «Fayllar» bo'limi), keyin guruh o'chiriladi.
        </p>
      )}
      {preview && target && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
          {previewQ.isLoading ? (
            <PageLoader />
          ) : previewQ.error || !previewQ.data ? (
            <span className="text-rose-600">Oldindan ko'rib bo'lmadi</span>
          ) : (
            <PreviewBody data={previewQ.data} target={target.name} />
          )}
        </div>
      )}

      <Confirm
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => move.mutate()}
        loading={move.isPending}
        confirmLabel="Ko'chirish"
        title={`«${g.name}» ni ko'chirish`}
        text={
          choice === PERSONAL ? (
            <>
              <b>{g.name}</b> guruhining huquqlari uning {g.member_count} ta a'zosiga shaxsiy huquq sifatida beriladi, keyin guruh o'chiriladi.
            </>
          ) : (
            <>
              <b>{g.name}</b> guruhidagi {g.member_count} ta xodim <b>{target?.name}</b> lavozimiga qo'shiladi, lavozimga guruhning barcha huquqlari ham qo'shiladi
              , keyin <b>{g.name}</b> o'chiriladi.
              <div className="mt-3">
                {previewQ.isLoading ? (
                  <span className="muted text-xs">Qo'shiladigan huquqlar hisoblanmoqda…</span>
                ) : previewQ.data ? (
                  <PreviewBody data={previewQ.data} target={target?.name ?? ""} />
                ) : null}
              </div>
            </>
          )
        }
      />
    </li>
  );
}

function PreviewBody({ data, target }: { data: GroupMergePreview; target: string }) {
  return (
    <div className="space-y-2">
      <div>
        <div className="label">Ko'chadigan xodimlar · {data.members.length}</div>
        {data.members.length ? <div>{data.members.map(person).join(", ")}</div> : <span className="muted">Xodim yo'q</span>}
      </div>
      <div>
        <div className="label">
          {target} lavozimiga quyidagi huquqlar ham qo'shiladi
          {data.target_member_count ? ` (lavozimdagi ${data.target_member_count} ta xodimga ham o'tadi)` : ""}:
        </div>
        {data.add_to_target.length ? (
          <div className="flex flex-wrap gap-1">
            {data.add_to_target.map((p) => (
              <Badge key={p.key} dot={false}>
                {p.label}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="muted">Yangi huquq yo'q — lavozimda bularning hammasi bor.</span>
        )}
      </div>
    </div>
  );
}
