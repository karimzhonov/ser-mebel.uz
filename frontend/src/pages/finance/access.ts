/** Who may open each finance page: one map for the sidebar, the routes and the tabs.
 * It mirrors the API rules (backend/api/views/finance.py), which stay the real check. */
export const VIEW_ALL = "accounting.view_all_operations";

export type FinancePage =
  | "summary"
  | "operations"
  | "debts"
  | "wallets"
  | "orders"
  | "requests"
  | "reports"
  | "workerCard"
  | "advances"
  | "followup"
  | "checks"
  | "settings";

export type FollowupTab = "bonus" | "handover" | "warranty" | "site" | "feedback";
export type SettingsTab = "members" | "workers" | "categories" | "cars" | "orders" | "params";

/** Every permission in a tab's list is required. */
export const FOLLOWUP_TAB_PERMS: Record<FollowupTab, string[]> = {
  bonus: ["accounting.view_orderbonus"],
  // Topshiruv follows Amallar + Barcha hamyonlar, not the Готов switch
  handover: ["accounting.view_operation", VIEW_ALL],
  warranty: ["accounting.view_warrantyletter"],
  site: ["accounting.view_siteentrytask"],
  feedback: ["accounting.view_clientfeedback"],
};

export const SETTINGS_TAB_PERMS: Record<SettingsTab, string[]> = {
  members: ["oauth.view_telegrammember"],
  workers: ["accounting.view_worker"],
  categories: ["accounting.view_financecategory"],
  cars: ["accounting.view_financecar"],
  orders: ["accounting.view_manualorder"],
  params: ["accounting.view_financecategory"],
};

/** GET finance/options/ answers a holder of any of these. */
export const FIN_OPTIONS_PERMS = [
  "accounting.view_operation",
  "accounting.view_debt",
  "accounting.view_finance_summary",
  "accounting.view_finance_orders",
  "accounting.view_monthreport",
];

/** GET finance/order-options/ answers a holder of any of these. */
export const ORDER_OPTIONS_PERMS = ["accounting.view_operation", "accounting.view_debt"];

/** The Excel export holds every one of these pages' data. */
export const EXPORT_PERMS = [
  "accounting.view_finance_summary",
  "accounting.view_operation",
  "accounting.view_finance_checks",
  "accounting.view_worker_card",
  "accounting.view_finance_wallets",
  VIEW_ALL,
];

/** In sidebar order. A page opens when the user holds ALL perms of ANY one alternative. */
const PAGES: { page: FinancePage; to: string; alternatives: string[][] }[] = [
  { page: "summary", to: "/finance", alternatives: [["accounting.view_finance_summary"]] },
  { page: "operations", to: "/finance/operations", alternatives: [["accounting.view_operation"]] },
  { page: "debts", to: "/finance/debts", alternatives: [["accounting.view_debt"]] },
  { page: "wallets", to: "/finance/wallets", alternatives: [["accounting.view_finance_wallets"]] },
  { page: "orders", to: "/finance/orders", alternatives: [["accounting.view_finance_orders", VIEW_ALL]] },
  { page: "requests", to: "/finance/requests", alternatives: [["accounting.view_moneyrequest"]] },
  { page: "reports", to: "/finance/reports", alternatives: [["accounting.view_monthreport"]] },
  { page: "workerCard", to: "/finance/worker-card", alternatives: [["accounting.view_worker_card", VIEW_ALL]] },
  { page: "advances", to: "/finance/advances", alternatives: [["accounting.view_advances", VIEW_ALL]] },
  { page: "followup", to: "/finance/followup", alternatives: Object.values(FOLLOWUP_TAB_PERMS) },
  { page: "checks", to: "/finance/checks", alternatives: [["accounting.view_finance_checks", VIEW_ALL]] },
  { page: "settings", to: "/finance/settings", alternatives: Object.values(SETTINGS_TAB_PERMS) },
];

type Can = (...perms: string[]) => boolean;

export function canOpenFinancePage(page: FinancePage, can: Can) {
  return !!PAGES.find((p) => p.page === page)?.alternatives.some((perms) => can(...perms));
}

export function firstFinancePage(can: Can) {
  return PAGES.find((p) => p.alternatives.some((perms) => can(...perms)))?.to ?? null;
}
