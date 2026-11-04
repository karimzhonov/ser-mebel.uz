import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { api } from "@/api/client";
import { useAction } from "@/api/hooks";
import type { Price } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button, Field, Modal, Textarea } from "@/components/ui";
import { OfferAgenda } from "./offers/OfferAgenda";

/** «Narx hisoblash» — the pricer's agenda (deadline first, overdue in red) + a price without a zamer. */
export function PricesPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [desc, setDesc] = useState("");
  const create = useAction(() => api.post<Price>("/prices/", { desc }).then((r) => r.data), {
    success: "Hisob-kitob yaratildi",
    invalidate: ["prices"],
    onSuccess: (p) => navigate(`/prices/${p.id}`),
  });

  return (
    <>
      <OfferAgenda
        kind="price"
        actions={
          can("price.add_price") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              O'lchovsiz hisob-kitob
            </Button>
          )
        }
      />
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="O'lchovsiz hisob-kitob"
        size="sm"
        footer={<Button loading={create.isPending} onClick={() => create.mutate()}>Yaratish</Button>}
      >
        <Field label="Tavsif" hint="Masalan, mijoz ismi yoki obyekt">
          <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} />
        </Field>
      </Modal>
    </>
  );
}

export { PriceDetailPage } from "./PriceDetail";
