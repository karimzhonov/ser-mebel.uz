"""«Oylik varaqlari»: the salary sheet on the site (payroll/services.py holds every rule).

The accountant (add/change_salarysheet) fills a draft and sends it on; the boss
(payroll.approve_salarysheet) approves it — the PDF then goes into each worker's
folder — or returns it with a reason."""

from __future__ import annotations

from urllib.parse import quote

from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounting.models import Worker
from core.exceptions import ServiceError
from payroll import services as P
from payroll.models import SheetStatus
from payroll.pdf import render_pdf

from ..permissions import ModelPermissions, require_perm
from ..serializers.payroll import (
    SalarySheetCreateSerializer,
    SalarySheetListSerializer,
    SalarySheetWriteSerializer,
)

APPROVE = "payroll.approve_salarysheet"
CHANGE = "payroll.change_salarysheet"


class SalarySheetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [ModelPermissions]
    serializer_class = SalarySheetListSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = P.sheets_qs().prefetch_related("members__worker")
        if self.action != "list":
            return qs
        p = self.request.query_params
        return P.filter_sheets(
            qs,
            status=p.get("status", ""),
            month=p.get("month", ""),
            worker=p.get("worker", ""),
            search=(p.get("search") or "").strip(),
        )

    def _detail(self, request, sheet) -> dict:
        user = request.user
        draft = sheet.status == SheetStatus.DRAFT
        approver = user.has_perm(APPROVE)
        return {
            **P.sheet_view(sheet),
            "returned_note": sheet.returned_note,
            "warnings": [] if sheet.status == SheetStatus.APPROVED else P.warnings(sheet),
            "created_by": getattr(sheet.created_by, "name", "") or "",
            "updated_by": getattr(sheet.updated_by, "name", "") or "",
            "submitted_by": getattr(sheet.submitted_by, "name", "") or "",
            "submitted_at": sheet.submitted_at,
            "approved_by": getattr(sheet.approved_by, "name", "") or "",
            "approved_at": sheet.approved_at,
            "can": {
                "edit": draft and user.has_perm(CHANGE),
                "submit": draft and user.has_perm(CHANGE),
                "approve": sheet.status != SheetStatus.APPROVED and approver,
                "return": (sheet.status == SheetStatus.SUBMITTED and (approver or user.has_perm(CHANGE)))
                or (sheet.status == SheetStatus.APPROVED and approver),
                "delete": draft and not sheet.version and user.has_perm("payroll.delete_salarysheet"),
            },
        }

    def retrieve(self, request, *args, **kwargs):
        return Response(self._detail(request, self.get_object()))

    def create(self, request, *args, **kwargs):
        ser = SalarySheetCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        worker = Worker.objects.filter(pk=d["worker"]).first()
        if worker is None:
            raise ServiceError("Xodimni tanlang.", "worker")
        sheet = P.create_sheet(
            worker, month=d.get("month") or None, kind=d.get("kind") or None, by=request.user
        )
        return Response(self._detail(request, sheet), status=201)

    def partial_update(self, request, *args, **kwargs):
        ser = SalarySheetWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sheet = P.update_sheet(self.get_object(), ser.validated_data, by=request.user)
        return Response(self._detail(request, sheet))

    def perform_destroy(self, instance):
        P.delete_sheet(instance)

    # not named `options`: that is the viewset's HTTP OPTIONS handler
    @action(detail=False, methods=["get"], url_path="options")
    def sheet_options(self, request):
        return Response(P.options())

    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        """Live totals + the order behind each typed ID, for the unsaved form."""
        require_perm(request.user, CHANGE)
        data = request.data if isinstance(request.data, dict) else {}
        return Response(P.preview_sheet(self.get_object(), data))

    @action(detail=True, methods=["get"], url_path="order-bonuses")
    def order_bonuses(self, request, pk=None):
        """«Bonuslar» closed in the sheet's period, for «Bonuslardan olish»."""
        require_perm(request.user, CHANGE)
        return Response(P.order_bonuses_for(self.get_object()))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        require_perm(request.user, CHANGE)
        return Response(self._detail(request, P.submit_sheet(self.get_object(), by=request.user)))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        require_perm(request.user, APPROVE)
        return Response(self._detail(request, P.approve_sheet(self.get_object(), by=request.user)))

    @action(detail=True, methods=["post"], url_path="return")
    def return_(self, request, pk=None):
        sheet = self.get_object()
        approver = request.user.has_perm(APPROVE)
        if sheet.status == SheetStatus.APPROVED and not approver:
            raise PermissionDenied("Tasdiqlangan varaqni faqat rahbar qaytaradi.")
        if not (approver or request.user.has_perm(CHANGE)):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        reason = str(request.data.get("reason") or "")
        if sheet.status == SheetStatus.APPROVED and not reason.strip():
            raise ServiceError("Tasdiqlangan varaqni qaytarish sababini yozing.", "reason")
        return Response(
            self._detail(request, P.return_sheet(sheet, reason=reason, by=request.user))
        )

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        sheet = self.get_object()
        view = P.sheet_view(sheet)
        name = f"Oylik_{view['month']}_{view['worker']}_No{sheet.number}.pdf"
        resp = HttpResponse(render_pdf(view), content_type="application/pdf")
        ascii_name = name.encode("ascii", "ignore").decode() or "oylik.pdf"
        disp = "attachment" if request.query_params.get("download") else "inline"
        resp["Content-Disposition"] = f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        return resp
