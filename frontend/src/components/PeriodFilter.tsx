import { Segmented } from "./ui";

export function PeriodFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Segmented
      value={value}
      onChange={onChange}
      options={[
        { value: "", label: "Всё время" },
        { value: "week", label: "Неделя" },
        { value: "month", label: "Месяц" },
        { value: "year", label: "Год" },
      ]}
    />
  );
}
