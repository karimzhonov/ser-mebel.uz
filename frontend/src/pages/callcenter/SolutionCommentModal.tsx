import { useState } from "react";
import { Button, Field, Modal, Textarea } from "@/components/ui";

/** Owner's rule: a call result is saved only with a comment (backend: set_invoice_solution). */
export function SolutionCommentModal({
  label,
  loading,
  onSubmit,
  onClose,
}: {
  label: string;
  loading?: boolean;
  onSubmit: (comment: string) => void;
  onClose: () => void;
}) {
  const [comment, setComment] = useState("");
  const ok = !!comment.trim();
  const send = () => ok && !loading && onSubmit(comment.trim());
  return (
    <Modal
      open
      onClose={onClose}
      title={`Qo'ng'iroq natijasi · ${label}`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Bekor qilish</Button>
          <Button disabled={!ok} loading={loading} onClick={send}>
            Saqlash
          </Button>
        </>
      }
    >
      <Field label="Izoh" hint="Majburiy: mijoz bilan nima gaplashildi, nima dedi">
        <Textarea
          autoFocus
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
          }}
        />
      </Field>
    </Modal>
  );
}
