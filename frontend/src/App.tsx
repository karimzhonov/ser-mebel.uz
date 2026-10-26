import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AppLayout } from "@/components/layout/AppLayout";
import { PageLoader } from "@/components/ui";
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CallCenterPage from "@/pages/CallCenter";
import { ClientDetailPage, ClientsPage } from "@/pages/Clients";
import { MeteringDetailPage, MeteringsPage } from "@/pages/Meterings";
import { DesignDetailPage, DesignsPage } from "@/pages/Designs";
import { PriceDetailPage, PricesPage } from "@/pages/Prices";
import CatalogPage from "@/pages/Catalog";
import { OrderCreatePage, OrderDetailPage, OrdersPage } from "@/pages/Orders";
import ProductionPage from "@/pages/Production";
import FactoriesPage from "@/pages/Factories";
import AccountingPage from "@/pages/Accounting";
import FinanceSummaryPage from "@/pages/finance/Summary";
import FinanceOperationsPage from "@/pages/finance/Operations";
import FinanceSettingsPage from "@/pages/finance/Settings";
import { FinanceOrdersPage, FinanceWalletsPage } from "@/pages/finance/Wallets";
import { HrJournalPage, HrTodayPage } from "@/pages/hr/Today";
import { HrCalendarPage, HrEmployeesPage, HrRatingPage, HrSettingsPage } from "@/pages/hr/People";
import { FinanceChecksPage, FinanceFollowupPage, FinanceReportsPage, FinanceRequestsPage } from "@/pages/finance/Tasks";
import UsersPage from "@/pages/Users";
import FolderPage from "@/pages/Folder";
import { Empty } from "@/components/ui";

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
        <Route index element={<DashboardPage />} />
        <Route path="call-center" element={<CallCenterPage />} />
        <Route path="clients" element={<ClientsPage />} />
        <Route path="clients/:phone" element={<ClientDetailPage />} />
        <Route path="meterings" element={<MeteringsPage />} />
        <Route path="meterings/:id" element={<MeteringDetailPage />} />
        <Route path="designs" element={<DesignsPage />} />
        <Route path="designs/:id" element={<DesignDetailPage />} />
        <Route path="prices" element={<PricesPage />} />
        <Route path="prices/:id" element={<PriceDetailPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/new" element={<OrderCreatePage />} />
        <Route path="orders/:id" element={<OrderDetailPage />} />
        <Route path="production/:kind" element={<ProductionPage />} />
        <Route path="factories" element={<FactoriesPage />} />
        <Route path="accounting/:kind" element={<AccountingPage />} />
        <Route path="finance" element={<FinanceSummaryPage />} />
        <Route path="finance/operations" element={<FinanceOperationsPage />} />
        <Route path="finance/wallets" element={<FinanceWalletsPage />} />
        <Route path="finance/orders" element={<FinanceOrdersPage />} />
        <Route path="finance/requests" element={<FinanceRequestsPage />} />
        <Route path="finance/reports" element={<FinanceReportsPage />} />
        <Route path="finance/followup" element={<FinanceFollowupPage />} />
        <Route path="finance/checks" element={<FinanceChecksPage />} />
        <Route path="finance/settings" element={<FinanceSettingsPage />} />
        <Route path="hr" element={<HrTodayPage />} />
        <Route path="hr/journal" element={<HrJournalPage />} />
        <Route path="hr/rating" element={<HrRatingPage />} />
        <Route path="hr/employees" element={<HrEmployeesPage />} />
        <Route path="hr/calendar" element={<HrCalendarPage />} />
        <Route path="hr/settings" element={<HrSettingsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="files/:id" element={<FolderPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Empty title="Sahifa topilmadi" />} />
      </Route>
    </Routes>
  );
}
