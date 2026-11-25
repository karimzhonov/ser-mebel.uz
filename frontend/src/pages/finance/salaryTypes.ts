/** «Oylik varaqlari» (backend payroll/services.py → api/views/payroll.py). Money comes
 * as decimal strings from the sheet view, as numbers in the list. */

export type SheetKind = "oddiy" | "sborka" | "ofis" | "menejer" | "sotuv" | "zamer";
export type SheetStatus = "draft" | "submitted" | "approved";
export type LineSection = "job" | "taken" | "delivered" | "collect" | "deduction" | "car";
export type SheetField = "fixed" | "bonus" | "bonus2" | "late" | "absent" | "instagram";

export interface SheetListRow {
  id: number;
  number: number;
  kind: SheetKind;
  kind_label: string;
  worker: number;
  worker_name: string;
  partners: string[];
  month: string;
  period_start: string;
  period_end: string;
  status: SheetStatus;
  status_label: string;
  version: number;
  returned_note: string;
  earned: number;
  rest: number;
  created_by_name: string;
  approved_by_name: string;
  approved_at: string | null;
  updated_at: string;
}

export interface SheetLine {
  id: number | null;
  section: LineSection;
  order_ref: string;
  order_id: number | null;
  title: string;
  on_date: string | null;
  paid_on: string | null;
  currency: "UZS" | "USD";
  amount: string;
  rate: string | null;
  days: number | null;
  percent: string | null;
  bonus_usd: string | null;
  value: string;
  /** «Bonuslar» row this collect line comes from (its days / % / bonus are final) */
  order_bonus: number | null;
}

/** GET …/order-bonuses/ — «Bonuslar» closed in the sheet's period */
export interface OrderBonusPick {
  matched: boolean;
  rows: {
    order_bonus: number;
    order_ref: string;
    title: string;
    on_date: string | null;
    paid_on: string | null;
    currency: "UZS" | "USD";
    amount: string;
    days: number | null;
    percent: string;
    bonus: string;
    receiver: string;
    on_sheet: number | null;
  }[];
}

export interface SheetAdvance {
  id: number;
  number: number;
  date: string;
  worker_id: number | null;
  worker: string;
  amount: string;
  currency: "UZS" | "USD";
  orig_amount: string | null;
  rate: string | null;
  given_by: string;
  comment: string;
}

export interface SheetMemberRow {
  worker_id: number;
  name: string;
  share: string;
  amount: string;
  advances: string;
  rest: string;
}

export interface SheetTotals {
  earned: { label: string; amount: string }[];
  minus: { label: string; amount: string }[];
  earned_total: string;
  minus_total: string;
  advances_total: string;
  rest: string;
  rest_usd: string | null;
  car_total: string | null;
  instagram_usd: string | null;
}

export interface SalarySheet {
  id: number;
  number: number;
  kind: SheetKind;
  kind_label: string;
  worker_id: number;
  worker: string;
  section: string;
  position: string;
  month: string;
  month_label: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  usd_rate: string;
  fixed: string;
  bonus_percent: string;
  bonus2_percent: string;
  late_days: number;
  late_rate: string;
  late_dates: string;
  absent_days: number;
  absent_rate: string;
  absent_dates: string;
  instagram_count: number;
  note: string;
  fields: SheetField[];
  status: SheetStatus;
  status_label: string;
  version: number;
  lines: SheetLine[];
  sections: { key: LineSection; title: string; total: string }[];
  advances: SheetAdvance[];
  members: SheetMemberRow[];
  totals: SheetTotals;
  returned_note: string;
  warnings: string[];
  created_by: string;
  updated_by: string;
  submitted_by: string;
  submitted_at: string | null;
  approved_by: string;
  approved_at: string | null;
  can: { edit: boolean; submit: boolean; approve: boolean; return: boolean; delete: boolean };
}

export interface OrderBrief {
  client: string;
  status: string;
  total: string;
  currency: "UZS" | "USD";
  total_usd: string | null;
  ready_date: string | null;
}

export interface LineCalc {
  days: number | null;
  percent: string | null;
  bonus_usd: string | null;
  value: string;
}

/** POST …/preview/ — the unsaved form computed by the server; `lines` follow the
 * order of the lines that were sent. */
export interface SheetPreview {
  lines: { calc: LineCalc | null; found: boolean | null; order: OrderBrief | null }[];
  sections: { key: LineSection; title: string; total: string }[];
  members: SheetMemberRow[];
  advances: SheetAdvance[];
  totals: SheetTotals;
}

export interface SheetOptions {
  kinds: { value: SheetKind; label: string; sections: LineSection[]; fields: SheetField[] }[];
  section_titles: Record<LineSection, string>;
  workers: { id: number; name: string; group: string; position: string }[];
  collect_tiers: { days: number; percent: string }[];
  instagram_tiers: { from: number; usd: string }[];
  this_month: string;
  next_month: string;
}
