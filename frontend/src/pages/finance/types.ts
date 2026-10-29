// Moliya (finance) API shapes — backend/api/views/finance.py

export type Role = "admin" | "staff" | "pending" | "blocked";

export interface Member {
  id: number;
  telegram_id: number;
  name: string;
  username: string;
  role: Role;
  role_label: string;
  user: number | null;
  user_detail: { id: number; name: string | null; phone: string } | null;
  is_site_entry: boolean;
  is_feedback: boolean;
  is_bonus_receiver: boolean;
  is_deadline_receiver: boolean;
  is_task_only: boolean;
  has_wallet: boolean;
  joined_at: string;
}

export interface MemberShort {
  id: number;
  telegram_id: number;
  name: string;
  role: Role;
}

export interface FinCategory {
  id: number;
  code: string;
  kind: "expense" | "income" | "internal";
  emoji: string;
  name: string;
  keywords: string[];
  color: string;
  needs_order: boolean;
  no_order: boolean;
  admin_only: boolean;
  excluded: boolean;
  archive: boolean;
  ordering: number;
  is_active: boolean;
}

export interface Operation {
  id: number;
  number: number;
  date: string;
  time: string | null;
  kind: "income" | "expense";
  kind_label: string;
  amount: string;
  currency: "UZS" | "USD";
  orig_amount: string | null;
  rate: string | null;
  category: number;
  category_detail: FinCategory;
  order: number | null;
  order_ref: string;
  comment: string;
  worker: string;
  pay_type: "" | "Avans" | "Oylik";
  member: number;
  member_detail: MemberShort;
  author_detail: MemberShort | null;
  site_user_detail: { id: number; name: string | null; phone: string } | null;
  has_receipt: boolean;
  pair_number: number | null;
  handover: "" | "accepted" | "deleted";
  is_deleted: boolean;
  source: "bot" | "site" | "import";
  source_label: string;
  created_at: string;
  updated_at: string;
}

export interface CatItem {
  code: string;
  name: string;
  emoji: string;
  color: string;
  amount: number;
  count: number;
}

export interface Summary {
  date_from: string;
  date_to: string;
  member: Member | null;
  expense: number;
  income: number;
  balance: number;
  given_to_staff: number;
  boss_personal: number;
  home: number;
  transfers: number;
  count: number;
  expense_by_category: CatItem[];
  income_by_category: CatItem[];
  salary_by_worker: { name: string; amount: number }[];
  months: { month: string; label: string; income: number; expense: number }[];
  wallet_balance: number | null;
  usd_rate: number;
}

export interface WalletRow {
  member: Member;
  balance: number;
  period_income: number;
  period_expense: number;
  last_day: string | null;
  report_month: string;
  report_submitted: boolean;
}

export interface FinOrder {
  ref: string;
  client: string;
  phone: string;
  bucket: "yangi" | "jarayonda" | "kutish" | "yakun" | "tugadi";
  status_label: string;
  order_id: number | null;
  manual: boolean;
  total: number;
  currency: string;
  paid: number | null;
  rest: number | null;
  price_uzs: number;
  spent: number;
  collected: number;
  profit: number | null;
  spent_percent: number | null;
  end_date: string | null;
  ready_date: string | null;
  by_category: { code: string; amount: number }[];
  operations?: Operation[];
  bonus?: Bonus | null;
}

export interface MonthReport {
  id: number;
  member: number;
  member_detail: MemberShort;
  month: string;
  submitted_at: string;
  balance: string;
  note: string;
}

export interface MoneyRequest {
  id: number;
  number: number;
  member: number;
  member_detail: MemberShort;
  amount: string;
  currency: string;
  orig_amount: string | null;
  reason: string;
  status: "pending" | "given" | "rejected";
  status_label: string;
  answer: string;
  answered_by_detail: MemberShort | null;
  operation_number: number | null;
  created_at: string;
  answered_at: string | null;
}

export interface Bonus {
  id: number;
  order_ref: string;
  client: string;
  description: string;
  total: string;
  currency: string;
  ready_date: string;
  rest: string | null;
  got_text: string;
  status: "waiting" | "done" | "expired";
  status_label: string;
  paid_date: string | null;
  days: number | null;
  percent: string | null;
  bonus: string | null;
  note: string;
  receiver: string;
}

export interface Warranty {
  id: number;
  order_ref: string;
  client: string;
  ready_date: string | null;
  given: boolean;
  given_at: string | null;
  given_by: string;
  note: string;
}

export interface SiteEntry {
  id: number;
  code: string;
  date: string;
  order_ref: string;
  client: string;
  sum_text: string;
  taken_by: string;
  rest_text: string;
  is_done: boolean;
  done_at: string | null;
  done_by: string;
}

export interface Feedback {
  id: number;
  order_ref: string;
  client: string;
  phone: string;
  ready_date: string | null;
  asked_date: string | null;
  status: "scheduled" | "asked" | "received";
  status_label: string;
  received_date: string | null;
  received_by: string;
  text: string;
  screenshot_url: string;
}

export interface Issue {
  level: "h" | "m" | "l";
  title: string;
  detail: string;
  fix: string;
}

export interface FinMe {
  member: Member | null;
  view_all: boolean;
  balance: number | null;
}

export interface Worker {
  id: number;
  group: string;
  name: string;
  position: string;
  ordering: number;
  is_active: boolean;
}

export interface Car {
  id: number;
  name: string;
  ordering: number;
  is_active: boolean;
}

export interface ManualOrder {
  id: number;
  ref: string;
  client: string;
  phone: string;
  price: string;
  is_closed: boolean;
  opened: string | null;
  closed: string | null;
}

export interface WorkerListItem {
  name: string;
  group: string;
  position: string;
  is_active: boolean;
  in_catalog: boolean;
  total: number;
  count: number;
}

export interface WorkerCard {
  name: string;
  group: string;
  position: string;
  in_catalog: boolean;
  advance: number;
  salary: number;
  other: number;
  total: number;
  all_time: number;
  count: number;
  last_date: string | null;
  by_giver: { name: string; amount: number; count: number }[];
  rows: {
    id: number;
    number: number;
    date: string;
    time: string;
    amount: number;
    currency: string;
    orig_amount: number | null;
    member: string;
    comment: string;
    pay_type: string;
  }[];
}

export interface WorkerCardResponse {
  date_from: string;
  date_to: string;
  workers: WorkerListItem[];
  card: WorkerCard | null;
}
