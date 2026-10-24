export type Tone = "ok" | "info" | "warn" | "danger" | "idle" | "primary";

export interface Money {
  amount: number;
  currency: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Me {
  id: number;
  phone: string;
  name: string | null;
  telegram_id: number | null;
  is_superuser: boolean;
  permissions: string[];
  telegram_link: string;
}

export interface UserShort {
  id: number;
  name: string | null;
  phone: string;
}

export interface ClientShort {
  phone: string;
  fio: string;
}

export interface Client extends ClientShort {
  created_at: string;
  orders_count?: number;
}

export interface EnumItem {
  value: string | number;
  label: string;
  tone: Tone;
  icon: string;
  archive?: boolean;
}

export interface Meta {
  order_statuses: EnumItem[];
  metering_statuses: EnumItem[];
  solutions: EnumItem[];
  inventory_type_kinds: { value: number; label: string }[];
  count_names: { value: string; label: string }[];
  currencies: string[];
  default_currency: string;
  warning_order_days: number;
  usd_rate: number;
  site_title: string;
}

export interface Deadline {
  days: number | null;
  level: Tone;
  text: string;
}

export interface OrderSummary {
  id: number;
  order_number: number;
  status: string;
  status_label: string;
  deadline: Deadline;
  money_left: Money | null;
}

export interface Invoice {
  id: number;
  client: ClientShort;
  create_date: string;
  update_date: string;
  desc: string | null;
  solution: number | null;
  solution_label: string | null;
  is_editable: boolean;
  metering_id: number | null;
}

export interface MeteringShort {
  id: number;
  client: ClientShort;
  address: string | null;
  address_link: string | null;
  date_time: string | null;
  status: string;
  folder: number | null;
}

export interface Metering {
  id: number;
  client: ClientShort;
  status: string;
  status_label: string;
  date_time: string | null;
  address: string | null;
  address_link: string | null;
  desc: string | null;
  create_date: string;
  invoice: number | null;
  folder: number | null;
  design: { id: number; done: boolean; confirm: boolean } | null;
  price: { id: number; done: boolean } | null;
  order: OrderSummary | null;
  is_editable: boolean;
  actions?: Record<
    "edit" | "dont_need" | "other_day" | "metering_done" | "create_design" | "create_price",
    boolean
  >;
}

export interface DesignType {
  id: number;
  name: string;
  folder: number | null;
  created_at: string;
}

export interface Design {
  id: number;
  metering: MeteringShort;
  created_at: string;
  done: boolean;
  confirm: boolean;
  types: DesignType[];
  order: OrderSummary | null;
  actions: { done: boolean; add_type: boolean; create_order: boolean };
}

export interface ObjectType {
  id: number;
  name: string;
  count_name: string;
  count_label: string;
}

export interface Inventory {
  id: number;
  name: string;
  type: number;
  price: Money | null;
}

export interface InventoryType {
  id: number;
  name: string;
  obj: number | null;
  type: number;
  type_label: string;
  ordering: number;
  inventories: Inventory[];
}

export interface CalculationItem {
  id: number;
  inventory_type: number;
  inventory: number;
  inventory_name: string;
  count: number;
  price: Money | null;
}

export interface Calculation {
  id: number;
  name: string;
  count: number | null;
  obj: number;
  amount: Money | null;
  items: CalculationItem[];
}

export interface Price {
  id: number;
  metering: MeteringShort | null;
  price: Money | null;
  done: boolean;
  desc: string | null;
  created_at: string;
  folder: number | null;
  order: OrderSummary | null;
  calculations?: Calculation[];
  actions?: { edit: boolean; done: boolean };
}

export interface Factory {
  id: number;
  name: string;
  address: string;
  phone: string;
  ordering: number;
}

export interface Order {
  id: number;
  order_number: number;
  client: ClientShort | null;
  factory: Factory;
  address: string;
  address_link: string | null;
  desc: string | null;
  status: string;
  status_label: string;
  reception_date: string;
  end_date: string | null;
  deadline: Deadline;
  metering: number | null;
  folder: number | null;
  price?: Money | null;
  lost_money?: Money | null;
  discount?: number;
  total_price?: Money | null;
  money_left?: Money | null;
}

export interface ProductionRow {
  id: number;
  done: boolean;
  square: number;
  folder: number | null;
  price?: Money | null;
}

export interface OrderDetail extends Order {
  design_type: { id: number; name: string; folder: number | null } | null;
  production: {
    detailing: {
      id: number;
      done: boolean;
      working_done: boolean;
      square: number;
      painter_square: number;
      rover_square: number;
      folder: number | null;
    } | null;
    rover: ProductionRow | null;
    painter: (ProductionRow & { type: string | null }) | null;
    assembly: (ProductionRow & { installing_done: boolean; user: UserShort | null }) | null;
  };
  actions: {
    edit: boolean;
    detailing: boolean;
    next_status: boolean;
    next_status_label: string | null;
    go_to_assembly: boolean;
    add_expense: boolean;
    edit_price: boolean;
  };
}

export interface ProductionOrder {
  id: number;
  order_number: number;
  client: ClientShort | null;
  address: string;
  address_link: string | null;
  status: string;
  status_label: string;
  deadline: Deadline;
  end_date: string | null;
  folder: number | null;
}

export interface ProductionItem {
  id: number;
  order: ProductionOrder;
  created_at: string;
  done: boolean;
  square: number;
  folder: number | null;
  price?: Money | null;
  // detailing
  working_done?: boolean;
  painter_square?: number;
  rover_square?: number;
  // painter
  type?: number | null;
  type_detail?: { id: number; name: string } | null;
  // assembly
  installing_done?: boolean;
  user?: number | null;
  user_detail?: UserShort | null;
  actions: Record<string, boolean>;
}

export interface PainterType {
  id: number;
  name: string;
  price: Money;
  user: number | null;
  user_detail: UserShort | null;
}

export interface Category {
  id: number;
  name: string;
  created_at: string;
}

export interface MoneyRecord {
  id: number;
  cost: Money;
  category: number;
  category_name: string;
  desc: string | null;
  created_at: string;
  user_detail: UserShort | null;
  order?: number | null;
  order_detail?: { id: number; order_number: number; client: string | null } | null;
}

export interface MoneyStats {
  currency: string;
  total: number;
  count: number;
  by_category: { id: number; label: string; amount: number; share: number }[];
  timeline: { date: string; value: number }[];
}

export interface StatusStats {
  total: number;
  by_status?: { key: string; count: number }[];
  by_solution?: { key: string; count: number }[];
  warnings?: { key: string; count: number }[];
  timeline: { date: string; value: number }[];
}

export interface HistoryEntry {
  date: string;
  type: "created" | "changed" | "deleted";
  user: UserShort | null;
  changes: { field: string; old: string | null; new: string | null }[];
}

export interface FolderFile {
  id: number;
  name: string;
  url: string;
  size: number;
  mime_type: string | null;
  is_image: boolean;
  thumbnail: string | null;
  uploaded_at: string;
  owner: UserShort | null;
}

export interface Folder {
  id: number;
  name: string;
  parent: number | null;
  breadcrumbs: { id: number; name: string }[];
  folders: { id: number; name: string; file_count: number }[];
  files: FolderFile[];
}

export interface Message {
  id: number;
  author: UserShort;
  message: string;
  created_at: string;
}

export interface KanbanColumn<C> {
  key: string;
  title: string;
  icon: string;
  accent: Tone;
  collapsed: boolean;
  count: number;
  cards: C[];
  more: number;
}

export interface Board {
  id: "orders" | "meterings" | "callcenter";
  label: string;
  total: number;
  columns: KanbanColumn<any>[];
}

export interface StaffUser {
  id: number;
  phone: string;
  name: string | null;
  telegram_id: number | null;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  groups: number[];
  last_login: string | null;
}

export interface Overview {
  range: { from: string | null; to: string | null };
  monthly: boolean;
  funnel: {
    steps: { key: string; label: string; count: number; conversion: number | null }[];
    total_conversion: number | null;
    cancelled: number | null;
  } | null;
  orders: {
    by_status: { key: string; count: number }[];
    active: number;
    overdue: number;
    due_soon: number;
    new: number;
    done: number;
    deadlines: { id: number; number: number; client: string; status: string; end_date: string; deadline: Deadline }[];
    factories: { name: string; count: number }[];
  } | null;
  money: { contracts: Money[]; paid: Money[]; debt: Money[]; debtors: number } | null;
  accounting: { currency: string; income: number | null; expense: number | null; profit: number | null } | null;
  production: {
    stages: { key: string; label: string; count: number; square: number; link: string }[];
    assemblers: { user: UserShort | null; count: number; square: number }[] | null;
  } | null;
  meterings: {
    missed: number;
    today: number;
    upcoming: { id: number; client: string; phone: string; address: string; when: string }[];
  } | null;
  call_center: { unanswered: number; callback: number } | null;
  timeline: { series: string[]; points: Record<string, number | string>[] };
}
