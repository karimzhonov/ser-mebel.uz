import { DueLabel, DueModal } from "@/components/DueDate";

const INVALIDATE = ["rovers", "orders", "dashboard"];

/** The rover deadline: red when late, muted when nobody set it yet, «(avto)» when automatic. */
export function RoverDueLabel(props: {
  dueDate: string | null | undefined;
  auto?: boolean;
  overdue?: boolean;
  className?: string;
}) {
  return <DueLabel {...props} />;
}

/** The production head sets / moves the deadline (POST /rovers/{id}/due/ {due_date}). */
export function RoverDueModal({
  roverId,
  dueDate,
  onClose,
}: {
  roverId: number;
  dueDate?: string | null;
  onClose: () => void;
}) {
  return (
    <DueModal
      resource="rovers"
      id={roverId}
      dueDate={dueDate}
      title="Rover muddati"
      presets={[3, 5, 7]}
      invalidate={INVALIDATE}
      onClose={onClose}
    />
  );
}
