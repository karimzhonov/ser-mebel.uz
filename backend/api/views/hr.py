"""HR — davomat API (the site side of the attendance bot). Rules: hr/services.py.
Every endpoint needs the matching hr.* model permission (ModelPermissions)."""

from __future__ import annotations

import re
from datetime import date

from django.db.models import Count
from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from hr import services as S
from hr.constants import DEFAULTS, LABELS, ST_LABEL
from hr.excel import build_xlsx
from hr.models import Attendance, Employee, Holiday, Leave, PointAdjustment, Winner, WorkGroup

from ..permissions import ModelPermissions, require_perm
from ..serializers.hr import (
    AttendanceEditSerializer,
    AttendanceSerializer,
    EmployeeSerializer,
    HolidaySerializer,
    LeaveSerializer,
    PointAdjustmentSerializer,
    WinnerSerializer,
    WorkGroupSerializer,
)
from ..utils import date_param, date_range, int_param


class HrDayView(APIView):
    """Board for one day: GET /hr/day/?date=YYYY-MM-DD (default today, live)."""

    permission_classes = [ModelPermissions]
    queryset = Attendance.objects.none()

    def get(self, request):
        now_d = S.now()
        day = date_param(request.query_params, "date") or now_d.date()
        rows = S.day_rows(day, now_d)
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        expected = sum(
            counts.get(k, 0) for k in ("on_time", "late", "waiting", "absent", "excused")
        )
        return Response(
            {
                "date": day,
                "now": now_d.strftime("%H:%M") if day == now_d.date() else None,
                "holiday": S.holiday(day),
                "rows": rows,
                "counts": counts,
                "expected": expected,
                "labels": ST_LABEL,
            }
        )


class AttendanceViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = AttendanceSerializer
    search_fields = ["employee__name", "late_comment", "early_comment", "excuse", "note"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # post: only /ensure/

    def get_queryset(self):
        qs = Attendance.objects.select_related("employee").order_by("-day", "employee__name")
        p = self.request.query_params
        start, end = date_range(p)
        if start:
            qs = qs.filter(day__gte=start)
        if end:
            qs = qs.filter(day__lte=end)
        emp = int_param(p, "employee")
        if emp:
            qs = qs.filter(employee_id=emp)
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("group"):
            qs = qs.filter(employee__group_id=int_param(p, "group"))
        return qs

    @action(detail=False, methods=["post"])
    def ensure(self, request):
        """The row of (employee, day), created if the day has none yet — so HR can
        correct an «absent» that has no record."""
        require_perm(request.user, "hr.change_attendance")
        e = Employee.objects.filter(pk=request.data.get("employee")).first()
        day = date_param(request.data, "day")
        if not e or not day:
            raise ValidationError({"employee": "Xodim va sana kerak."})
        a = Attendance.objects.filter(employee=e, day=day).first()
        if a:
            return Response(AttendanceSerializer(a).data)
        # the board's row for that day — none before the count started / they joined
        row = next((r for r in S.compute_day(day, S.now()) if r.e.id == e.id), None)
        if not row:
            raise ValidationError({"day": "Bu kun xodim uchun hisobga olinmaydi."})
        a, created = Attendance.objects.get_or_create(employee=e, day=day)
        if created and day < S.now().date():
            # a past day without a row: freeze it with the status the board showed
            a.status = row.st
            a.work_start, a.work_end = S.hm_str(S.emp_start(e)), S.hm_str(S.emp_end(e))
            a.finalized = True
            a.save()
            a = S.edit_attendance(a, {})
        return Response(AttendanceSerializer(a).data)

    def partial_update(self, request, *args, **kwargs):
        s = AttendanceEditSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        a = S.edit_attendance(self.get_object(), dict(s.validated_data))
        return Response(AttendanceSerializer(a).data)


class EmployeeViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = EmployeeSerializer
    pagination_class = None
    search_fields = ["name", "username"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Employee.objects.select_related("group", "member")
        if self.request.query_params.get("active") in ("0", "1"):
            qs = qs.filter(is_active=self.request.query_params["active"] == "1")
        return qs

    def perform_create(self, serializer):
        from django.db import IntegrityError, transaction
        from django.db.models import Max

        for _ in range(5):  # number = max + 1 can collide with the bot adding someone
            try:
                with transaction.atomic():
                    num = (Employee.objects.aggregate(m=Max("number"))["m"] or 0) + 1
                    serializer.save(number=num, created_on=S.now().date())
                    return
            except IntegrityError:
                if Employee.objects.filter(
                    telegram_id=serializer.validated_data["telegram_id"]
                ).exists():
                    raise ValidationError({"telegram_id": "Bu Telegram ID allaqachon ro'yxatda."})
        raise ValidationError({"detail": "Saqlab bo'lmadi, qayta urinib ko'ring."})


class WorkGroupViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = WorkGroupSerializer
    queryset = WorkGroup.objects.annotate(n_employees=Count("employees"))
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]


class HolidayViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = HolidaySerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Holiday.objects.all()
        if self.request.query_params.get("upcoming") == "1":
            qs = qs.filter(day__gte=S.now().date())
        return qs


class LeaveViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = LeaveSerializer
    queryset = Leave.objects.select_related("employee")
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        lv = S.add_leave(d["employee"], d["date_from"], d["date_to"], d.get("reason") or "ta'til")
        return Response(LeaveSerializer(lv).data, status=201)


class PointAdjustmentViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = PointAdjustmentSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = PointAdjustment.objects.select_related("employee")
        start, end = date_range(self.request.query_params)
        if start:
            qs = qs.filter(day__gte=start)
        if end:
            qs = qs.filter(day__lte=end)
        return qs

    def perform_create(self, serializer):
        a = serializer.save()
        from hr.telegram import dm, esc, ism

        v, why = a.value, a.reason
        dm(
            a.employee,
            (
                (
                    f"🌟 {ism(a.employee)}, rahbar sizga <b>+{v} ball</b> berdi"
                    + (f": {esc(why)}" if why else "")
                    + ". Barakalla! 👏"
                )
                if v > 0
                else (
                    f"ℹ️ {ism(a.employee)}, sizga <b>{v} ball</b> yozildi"
                    + (f": {esc(why)}" if why else "")
                    + "."
                )
            ),
        )


class WinnerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = WinnerSerializer
    queryset = Winner.objects.select_related("employee")
    pagination_class = None

    @action(detail=False, methods=["post"])
    def announce(self, request):
        """Announce «Oy/Yil xodimi» in every work group (same as the bot's button)."""
        require_perm(request.user, "hr.add_winner")
        kind, period = request.data.get("kind"), str(request.data.get("period") or "")
        if kind not in ("m", "y") or not re.fullmatch(
            r"\d{4}-\d{2}" if kind == "m" else r"\d{4}", period
        ):
            raise ValidationError({"period": "Oy: 2026-10, yil: 2026."})
        e = Employee.objects.filter(pk=request.data.get("employee")).first()
        if not e:
            raise ValidationError({"employee": "Xodimni tanlang."})
        if Winner.objects.filter(kind=kind, period=period).exists():
            raise ValidationError({"period": "Bu tanlov allaqachon e'lon qilingan."})
        from hr.telegram import announce_winner

        announce_winner(kind, period, e.telegram_id)
        return Response(
            WinnerSerializer(Winner.objects.get(kind=kind, period=period)).data, status=201
        )


class HrStatsView(APIView):
    """Ranking: ?month=YYYY-MM | ?year=YYYY | ?date_from&date_to."""

    permission_classes = [ModelPermissions]
    queryset = Attendance.objects.none()

    def get(self, request):
        p, now_d = request.query_params, S.now()
        if p.get("year"):
            if not re.fullmatch(r"\d{4}", p["year"]):
                raise ValidationError({"year": "Masalan 2026."})
            rows = [
                {
                    "employee_id": x["e"].id,
                    "number": x["e"].number,
                    "name": x["e"].name,
                    "points": x["pts"],
                    "expected": x["exp"],
                    "on_time": x["on_time"],
                    "discipline": x["disc"],
                    "wins": x["wins"],
                    "bonus": x["bonus"],
                    "adjust": x["adj"],
                }
                for x in S.year_stats(p["year"], now_d)
            ]
            return Response({"period": p["year"], "rows": rows})
        if p.get("month"):
            if not re.fullmatch(r"\d{4}-\d{2}", p["month"]):
                raise ValidationError({"month": "Masalan 2026-10."})
            start, end = date.fromisoformat(p["month"] + "-01"), S.last_day_of_month(p["month"])
        else:
            start, end = date_range(p)
            if not start or not end:
                ym = now_d.strftime("%Y-%m")
                start, end = date.fromisoformat(ym + "-01"), S.last_day_of_month(ym)
        stats = S.period_stats(start, end, now_d)
        return Response(
            {
                "period": f"{start}..{end}",
                "date_from": start,
                "date_to": end,
                "rows": [s.as_dict() for s in stats],
            }
        )


class HrSettingsView(APIView):
    permission_classes = [ModelPermissions]
    queryset = WorkGroup.objects.none()

    def get(self, request):
        return Response({"values": S.all_settings(), "labels": LABELS, "defaults": DEFAULTS})

    def patch(self, request):
        require_perm(request.user, "hr.change_workgroup")
        for k in request.data:
            if k not in DEFAULTS:
                raise ValidationError({k: "Noma'lum sozlama."})
        for k, v in request.data.items():
            S.set_setting(k, v)
        return self.get(request)


class HrExportView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Attendance.objects.none()

    def get(self, request):
        start, end = date_range(request.query_params)
        if not start or not end:
            raise ValidationError({"date_from": "Davrni tanlang."})
        content = build_xlsx(start, end)
        resp = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="Davomat_{start}_{end}.xlsx"'
        return resp
