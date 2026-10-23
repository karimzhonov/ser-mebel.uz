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
        <Route path="users" element={<UsersPage />} />
        <Route path="files/:id" element={<FolderPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Empty title="Страница не найдена" />} />
      </Route>
    </Routes>
  );
}
