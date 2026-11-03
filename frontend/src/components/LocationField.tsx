import { useEffect, useState } from "react";
import { AlertTriangle, MapPin, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage, fieldErrors } from "@/api/client";
import { useAction } from "@/api/hooks";
import type { GeoParse } from "@/api/types";
import { cn } from "@/lib/cn";
import { mapHref } from "@/lib/geo";
import { Button, Field, Input, Modal } from "./ui";

type Preview = { state: "idle" } | { state: "loading" } | { state: "ok"; data: GeoParse } | { state: "error"; message: string };

/** What the server makes of a pasted map link / coordinates, checked 400 ms after typing stops. */
function useGeoPreview(text: string): Preview {
  const [preview, setPreview] = useState<Preview>({ state: "idle" });
  useEffect(() => {
    const value = text.trim();
    if (!value) {
      setPreview({ state: "idle" });
      return;
    }
    let alive = true;
    setPreview({ state: "loading" });
    const timer = setTimeout(() => {
      api
        .post<GeoParse>("/geo/parse/", { text: value })
        .then((r) => alive && setPreview({ state: "ok", data: r.data }))
        .catch((e) => {
          if (!alive) return;
          const errs = fieldErrors(e);
          setPreview({ state: "error", message: errs.location || errs.text || errorMessage(e) });
        });
    }, 400);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [text]);
  return preview;
}

/** «Xarita (havola yoki koordinata)»: a Google / Yandex / 2GIS link or "41.31, 69.27". */
export function LocationField({
  value,
  onChange,
  error,
  hint,
  className,
  label = "Xarita (havola yoki koordinata)",
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: string;
  hint?: string;
  className?: string;
  label?: string;
  autoFocus?: boolean;
}) {
  const preview = useGeoPreview(value);
  return (
    <div className={className}>
      <Field label={label} error={error} hint={!value.trim() ? hint : undefined}>
        <Input
          autoFocus={autoFocus}
          placeholder="https://yandex.uz/maps/… yoki 41.311081, 69.279737"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
      {!error && <PreviewLine preview={preview} />}
    </div>
  );
}

function PreviewLine({ preview }: { preview: Preview }) {
  if (preview.state === "idle") return null;
  if (preview.state === "loading") return <div className="muted mt-1 text-xs">Tekshirilmoqda…</div>;
  if (preview.state === "error") return <div className="mt-1 text-xs text-rose-600">{preview.message}</div>;
  const { data } = preview;
  if (data.lat && data.lon) {
    const href = mapHref({ mapUrl: data.map_url, lat: data.lat, lon: data.lon });
    return (
      <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-emerald-700 dark:text-emerald-300">
        <MapPin className="h-3.5 w-3.5" />
        <span className="tabular-nums">
          {data.lat}, {data.lon}
        </span>
        {href && (
          <>
            ·
            <a href={href} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline dark:text-brand-300">
              Yandexda ko'rish
            </a>
          </>
        )}
      </div>
    );
  }
  if (data.short)
    return (
      <div className="mt-1 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300">
        <AlertTriangle className="h-3.5 w-3.5" /> Qisqa havola — nuqta aniqlanmadi, havola saqlanadi
      </div>
    );
  return null;
}

/** Text to start the field with: the saved point, else the pasted link. */
export function locationText(lat?: string | null, lon?: string | null, link?: string | null) {
  return lat && lon ? `${lat}, ${lon}` : link ?? "";
}

type LocationBody = { location?: string; address?: string };

/** Change the address + map point of a lead / metering / order
 * (POST /{invoices|meterings|orders}/{id}/location/). */
export function LocationEditModal({
  resource,
  id,
  address,
  link,
  lat,
  lon,
  invalidate,
  onClose,
}: {
  resource: "invoices" | "meterings" | "orders";
  id: number;
  address: string | null | undefined;
  link: string | null | undefined;
  lat: string | null | undefined;
  lon: string | null | undefined;
  invalidate: string[];
  onClose: () => void;
}) {
  const initialLocation = locationText(lat, lon, link);
  const [form, setForm] = useState({ address: address ?? "", location: initialLocation });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const hasLocation = !!(lat && lon) || !!link;
  const save = useAction(
    (body: LocationBody) =>
      api.post<{ short?: boolean }>(`/${resource}/${id}/location/`, body).then((r) => r.data),
    {
      invalidate,
      onSuccess: (r) => {
        if (r?.short) toast.warning("Qisqa havola — nuqta aniqlanmadi, havola saqlandi");
        else toast.success("Lokatsiya saqlandi");
        onClose();
      },
    },
  );
  const submit = (body: LocationBody) => {
    setErrors({});
    save.mutateAsync(body).catch((e) => setErrors(fieldErrors(e)));
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="Manzil va lokatsiya"
      footer={
        <>
          {hasLocation && (
            <Button
              variant="ghost"
              className={cn("mr-auto text-rose-600")}
              icon={<Trash2 className="h-4 w-4" />}
              disabled={save.isPending}
              onClick={() => submit({ location: "" })}
            >
              Tozalash
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          <Button loading={save.isPending} onClick={() => {
              // A missing `location` keeps the saved point/link and only updates the address;
              // the address is always sent, so emptying it clears it.
              const body: LocationBody = { address: form.address.trim() };
              if (form.location.trim() !== initialLocation.trim()) body.location = form.location.trim();
              submit(body);
            }}>
            Saqlash
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Manzil" error={errors.address}>
          <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </Field>
        <LocationField
          autoFocus
          value={form.location}
          onChange={(location) => setForm({ ...form, location })}
          error={errors.location}
          hint="Telegramdan lokatsiya yuborish ham mumkin: botga lokatsiyani jo'nating va mijozni tanlang."
        />
      </div>
    </Modal>
  );
}
