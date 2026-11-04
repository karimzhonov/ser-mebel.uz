import type { ReactNode } from "react";
import type { OfferAnswer, OfferFields, OfferKind, PersonRef } from "@/api/types";
import { Card, KV } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { personName } from "../meterings/actions";
import {
  AnswerButtons,
  AnswersHistory,
  ASSIGNEE_LABEL,
  CLIENT_RESULT_LABEL,
  DueButton,
  DueLabel,
  OfferStageBadge,
  ReassignSelect,
} from "./actions";

/** The stage-2 block of a design / price page: deadline (+ «Muddatni o'zgartirish»), who works on it
 * (+ reassign), the manager, the measurer and their note, the round, the client's answer buttons
 * (for the manager, while it is at the client) and the answers history. */
export function OfferStatusCard({
  kind,
  id,
  offer,
  assignee,
  actions,
  client,
}: {
  kind: OfferKind;
  id: number;
  offer: Partial<OfferFields>;
  assignee: PersonRef | null | undefined;
  actions?: { due?: boolean; reassign?: boolean; answer?: boolean };
  client?: string;
}) {
  const a = actions ?? {};
  const stage = offer.stage;
  const items: [ReactNode, ReactNode][] = [
    ["Holat", <OfferStageBadge stage={stage} label={offer.stage_label} overdue={offer.is_overdue} />],
  ];
  if (stage === "work" || offer.due_at)
    items.push(["Muddat", <DueLabel value={offer.due_at} overdue={offer.is_overdue && stage === "work"} className="text-base" />]);
  if (offer.done_at) items.push(["Tayyor bo'lgan", dateTime(offer.done_at)]);
  items.push([ASSIGNEE_LABEL[kind], a.reassign ? <ReassignSelect kind={kind} id={id} current={assignee} /> : personName(assignee, "tayinlanmagan")]);
  items.push(["Menejer", personName(offer.manager, "tayinlanmagan")]);
  if (offer.measurer) items.push(["Zamerchi", personName(offer.measurer)]);
  if ((offer.round ?? 1) > 1) items.push(["Raund", `${offer.round}-raund`]);
  if (offer.client_result) items.push(["Mijoz javobi", CLIENT_RESULT_LABEL[offer.client_result] ?? offer.client_result]);
  const answers: OfferAnswer[] = offer.answers ?? [];

  return (
    <>
      <Card title="Vazifa">
        {a.due && stage === "work" && <DueButton big kind={kind} id={id} dueAt={offer.due_at ?? null} className="mb-3 w-full" />}
        <KV items={items} />
        {offer.last_comment && (offer.round ?? 1) > 1 && (
          <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
            <div className="text-xs font-medium">{kind === "design" ? "Mijoz o'zgartirish so'radi" : "Qayta hisoblash sababi"}</div>
            <div className="whitespace-pre-line break-words">{offer.last_comment}</div>
          </div>
        )}
        {offer.result_note && (
          <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60">
            <div className="muted text-xs font-medium">Zamerchi izohi</div>
            <div className="whitespace-pre-line break-words">{offer.result_note}</div>
          </div>
        )}
      </Card>
      {a.answer && stage === "review" && (
        <Card title="Mijoz javobi">
          <p className="muted mb-3 text-sm">Mijozga ko'rsating va javobini belgilang.</p>
          <AnswerButtons big kind={kind} id={id} client={client} />
        </Card>
      )}
      {answers.length > 0 && (
        <Card title="Javoblar tarixi">
          <AnswersHistory kind={kind} answers={answers} />
        </Card>
      )}
    </>
  );
}
