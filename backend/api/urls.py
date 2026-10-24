from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import accounting, call_center, metering, orders, users
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
    path("", include(router.urls)),
]

urlpatterns = [
    path("v1/", include(v1)),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]
