from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import accounting, call_center, finance, hr, metering, orders, users
from .views.auth import LoginView, LogoutView, MeView, TelegramLoginView
from .views.dashboard import BoardsView, MetaView
from .views.files import FileView, FolderMessagesView, FolderView
from .views.overview import OverviewView

router = DefaultRouter()
router.register("clients", call_center.ClientViewSet, basename="client")
router.register("invoices", call_center.InvoiceViewSet, basename="invoice")
router.register("meterings", metering.MeteringViewSet, basename="metering")
router.register("designs", metering.DesignViewSet, basename="design")
router.register("design-types", metering.DesignTypeViewSet, basename="designtype")
router.register("prices", metering.PriceViewSet, basename="price")
router.register("object-types", metering.ObjectTypeViewSet, basename="objecttype")
router.register("inventory-types", metering.InventoryTypeViewSet, basename="inventorytype")
router.register("inventories", metering.InventoryViewSet, basename="inventory")
router.register("orders", orders.OrderViewSet, basename="order")
router.register("factories", orders.FactoryViewSet, basename="factory")
router.register("detailings", orders.DetailingViewSet, basename="detailing")
router.register("rovers", orders.RoverViewSet, basename="rover")
router.register("painter-types", orders.PainterTypeViewSet, basename="paintertype")
router.register("painters", orders.PainterViewSet, basename="painter")
router.register("assemblies", orders.AssemblyViewSet, basename="assembly")
router.register("incomes", accounting.IncomeViewSet, basename="income")
router.register("expenses", accounting.ExpenseViewSet, basename="expense")
router.register("income-categories", accounting.IncomeCategoryViewSet, basename="incomecategory")
router.register("expense-categories", accounting.ExpenseCategoryViewSet, basename="expensecategory")
router.register("finance/members", finance.TelegramMemberViewSet, basename="telegrammember")
router.register("finance/categories", finance.FinanceCategoryViewSet, basename="financecategory")
router.register("finance/workers", finance.WorkerViewSet, basename="worker")
router.register("finance/cars", finance.FinanceCarViewSet, basename="financecar")
router.register("finance/manual-orders", finance.ManualOrderViewSet, basename="manualorder")
router.register("finance/operations", finance.OperationViewSet, basename="operation")
router.register("finance/month-reports", finance.MonthReportViewSet, basename="monthreport")
router.register("finance/requests", finance.MoneyRequestViewSet, basename="moneyrequest")
router.register("finance/bonuses", finance.OrderBonusViewSet, basename="orderbonus")
router.register("finance/warranty", finance.WarrantyLetterViewSet, basename="warrantyletter")
router.register("finance/site-entry", finance.SiteEntryTaskViewSet, basename="siteentrytask")
router.register("finance/feedback", finance.ClientFeedbackViewSet, basename="clientfeedback")
router.register("hr/attendance", hr.AttendanceViewSet, basename="attendance")
router.register("hr/employees", hr.EmployeeViewSet, basename="employee")
router.register("hr/groups", hr.WorkGroupViewSet, basename="workgroup")
router.register("hr/holidays", hr.HolidayViewSet, basename="holiday")
router.register("hr/leaves", hr.LeaveViewSet, basename="leave")
router.register("hr/points", hr.PointAdjustmentViewSet, basename="pointadjustment")
router.register("hr/winners", hr.WinnerViewSet, basename="winner")
router.register("users", users.UserViewSet, basename="user")
router.register("groups", users.GroupViewSet, basename="group")

v1 = [
    path("auth/login/", LoginView.as_view(), name="api-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="api-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="api-logout"),
    path("auth/telegram/", TelegramLoginView.as_view(), name="api-telegram-login"),
    path("auth/me/", MeView.as_view(), name="api-me"),
    path("meta/", MetaView.as_view(), name="api-meta"),
    path("dashboard/boards/", BoardsView.as_view(), name="api-boards"),
    path("dashboard/overview/", OverviewView.as_view(), name="api-overview"),
    path("folders/<int:folder_id>/", FolderView.as_view(), name="api-folder"),
    path(
        "folders/<int:folder_id>/messages/",
        FolderMessagesView.as_view(),
        name="api-folder-messages",
    ),
    path("files/<int:file_id>/", FileView.as_view(), name="api-file"),
    path("finance/telegram/update/", finance.TelegramUpdateView.as_view(), name="api-finance-telegram"),
    path("finance/summary/", finance.FinanceSummaryView.as_view(), name="api-finance-summary"),
    path("finance/wallets/", finance.WalletsView.as_view(), name="api-finance-wallets"),
    path("finance/orders/", finance.FinanceOrdersView.as_view(), name="api-finance-orders"),
    path("finance/orders/<str:ref>/", finance.FinanceOrderDetailView.as_view(), name="api-finance-order"),
    path("finance/order-options/", finance.FinanceOrderOptionsView.as_view(), name="api-finance-order-options"),
    path("finance/checks/", finance.ChecksView.as_view(), name="api-finance-checks"),
    path("finance/export/", finance.ExportView.as_view(), name="api-finance-export"),
    path("finance/settings/", finance.FinanceSettingsView.as_view(), name="api-finance-settings"),
    path("finance/handover/", finance.HandoverView.as_view(), name="api-finance-handover"),
    path("finance/me/", finance.MeFinanceView.as_view(), name="api-finance-me"),
    path("hr/day/", hr.HrDayView.as_view(), name="api-hr-day"),
    path("hr/stats/", hr.HrStatsView.as_view(), name="api-hr-stats"),
    path("hr/settings/", hr.HrSettingsView.as_view(), name="api-hr-settings"),
    path("hr/export/", hr.HrExportView.as_view(), name="api-hr-export"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("v1/", include(v1)),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]
