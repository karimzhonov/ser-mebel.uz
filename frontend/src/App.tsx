import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AppLayout } from "@/components/layout/AppLayout";
import { Card, Empty, PageLoader } from "@/components/ui";
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CallCenterPage from "@/pages/callcenter";
import MyTasksPage from "@/pages/callcenter/MyTasks";
import { ClientDetailPage, ClientsPage } from "@/pages/Clients";
import { MeteringDetailPage, MeteringsPage } from "@/pages/Meterings";
import { DesignDetailPage, DesignsPage } from "@/pages/Designs";
import { PriceDetailPage, PricesPage } from "@/pages/Prices";
import PresentationsPage from "@/pages/Presentations";
import ManagerTasksPage from "@/pages/offers/ManagerTasks";
import CatalogPage from "@/pages/Catalog";
import { OrderCreatePage, OrderDetailPage, OrdersPage } from "@/pages/Orders";
import ProductionPage from "@/pages/Production";
import FactoriesPage from "@/pages/Factories";
import FinanceSummaryPage from "@/pages/finance/Summary";
import FinanceOperationsPage from "@/pages/finance/Operations";
import { FinanceDebtsPage } from "@/pages/finance/Debts";
import FinanceSettingsPage from "@/pages/finance/Settings";
import { FinanceOrdersPage, FinanceWalletsPage } from "@/pages/finance/Wallets";
import { HrJournalPage, HrTodayPage } from "@/pages/hr/Today";
import { WarehouseMovementsPage, WarehouseSettingsPage, WarehouseStockPage } from "@/pages/warehouse/Warehouse";
import { HrCalendarPage, HrEmployeesPage, HrRatingPage, HrSettingsPage } from "@/pages/hr/People";
import { canOpenFinancePage, firstFinancePage, type FinancePage } from "@/pages/finance/access";
import FinanceWorkerCardPage from "@/pages/finance/WorkerCard";
import { FinanceAdvancesPage } from "@/pages/finance/Advances";
import { FinanceChecksPage, FinanceFollowupPage, FinanceReportsPage, FinanceRequestsPage } from "@/pages/finance/Tasks";
import UsersPage from "@/pages/Users";
import FolderPage from "@/pages/Folder";
import NotFoundPage from "@/pages/NotFound";

/** A finance page opens only with its own rights; /finance falls through to the first allowed one. */
function FinanceGuard({ page, children }: { page: FinancePage; children: ReactNode }) {
  const { can } = useAuth();
  if (canOpenFinancePage(page, can)) return <>{children}</>;
  const first = page === "summary" ? firstFinancePage(can) : null;
  if (first) return <Navigate to={first} replace />;
  return (
    <Card>
      <Empty title="Bu bo'limga huquq yo'q" />
    </Card>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <PageLoader />
      </div>
    );
  if (!user)
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={user.is_warehouse_keeper && !user.is_superuser ? <Navigate to="/warehouse" replace /> : <DashboardPage />} />
        <Route path="call-center" element={<CallCenterPage />} />
        <Route path="call-center/tasks" element={<MyTasksPage />} />
        <Route path="clients" element={<ClientsPage />} />
        <Route path="clients/:phone" element={<ClientDetailPage />} />
        <Route path="meterings" element={<MeteringsPage />} />
        <Route path="meterings/:id" element={<MeteringDetailPage />} />
        <Route path="designs" element={<DesignsPage />} />
        <Route path="designs/:id" element={<DesignDetailPage />} />
        <Route path="prices" element={<PricesPage />} />
        <Route path="prices/:id" element={<PriceDetailPage />} />
        <Route path="presentations" element={<PresentationsPage />} />
        <Route path="my-tasks" element={<ManagerTasksPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/new" element={<OrderCreatePage />} />
        <Route path="orders/:id" element={<OrderDetailPage />} />
        <Route path="production/:kind" element={<ProductionPage />} />
        <Route path="factories" element={<FactoriesPage />} />
        <Route path="finance" element={<FinanceGuard page="summary"><FinanceSummaryPage /></FinanceGuard>} />
        <Route path="finance/operations" element={<FinanceGuard page="operations"><FinanceOperationsPage /></FinanceGuard>} />
        <Route path="finance/debts" element={<FinanceGuard page="debts"><FinanceDebtsPage /></FinanceGuard>} />
        <Route path="finance/wallets" element={<FinanceGuard page="wallets"><FinanceWalletsPage /></FinanceGuard>} />
        <Route path="finance/orders" element={<FinanceGuard page="orders"><FinanceOrdersPage /></FinanceGuard>} />
        <Route path="finance/requests" element={<FinanceGuard page="requests"><FinanceRequestsPage /></FinanceGuard>} />
        <Route path="finance/reports" element={<FinanceGuard page="reports"><FinanceReportsPage /></FinanceGuard>} />
        <Route path="finance/worker-card" element={<FinanceGuard page="workerCard"><FinanceWorkerCardPage /></FinanceGuard>} />
        <Route path="finance/followup" element={<FinanceGuard page="followup"><FinanceFollowupPage /></FinanceGuard>} />
        <Route path="finance/advances" element={<FinanceGuard page="advances"><FinanceAdvancesPage /></FinanceGuard>} />
        <Route path="finance/checks" element={<FinanceGuard page="checks"><FinanceChecksPage /></FinanceGuard>} />
        <Route path="finance/settings" element={<FinanceGuard page="settings"><FinanceSettingsPage /></FinanceGuard>} />
        <Route path="warehouse" element={<WarehouseStockPage />} />
        <Route path="warehouse/movements" element={<WarehouseMovementsPage />} />
        <Route path="warehouse/settings" element={<WarehouseSettingsPage />} />
        <Route path="hr" element={<HrTodayPage />} />
        <Route path="hr/journal" element={<HrJournalPage />} />
        <Route path="hr/rating" element={<HrRatingPage />} />
        <Route path="hr/employees" element={<HrEmployeesPage />} />
        <Route path="hr/calendar" element={<HrCalendarPage />} />
        <Route path="hr/settings" element={<HrSettingsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="files/:id" element={<FolderPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
