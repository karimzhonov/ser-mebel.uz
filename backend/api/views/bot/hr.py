"""Bot API - HR (davomat). The bot forwards Telegram facts; hr.services decides.

"Admin" in HR is a finance admin (hr.services.is_admin). Employees act on themselves.
"""

from __future__ import annotations

import re
from datetime import date

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from core.exceptions import ServiceError
from hr import events as E
from hr import report_data as RD
from hr import services as S
from hr.constants import DEFAULTS
from hr.models import Employee, Holiday, HolidayDecision, Leave

from ...serializers import bot as D
from .base import BotAPIView


def _iso(value, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ServiceError(f"{field}: YYYY-MM-DD kerak.")


def _emp_or_404(ref) -> Employee:
    """ref = the employee's number or Telegram id (or @username / name)."""
    ref = str(ref or "").strip().lstrip("#")
    e = None
    if ref.isdigit():
        e = Employee.objects.select_related("group").filter(number=int(ref)).first()
        if not e:
            e = Employee.objects.select_related("group").filter(telegram_id=int(ref)).first()
    else:
        e = S.find_emp(ref)
    if not e:
        raise NotFound("Xodim topilmadi.")
    return e


# ===================================================================== group traffic
class GroupMessageView(BotAPIView):
    def post(self, request):
        d = request.data
        return Response(
            S.process_group_report(
                chat=d.get("chat") or {},
                message_id=int(d.get("message_id") or 0),
                ts=int(d.get("date") or 0),
                user=d.get("from") or {},
                forwarded=bool(d.get("forwarded")),
                media=d.get("media") or {},
                text=str(d.get("text") or ""),
            )
        )


class MembersJoinedView(BotAPIView):
    def post(self, request):
        d = request.data
        return Response({"welcome": S.members_joined(d.get("chat") or {}, d.get("users") or [])})


class MemberLeftView(BotAPIView):
    def post(self, request):
        d = request.data
        S.member_left(d.get("chat") or {}, d.get("user") or {})
        return Response({})


class BotMembershipView(BotAPIView):
    def post(self, request):
        d = request.data
        S.bot_added_to_group(d.get("chat") or {}, str(d.get("status") or ""))
        return Response({})


# ===================================================================== groups, employees
class GroupsView(BotAPIView):
    def get(self, request):
        self.require_actor()
        return Response([D.group_dto(g) for g in S.groups()])

    def post(self, request):
        self.require_hr_admin()
        try:
            chat_id = int(request.data.get("chat_id"))
        except (TypeError, ValueError):
            raise ServiceError("chat_id kerak.")
        return Response(
            D.group_dto(S.connect_group(chat_id, str(request.data.get("title") or ""))),
            status=201,
        )


class GroupView(BotAPIView):
    def delete(self, request, chat_id):
        self.require_hr_admin()
        try:
            S.disconnect_group(int(chat_id))
        except ValueError:
            raise NotFound("Guruh topilmadi.")
        return Response(status=204)


class EmployeesView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        rows = S.all_emps()
        flag = request.query_params.get("active")
        if flag in ("0", "1"):
            rows = [e for e in rows if e.is_active == (flag == "1")]
        return Response([D.employee_dto(e) for e in rows])

    def post(self, request):
        """/qosh: add the person (the bot passes the replied-to user) to a work group."""
        self.require_hr_admin()
        user = request.data.get("user") or {}
        if not user.get("id") or user.get("is_bot"):
            raise ServiceError("Xodim topilmadi.")
        e, _ = S.upsert_emp(user, S.group_by_chat(request.data.get("chat_id") or 0))
        return Response(D.employee_dto(e), status=201)


class EmployeeView(BotAPIView):
    def get(self, request, ref):
        self.require_hr_admin()
        return Response(D.employee_dto(_emp_or_404(ref)))

    def patch(self, request, ref):
        self.require_hr_admin()
        e = _emp_or_404(ref)
        d = request.data
        if "off_days" in d:
            value = d["off_days"]
            S.set_off_days(
                e,
                (
                    None
                    if value in (None, "general", "umumiy")
                    else S.parse_days(
                        ",".join(str(x) for x in value) if isinstance(value, list) else value
                    )
                ),
            )
        if d.get("toggle_off_day") is not None:
            try:
                day_no = int(d["toggle_off_day"])
            except (TypeError, ValueError):
                raise ServiceError("Hafta kuni 1 dan 7 gacha.")
            S.toggle_off_day(e, day_no)
        if d.get("reset_hours"):
            S.set_hours(e, None, None)
        elif d.get("work_start") or d.get("work_end"):
            ws, we = S.parse_hm(d.get("work_start")), S.parse_hm(d.get("work_end"))
            if ws is None or we is None:
                raise ServiceError("Ish vaqti: HH:MM.")
            S.set_hours(e, S.hm_str(ws), S.hm_str(we))
        if "is_active" in d:
            S.set_active(e, bool(d["is_active"]))
        e = Employee.objects.select_related("group").get(pk=e.pk)
        return Response(D.employee_dto(e))


class EmployeeNotifyView(BotAPIView):
    def post(self, request, ref):
        self.require_hr_admin()
        e = _emp_or_404(ref)
        what = request.data.get("what")
        if what == "off_days":
            E.off_days_set(e)
        elif what == "hours":
            E.hours_set(e)
        else:
            raise ServiceError("what: off_days yoki hours.")
        return Response(status=204)


# ===================================================================== the employee himself
class StartView(BotAPIView):
    def post(self, request):
        user = request.data.get("user") or {}
        if int(user.get("id") or 0) != self.require_actor():
            raise PermissionDenied("actor mismatch")
        e = S.employee_start(user, request.data.get("group_chat_id"))
        return Response({"employee": D.employee_dto(e) if e else None})


class MyStatusView(BotAPIView):
    def get(self, request):
        self.require_actor()
        if not self.employee:
            raise NotFound("Siz xodimlar ro'yxatida yo'qsiz.")
        return Response(S.my_status_data(self.employee))


class CantComeView(BotAPIView):
    def post(self, request):
        return Response(S.cant_come(self.require_actor()))


class PrivateTextView(BotAPIView):
    def post(self, request):
        return Response(S.process_private_text(self.require_actor(), request.data.get("text")))


class CallbackView(BotAPIView):
    def post(self, request):
        d = request.data
        return Response(
            S.process_employee_callback(
                self.require_actor(),
                str(d.get("action") or ""),
                str(d.get("day") or ""),
                str(d.get("arg") or ""),
            )
        )


class DmStatusView(BotAPIView):
    def post(self, request):
        d = request.data
        S.record_dm(d.get("telegram_id"), bool(d.get("ok")), bool(d.get("blocked")))
        return Response(status=204)


# ===================================================================== admin: reports
class DayReportView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        now_d = S.now()
        raw = request.query_params.get("date")
        day = _iso(raw, "date") if raw else now_d.date()
        if day == now_d.date():
            return Response(RD.day_report_data(day, now_d))
        return Response(RD.past_day_report_data(day))


class PeriodReportView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        p = request.query_params
        return Response(
            RD.period_report_data(_iso(p.get("from"), "from"), _iso(p.get("to"), "to"), S.now())
        )


class RankingView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        p = request.query_params
        if p.get("year"):
            if not re.fullmatch(r"\d{4}", p["year"]):
                raise ServiceError("year: 2026.")
            return Response(S.ranking_rows(year=p["year"]))
        ym = p.get("month") or S.now().strftime("%Y-%m")
        if not re.fullmatch(r"\d{4}-\d{2}", ym):
            raise ServiceError("month: 2026-10.")
        return Response(S.ranking_rows(ym))


# ===================================================================== admin: people & calendar
class DayOffView(BotAPIView):
    def post(self, request):
        self.require_hr_admin()
        e = _emp_or_404(request.data.get("employee"))
        d = S.parse_date(request.data.get("date") or "bugun", S.now().date())
        if not d:
            raise ServiceError("Sana noto'g'ri. Masalan: bugun yoki 25.10.2026")
        S.set_att(d, e, status="off")
        E.day_off_set(e, d)
        return Response({"employee": D.employee_dto(e), "day": d.isoformat()})


def _leave_dto(lv: Leave) -> dict:
    return {
        "number": lv.number,
        "employee": D.employee_dto(lv.employee),
        "date_from": lv.date_from.isoformat(),
        "date_to": lv.date_to.isoformat(),
        "reason": lv.reason,
    }


class LeavesView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        qs = Leave.objects.filter(date_to__gte=S.now().date()).select_related(
            "employee", "employee__group"
        )
        return Response([_leave_dto(x) for x in qs])

    def post(self, request):
        self.require_hr_admin()
        d = request.data
        e = _emp_or_404(d.get("employee"))
        today_ = S.now().date()
        d_from = S.parse_date(d.get("date_from"), today_)
        d_to = S.parse_date(d.get("date_to") or d.get("date_from"), today_)
        if not d_from or not d_to:
            raise ServiceError("Sana noto'g'ri.")
        lv = S.add_leave(e, d_from, d_to, str(d.get("reason") or "ta'til"))
        E.leave_added(e, lv)
        return Response(_leave_dto(lv), status=201)


class LeaveView(BotAPIView):
    def delete(self, request, number):
        self.require_hr_admin()
        if not S.delete_leave(number):
            raise NotFound("Topilmadi.")
        return Response(status=204)


class HolidaysView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        return Response(
            [
                {"day": h.day.isoformat(), "name": h.name}
                for h in Holiday.objects.filter(day__gte=S.now().date())
            ]
        )

    def post(self, request):
        self.require_hr_admin()
        d = S.parse_date(request.data.get("day"), S.now().date())
        if not d:
            raise ServiceError("Sana noto'g'ri. Masalan: 01.01.2027")
        h = S.set_holiday(d, str(request.data.get("name") or ""))
        return Response({"day": h.day.isoformat(), "name": h.name}, status=201)


class HolidayView(BotAPIView):
    def delete(self, request, day):
        self.require_hr_admin()
        d = S.parse_date(day, S.now().date())
        if not d or not S.delete_holiday(d):
            raise NotFound("Topilmadi.")
        return Response(status=204)


class HolidayDecisionView(BotAPIView):
    def get(self, request, day):
        self.require_hr_admin()
        d = _iso(day, "day")
        dec = HolidayDecision.objects.filter(holiday_day=d).first()
        return Response(
            {
                "day": d.isoformat(),
                "name": S.holiday_name(d),
                "decided": bool(dec),
                "days": dec.days if dec else None,
            }
        )

    def post(self, request, day):
        self.require_hr_admin()
        d = _iso(day, "day")
        try:
            n = int(request.data.get("n"))
        except (TypeError, ValueError):
            raise ServiceError("n: kunlar soni.")
        start = request.data.get("start")
        res = S.decide_holiday(d, n, _iso(start, "start") if start else d)
        E.holiday_applied(d, res["name"], n, res["days"])
        return Response({"days": [x.isoformat() for x in res["days"]], "name": res["name"]})


class SettingsView(BotAPIView):
    def get(self, request):
        self.require_hr_admin()
        return Response(
            [{"key": k, "label": S.label(k), "value": v} for k, v in S.all_settings().items()]
        )


class SettingView(BotAPIView):
    def put(self, request, key):
        self.require_hr_admin()
        key = key.upper()
        if key not in DEFAULTS:
            raise ServiceError("Noma'lum sozlama.")
        stored = S.set_setting(key, request.data.get("value"))
        return Response({"key": key, "label": S.label(key), "value": stored})


class PointsView(BotAPIView):
    def post(self, request):
        self.require_hr_admin()
        d = request.data
        e = _emp_or_404(d.get("employee"))
        try:
            value = int(str(d.get("value")).replace("−", "-"))
        except ValueError:
            raise ServiceError("Ball butun son bo'lishi kerak.")
        adj = S.add_points(e, value, str(d.get("reason") or ""), S.now().date())
        E.points_added(adj, from_site=False)
        return Response(
            {"employee": D.employee_dto(e), "value": adj.value, "reason": adj.reason}, status=201
        )


class ResetView(BotAPIView):
    def post(self, request):
        self.require_hr_admin()
        S.reset_data(_iso(request.data.get("since"), "since"))
        return Response(status=204)


class WinnersView(BotAPIView):
    def post(self, request):
        self.require_hr_admin()
        d = request.data
        kind, period = d.get("kind"), str(d.get("period") or "")
        if kind not in ("m", "y") or not re.fullmatch(
            r"\d{4}-\d{2}" if kind == "m" else r"\d{4}", period
        ):
            raise ServiceError("Oy: 2026-10, yil: 2026.")
        e = (
            Employee.objects.select_related("group")
            .filter(telegram_id=d.get("employee_tg") or 0)
            .first()
        )
        if not e:
            raise NotFound("Xodim topilmadi.")
        res = S.announce_winner(kind, period, e)
        E.winner_announced(kind, period, res)
        return Response({"groups_count": len(res["groups"])}, status=201)


class OffRequestsView(BotAPIView):
    def post(self, request):
        self.require_hr_admin()
        d = request.data
        e = (
            Employee.objects.select_related("group")
            .filter(telegram_id=d.get("employee_tg") or 0)
            .first()
        )
        if not e:
            raise NotFound("Xodim topilmadi.")
        day = _iso(d.get("day"), "day")
        approve = bool(d.get("approve"))
        S.answer_off_request(e, day, approve)
        E.off_request_answered(e, day, approve)
        return Response({})
