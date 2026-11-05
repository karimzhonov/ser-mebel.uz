import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, FolderOpen, Package, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useAction, useGet } from "@/api/hooks";
import type { Design, DesignType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AddressLink, BackLink, DeadlinePill, FolderButton, FolderModal, OrderStatusBadge, PhoneLink } from "@/components/domain";
import {
  Badge,
  Button,
  Card,
  Confirm,
  Empty,
  Field,
  IconButton,
  Input,
  KV,
  Modal,
  PageHeader,
  PageLoader,
} from "@/components/ui";
import { dateTime } from "@/lib/format";
import { personName } from "./meterings/actions";
import { OfferAgenda } from "./offers/OfferAgenda";
import { OfferStatusCard } from "./offers/OfferStatusCard";
import { CLIENT_RESULT_LABEL, Hint, OFFER_INVALIDATE, OfferStageBadge } from "./offers/actions";

/** «Dizayn» — the designer's agenda (deadline first, overdue in red). */
export function DesignsPage() {
  return <OfferAgenda kind="design" />;
}

export function DesignDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: d, isLoading } = useGet<Design>(`/designs/${id}/`);
  const [confirmDone, setConfirmDone] = useState(false);
  const [variant, setVariant] = useState<{ id?: number; name: string } | null>(null);
  const [folder, setFolder] = useState<number | null>(null);

  const inv = OFFER_INVALIDATE;
  const done = useAction(() => api.post(`/designs/${id}/done/`), {
    success: "Dizayn tayyor — menejerga yuborildi",
    invalidate: inv,
    onSuccess: () => setConfirmDone(false),
  });
  const saveVariant = useAction(
    () =>
      variant?.id
        ? api.patch(`/design-types/${variant.id}/`, { name: variant.name })
        : api.post(`/designs/${id}/types/`, { name: variant?.name }),
    { success: "Saqlandi", invalidate: inv, onSuccess: () => setVariant(null) },
  );
  const removeVariant = useAction((typeId: number) => api.delete(`/design-types/${typeId}/`), {
    success: "O'chirildi",
    invalidate: inv,
  });

  if (isLoading || !d) return <PageLoader />;
  const m = d.metering;
  const noFiles = d.file_count === 0;
  return (
    <div>
      <PageHeader
        back={<BackLink to="/designs">Dizayn</BackLink>}
        title={m.client.fio}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {d.stage ? (
              <OfferStageBadge stage={d.stage} label={d.stage_label} overdue={d.is_overdue} />
            ) : d.done ? (
              <Badge tone="ok">Bajarildi</Badge>
            ) : (
              <Badge tone="warn">Ishda</Badge>
            )}
            {d.order && <Badge tone="primary">Buyurtma rasmiylashtirildi</Badge>}
            {d.client_result && <Badge tone={d.client_result === "agreed" ? "ok" : "danger"}>{CLIENT_RESULT_LABEL[d.client_result]}</Badge>}
            {d.user_detail && <span>Dizayner: {personName(d.user_detail)}</span>}
          </span>
        }
        actions={
          <>
            <FolderButton folderId={m.folder} label="O'lchov fayllari" />
            {d.actions.done && (
              <Button
                size="lg"
                variant="success"
                className="w-full sm:w-auto"
                icon={<CheckCircle2 className="h-5 w-5" />}
                disabled={noFiles}
                onClick={() => setConfirmDone(true)}
              >
                Tayyor
              </Button>
            )}
            {d.actions.create_order && (
              <Button
                icon={<Package className="h-4 w-4" />}
                onClick={() => navigate(`/orders/new?metering=${m.id}&design=${d.id}`)}
              >
                Buyurtma yaratish
              </Button>
            )}
          </>
        }
      />
      {(d.is_overdue && d.stage === "work") || (d.actions.done && noFiles) ? (
        <div className="mb-4 space-y-2">
          {d.is_overdue && d.stage === "work" && <Hint tone="danger">Muddat o'tdi — dizaynni tayyorlang yoki muddatni o'zgartiring.</Hint>}
          {d.actions.done && noFiles && <Hint>Kamida bitta fayl yuklang — variant papkasiga dizayn fayllarini qo'ying, keyin «Tayyor»ni bosing.</Hint>}
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Dizayn variantlari"
          padded={false}
          actions={
            d.actions.add_type && (
              <Button size="sm" variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setVariant({ name: `Dizayn-${d.types.length + 1}` })}>
                Variant
              </Button>
            )
          }
        >
          {!d.types.length && <Empty title="Variantlar yo'q" />}
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {d.types.map((t: DesignType) => (
              <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <div>
                  <div className="font-medium">{t.name}</div>
                  <div className="muted text-xs">{dateTime(t.created_at)}</div>
                </div>
                <div className="flex items-center gap-1">
                  {t.folder && (
                    <Button size="sm" variant="outline" icon={<FolderOpen className="h-4 w-4" />} onClick={() => setFolder(t.folder)}>
                      Fayllar
                    </Button>
                  )}
                  {can("design.change_designtype") && (
                    <IconButton label="Nomini o'zgartirish" onClick={() => setVariant({ id: t.id, name: t.name })}>
                      <Pencil className="h-4 w-4" />
                    </IconButton>
                  )}
                  {can("design.delete_designtype") && d.types.length > 1 && (
                    <IconButton label="O'chirish" onClick={() => confirm(`«${t.name}» o'chirilsinmi?`) && removeVariant.mutate(t.id)}>
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-4">
          <OfferStatusCard
            kind="design"
            id={d.id}
            offer={d}
            assignee={d.user_detail}
            actions={{ due: d.actions.due, reassign: d.actions.reassign, answer: d.actions.answer }}
            client={m.client.fio}
          />
          <Card title="O'lchov">
            <KV
              items={[
                ["Mijoz", <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/meterings/${m.id}`}>{m.client.fio}</Link>],
                ["Telefon", <PhoneLink value={m.client.phone} />],
                ["Manzil", <AddressLink address={m.address} link={m.address_link} mapUrl={m.map_url} lat={m.lat} lon={m.lon} />],
                ["O'lchov sanasi", dateTime(m.date_time)],
              ]}
            />
          </Card>
          {d.order && (
            <Card title={`Buyurtma №${d.order.order_number}`}>
              <div className="flex flex-wrap gap-2">
                <OrderStatusBadge status={d.order.status} label={d.order.status_label} />
                <DeadlinePill deadline={d.order.deadline} />
              </div>
              <Link to={`/orders/${d.order.id}`} className="mt-3 inline-block text-sm text-brand-700 hover:underline dark:text-brand-300">
                Buyurtmani ochish →
              </Link>
            </Card>
          )}
        </div>
      </div>

      <Confirm
        open={confirmDone}
        onClose={() => setConfirmDone(false)}
        title="Dizayn tayyormi?"
        text="Menejerga xabar boradi — u dizaynni mijozga ko'rsatadi."
        confirmLabel="Ha, tayyor"
        variant="success"
        loading={done.isPending}
        onConfirm={() => done.mutate()}
      />
      <Modal
        open={!!variant}
        onClose={() => setVariant(null)}
        title={variant?.id ? "Variant nomini o'zgartirish" : "Yangi variant"}
        size="sm"
        footer={<Button loading={saveVariant.isPending} onClick={() => saveVariant.mutate()}>Saqlash</Button>}
      >
        <Field label="Nomi">
          <Input value={variant?.name ?? ""} onChange={(e) => setVariant(variant && { ...variant, name: e.target.value })} />
        </Field>
      </Modal>
      {folder && <FolderModal folderId={folder} onClose={() => setFolder(null)} />}
    </div>
  );
}
