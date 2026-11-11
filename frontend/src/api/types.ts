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
  /** the omborchi: sees only the «Ombor» section */
  is_warehouse_keeper: boolean;
  /** lavozim (group) names, e.g. «Menejer», «Bosh menejer» */
  lavozims?: string[];
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
  /** The site bot's @username (TELEGRAM_BOT_USERNAME), without the @. */
  telegram_bot: string;
  /** CRM: where a lead came from (Telegram, Instagram, …) — required on a new ariza. */
  lead_sources?: { value: string; label: string }[];
}

/** A saved map point (strings with 6 decimals, "41.311081") + the Yandex link the API builds:
 * the exact point, else a text search for the address; null when there is nothing to show. */
export interface Located {
  lat: string | null;
  lon: string | null;
  map_url: string | null;
}

/** POST /geo/parse/ — a pasted map link / coordinates, as the server understands it. */
export interface GeoParse {
  lat: string | null;
  lon: string | null;
  map_url: string | null;
  /** a short link (maps.app.goo.gl, yandex …/-/…): kept as a link, no point read from it */
  short: boolean;
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

export interface Invoice extends Located {
  id: number;
  client: ClientShort;
  create_date: string;
  update_date: string;
  desc: string | null;
  solution: number | null;
  solution_label: string | null;
  is_editable: boolean;
  metering_id: number | null;
  /** the lead's zamer (latest) in short — null when none yet */
  metering?: InvoiceMetering | null;
  source: string | null;
  source_label: string | null;
  assigned_to: UserRef | null;
  created_by: UserRef | null;
  next_task: { id: number; text: string; due_at: string } | null;
  open_tasks: number;
  /** the lead's approximate price (to tell the client) */
  estimate?: { id: number; stage: string; stage_label: string; total: Money | null } | null;
  /** an active lead (new / re-phone / info / location) with no open task */
  needs_task: boolean;
  address?: string;
  address_link?: string | null;
}

/* ---------------------------------------------------------------- CRM */

export interface UserRef {
  id: number;
  name: string;
}

export interface Assignee extends UserRef {
  has_telegram: boolean;
}

/** The lead a task belongs to (InvoiceTaskSerializer.invoice). */
export interface TaskLead {
  id: number;
  client: ClientShort;
  source: string | null;
  source_label: string | null;
  solution: number | null;
  solution_label: string | null;
  /** the lead's address — prefills an O'lchov created from the task */
  address?: string | null;
  /** the lead has a saved map point / link (the metering copies it) */
  has_point?: boolean;
}

export interface InvoiceTask {
  id: number;
  text: string;
  due_at: string;
  is_done: boolean;
  done_at: string | null;
  created_at: string;
  assigned: UserRef | null;
  invoice: TaskLead;
  created_by: UserRef | null;
}

/** POST /invoice-tasks/{id}/done/ — the finished task (top level) + what the outcome did. */
export interface TaskDoneResult extends InvoiceTask {
  /** the reminder created for the next call (re_phone / given_* with a time), else null */
  next_task: InvoiceTask | null;
  /** how many other open tasks of the lead were closed (closing outcomes) */
  closed_tasks: number;
}

export interface TimelineEntry {
  type: "created" | "note" | "task_created" | "task_done" | "metering" | "order";
  at: string;
  author: UserRef | null;
  /** for type=note: note | solution | assigned | source | location | metering (meta.event) */
  kind: string | null;
  text: string;
  meta: Record<string, unknown>;
  task: { id: number; text: string; due_at: string; is_done: boolean; assigned: UserRef | null } | null;
  link: { kind: "metering" | "order"; id: number } | null;
}

export interface LeadBoardColumn {
  key: string;
  title: string;
  tone: Tone;
  /** the solution a card gets when dropped here (null = «Yangi») */
  solution: number | null;
  droppable: boolean;
  collapsed: boolean;
  count: number;
  cards: Invoice[];
}

export interface LeadBoard {
  columns: LeadBoardColumn[];
}

export interface TaskAgenda {
  overdue: InvoiceTask[];
  today: InvoiceTask[];
  upcoming: InvoiceTask[];
}

export interface MeteringShort extends Located {
  id: number;
  client: ClientShort;
  address: string | null;
  address_link: string | null;
  date_time: string | null;
  status: string;
  folder: number | null;
}

/** a person on a zamer (measurer / operator); the API sends UserShort, name may be empty */
export interface PersonRef {
  id: number;
  name: string | null;
  phone?: string;
}

export type MeteringNextStep = "" | "design_price" | "price";

/** InvoiceSerializer.metering — the zamer of a lead, in short */
export interface InvoiceMetering {
  id: number;
  status: string;
  status_label: string;
  date_time: string | null;
  measurer: PersonRef | null;
  result_note: string;
  cancel_reason: string;
  next_step: MeteringNextStep;
  folder: number | null;
  /** stage 2: who shows the design / price to the client */
  manager?: PersonRef | null;
  client_result?: ClientResult;
  design?: OfferBrief | null;
  price?: OfferBrief | null;
}

export type MeteringActionKey =
  | "edit"
  | "measured"
  | "reschedule"
  | "cancel"
  | "finish"
  | "upload"
  | "set_measurer"
  | "create_design"
  | "create_price"
  | "assign"
  // legacy keys (older API): metering_done = measured, other_day = reschedule, dont_need = cancel
  | "metering_done"
  | "other_day"
  | "dont_need";

export interface Metering extends Located {
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
  design: { id: number; done: boolean; confirm: boolean; user: UserShort | null } | null;
  /** stage «estimate» = the lead's approximate price, before «Bajarildi» */
  price: { id: number; done: boolean; user: UserShort | null; stage?: OfferStage } | null;
  order: OrderSummary | null;
  is_editable: boolean;
  /** who goes to measure (null = not assigned) */
  measurer?: PersonRef | null;
  /** the call-centre operator of the lead (or whoever created the zamer) */
  operator?: PersonRef | null;
  measured_at?: string | null;
  done_at?: string | null;
  result_note?: string;
  next_step?: MeteringNextStep;
  cancel_reason?: string;
  /** open and its time passed (+ grace) — the measurer has not answered */
  is_overdue?: boolean;
  rev?: number;
  /** detail only: files in the zamer folder tree */
  file_count?: number;
  actions?: Partial<Record<MeteringActionKey, boolean>>;
}

/** GET /meterings/agenda/ — one measurer's day plan */
export interface MeteringAgenda {
  counts: { overdue: number; today: number; tomorrow: number; week: number; waiting: number; archive: number };
  overdue: Metering[];
  today: Metering[];
  tomorrow: Metering[];
  week: Metering[];
  waiting: Metering[];
}

/** GET /meterings/measurers/ */
export interface MeasurerList {
  items: UserShort[];
  /** preselect this one (the only measurer), else null */
  default: number | null;
  /** set when there is no measurer — a zamer can then be created without one */
  hint?: string;
}

/* ---------------------------------------------------- stage 2: dizayn va narx */

export type OfferKind = "design" | "price";

/** work → review (at the client) → approved / declined; cancelled */
/* "waiting" is a legacy value only (old rows); nothing new creates it */
/** «estimate»: a Price only — the approximate price on a lead, before the zamer is finished */
export type OfferStage = "waiting" | "work" | "review" | "approved" | "declined" | "cancelled" | "estimate";

export type ClientResult = "" | "agreed" | "design_declined" | "price_declined";

/** design: approved | changes | declined; price: approved | recalc | declined */
export type OfferAnswerKind = "approved" | "changes" | "recalc" | "declined";

export interface OfferAnswer {
  id: number;
  kind: OfferKind;
  round: number;
  answer: OfferAnswerKind;
  answer_label?: string;
  comment: string;
  due_at: string | null;
  by: PersonRef | null;
  created_at: string;
}

/** a design / price in short (lead card, «Mijozga ko'rsatish» rows) */
export interface OfferBrief {
  id: number;
  stage: OfferStage;
  stage_label: string;
  due_at: string | null;
  done_at?: string | null;
  is_overdue: boolean;
  user: PersonRef | null;
  round: number;
  last_comment: string | null;
  /** design only: the variants (each has its own folder) */
  types?: DesignType[];
  /** price only */
  price?: Money | null;
  folder?: number | null;
}

/** fields Design and Price share in stage 2 */
export interface OfferFields {
  stage: OfferStage;
  stage_label: string;
  due_at: string | null;
  done_at: string | null;
  round: number;
  rev: number;
  is_overdue: boolean;
  manager: PersonRef | null;
  measurer: PersonRef | null;
  /** the manager's last «O'zgartirish» / «Qayta hisoblash» comment */
  last_comment: string | null;
  client_result: ClientResult;
  /** the measurer's note (metering.result_note) */
  result_note?: string;
  /** detail only */
  answers?: OfferAnswer[];
}

export interface OfferAgendaCounts {
  overdue: number;
  today: number;
  work: number;
  review: number;
  archive?: number;
}

/** GET /designs/agenda/, /prices/agenda/ */
export interface OfferAgenda<T> {
  counts: OfferAgendaCounts;
  overdue: T[];
  today: T[];
  work: T[];
  review: T[];
}

/** GET /meterings/presentations/ — one client the manager shows a design / price to */
export interface PresentationRow {
  metering: MeteringShort;
  design: OfferBrief | null;
  price: OfferBrief | null;
  manager: PersonRef | null;
  waiting_for: "design" | "price" | null;
  is_overdue: boolean;
}

export interface Presentations {
  counts: { review: number; overdue: number; working: number; order_ready: number };
  review: PresentationRow[];
  working: PresentationRow[];
  order_ready: PresentationRow[];
}

/** GET /meterings/assignees/ */
export interface MeteringAssignees {
  designers: UserShort[];
  /** who may calculate the price = the managers (Menejer + Bosh menejer) */
  pricers: UserShort[];
  /** set when nobody holds «Dizayner» / «Menejer» — what to do about it */
  designer_hint?: string;
  pricer_hint?: string;
  managers?: UserShort[];
  default_manager?: number | null;
  /** the only designer, preselected */
  default_designer?: number | null;
  defaults?: { design_due_at: string; price_due_at: string };
  /** set when nobody holds «Menejer» */
  hint?: string;
}

export interface DesignType {
  id: number;
  name: string;
  folder: number | null;
  created_at: string;
}

export interface Design extends OfferFields {
  id: number;
  metering: MeteringShort;
  created_at: string;
  done: boolean;
  confirm: boolean;
  user_detail: UserShort | null;
  types: DesignType[];
  order: OrderSummary | null;
  /** detail only: files in the variant folders */
  file_count?: number;
  actions: { done: boolean; add_type: boolean; create_order: boolean; due?: boolean; reassign?: boolean; answer?: boolean };
}

export interface ObjectType {
  id: number;
  name: string;
  count_name: string;
  count_label: string;
  /** decor: the client's PDF shows m²; other furniture shows its size */
  show_area: boolean;
  /** hidden from the catalog and from new furniture; old calculations keep it */
  archived: boolean;
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
  inventory_type_name: string;
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
  room: number | null;
  note: string;
  color: string;
  /** "" = the object type's own unit */
  unit: "" | "kv" | "pog";
  /** size in mm */
  height: number | null;
  width: number | null;
  depth: number | null;
  /** decimals come as strings */
  auto_amount: string | null;
  manual_amount: string | null;
  amount: Money | null;
  items: CalculationItem[];
  accessories: Accessory[];
}

export interface Accessory {
  id: number;
  inventory: number | null;
  /** the catalog type («Musor yashik») when picked from the catalog */
  type_name: string;
  name: string;
  count: number;
  price: number;
  amount: number;
  image: number | null;
  thumbnail: string | null;
}

export interface PriceVersion {
  id: number;
  number: number;
  label: string;
  total: number;
  created_at: string;
  created_by: string | null;
}

export interface RoomType {
  id: number;
  name: string;
  icon: string;
  ordering: number;
  /** empty = any furniture fits */
  object_types: number[];
}

export interface RoomImage {
  id: number;
  file: number;
  /** the furniture this picture shows; null = the whole room */
  calculate: number | null;
  name: string;
  thumbnail: string | null;
}

export interface Room {
  id: number;
  name: string;
  room_type: number;
  room_type_name: string;
  icon: string;
  ordering: number;
  images: RoomImage[];
}

/** The offer exactly as the Excel / PDF print it. */
export interface OfferSheet {
  client: string;
  estimator: string;
  date: string;
  variant: string;
  currency: string;
  total: number;
  rooms: {
    id: number | null;
    name: string;
    room_type: string;
    icon: string;
    images: number;
    total: number;
    items: {
      id: number;
      name: string;
      object: string;
      count: number | null;
      count_text: string;
      size_text: string;
      note: string;
      color: string;
      manual: boolean;
      auto_amount: number | null;
      amount: number;
      params: { label: string; value: string }[];
      /** params + colour / accessories / extra, as the PDF prints them */
      lines: { label: string; value: string }[];
      images: number;
    }[];
  }[];
}

export interface Price extends Partial<OfferFields> {
  id: number;
  metering: MeteringShort | null;
  price: Money | null;
  done: boolean;
  desc: string | null;
  created_at: string;
  folder: number | null;
  user_detail: UserShort | null;
  order: OrderSummary | null;
  client_title: string;
  variant: string;
  calculations?: Calculation[];
  rooms?: Room[];
  sheet?: OfferSheet;
  versions?: PriceVersion[];
  /** the order is in detailing or later: nothing can change */
  locked?: boolean;
  /** design_price: days the pricer gets once the design is approved */
  duration_days?: number;
  /** delete: a lead's approximate price, until the zamer is finished */
  actions?: { edit: boolean; done: boolean; due?: boolean; reassign?: boolean; answer?: boolean; delete?: boolean };
  /** the lead (ariza) whose approximate price this is */
  invoice?: number | null;
}

export interface Factory {
  id: number;
  name: string;
  address: string;
  phone: string;
  ordering: number;
}

export interface Order extends Located {
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
  /** rover only: new | checking | done */
  state?: "new" | "checking" | "done" | null;
}

export interface OrderDetail extends Order {
  /** the advance entered at creation, waiting for the boss («Avans tasdiqlash») */
  advance_pending?: { id: number; amount: string; currency: string } | null;
  /** the zamer's price calculation; after the order only the bosh menejer edits it */
  calculation?: { id: number; can_edit: boolean } | null;
  design_type: { id: number; name: string; folder: number | null } | null;
  production: {
    detailing: {
      id: number;
      done: boolean;
      working_done: boolean;
      square: number;
      painter_square: number;
      rover_square: number;
      due_at: string | null;
      folder: number | null;
    } | null;
    rover: ProductionRow | null;
    painter: (ProductionRow & { type: string | null; waiting_rover: boolean }) | null;
    assembly: (ProductionRow & { installing_done: boolean; user: UserShort | null }) | null;
  };
  actions: {
    edit: boolean;
    detailing: boolean;
    next_status: boolean;
    next_status_label: string | null;
    go_to_assembly: boolean;
    finance: boolean;
    edit_price: boolean;
  };
}

export interface ProductionOrder extends Located {
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
  // rover
  state?: "new" | "checking" | "assembled" | "done";
  state_label?: string;
  // painter
  started_at?: string | null;
  done_at?: string | null;
  done_by_detail?: UserShort | null;
  painter_detail?: UserShort | null;
  submitted_at?: string | null;
  submitted_by_detail?: UserShort | null;
  checked_at?: string | null;
  checked_by_detail?: UserShort | null;
  note?: string;
  due_date?: string | null;
  due_auto?: boolean;
  due_set_at?: string | null;
  due_set_by_detail?: UserShort | null;
  overdue?: boolean;
  // detailing
  working_done?: boolean;
  painter_square?: number;
  rover_square?: number;
  due_at?: string | null;
  // painter
  type?: number | null;
  type_detail?: { id: number; name: string } | null;
  // assembly
  finished_at?: string | null;
  finished_by_detail?: UserShort | null;
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

export interface StatusStats {
  total: number;
  by_status?: { key: string; count: number }[];
  by_solution?: { key: string; count: number }[];
  warnings?: { key: string; count: number }[];
  timeline: { date: string; value: number }[];
  /** orders: live orders paid under 65% (null without the price permission) */
  underpaid?: number | null;
}

export interface HistoryEntry {
  date: string;
  type: "created" | "changed" | "deleted";
  user: UserShort | null;
  changes: { field: string; old: string | null; new: string | null }[];
}

export interface FolderFile {
  id: number;
  download_name: string | null;
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
  /** own rights left from the old per-person switches (rights come from the lavozim now) */
  personal_rights?: { key: string; label: string }[];
}

/** GET /groups/ — a role (Django group) */
export interface StaffGroup {
  id: number;
  name: string;
  /** number of members */
  member_count?: number;
  members_count?: number;
  user_count?: number;
  /** managed elsewhere (the keeper group «Omborchi» — on the Ombor page): no rename/delete/access/member edits */
  locked?: boolean;
}

/** GET /groups/merge-plan/ — old groups to move into the lavozims (superuser) */
export interface GroupMergePlan {
  items: {
    group: { id: number; name: string; member_count: number; locked?: boolean };
    suggested: { id: number; name: string } | null;
    reason: string;
    /** optional extras the backend may send: a plain rename / «add to personal rights» suggestion */
    action?: string;
    rename_to?: string;
    to_personal?: boolean;
  }[];
  targets: { id: number; name: string }[];
}

/** GET /groups/{id}/merge-preview/?target= */
export interface GroupMergePreview {
  members: (Pick<StaffUser, "id" | "phone" | "name"> | string)[];
  add_to_target: { key: string; label: string }[];
  target_member_count: number;
}

/** POST /groups/{id}/merge-into/ */
export interface GroupMergeResult {
  moved_members: number;
  added_permissions: string[];
  deleted: string;
}

export type AccessLevel = "none" | "view" | "edit";

export interface AccessSection {
  key: string;
  /** menu group: Sotuv, O'lchov, HR … */
  title: string;
  label: string;
  hint: string;
  /** false = view-only here (e.g. the warehouse: only the keeper books) */
  can_edit: boolean;
  is_flag?: boolean;
  /** the person's own level; "custom" = set by hand in the old admin */
  level: AccessLevel | "custom";
  /** person only: what the person's groups give */
  from_groups?: AccessLevel | "custom";
}

/** GET /users/{id}/access/ and /groups/{id}/access/ (a group has no is_superuser / is_keeper) */
export interface UserAccess {
  is_superuser?: boolean;
  is_keeper?: boolean;
  sections: AccessSection[];
}

export interface Overview {
  range: { from: string | null; to: string | null };
  monthly: boolean;
  /** the bosh menejer: only Sotuv + O'lchov blocks are sent */
  sales_only?: boolean;
  underpaid?: {
    threshold: number;
    count: number;
    items: { id: number; number: number; client: string; phone: string; status: string; paid_pct: number; total: Money; paid: Money }[];
  } | null;
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
    upcoming: { id: number; client: string; phone: string; address: string; when: string; map_url?: string | null; lat?: string | null; lon?: string | null }[];
  } | null;
  call_center: { unanswered: number; callback: number } | null;
  warehouse: {
    products: number;
    stock_value: number;
    stock_value_usd: number | null;
    period_in: number;
    period_out: number;
    low_count: number;
    low_stock: { id: number; name: string; quantity: number; min_quantity: number; unit: string }[];
  } | null;
  hr: {
    date: string;
    now: string;
    holiday: string | null;
    expected: number;
    counts: Record<string, number>;
    attention: { id: number; name: string; status: "late" | "absent" | "waiting"; in_time: string; late_min: number | null; group: string }[];
  } | null;
  wallets: {
    currency: string;
    total: number;
    count: number;
    rows: { id: number; name: string; role: string; balance: number }[];
  } | null;
  timeline: { series: string[]; points: Record<string, number | string>[] };
  /** «Zamer · Dizayn · Narx» — superuser / metering.manage_metering only */
  pipeline?: SalesPipeline | null;
}

export type PipelineRole = "zamerchi" | "dizayner" | "narxchi" | "menejer";

export interface SalesPipeline {
  counts: {
    zamer_today: number;
    zamer_overdue: number;
    zamer_waiting: number;
    design_work: number;
    design_overdue: number;
    design_review: number;
    price_work: number;
    price_overdue: number;
    price_review: number;
    order_ready: number;
  };
  overdue: { kind: string; id: number; client: string; person: string | PersonRef | null; due_at: string | null; late_hours: number | null; url?: string | null }[];
  load: { role: PipelineRole; person: { id: number; name: string } | null; open: number; overdue: number }[];
}
