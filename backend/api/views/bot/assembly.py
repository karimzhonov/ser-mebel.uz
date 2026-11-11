"""Assembly (Yig'ish/O'rnatish): the assembler's «O'rnatildi» and the production head's
deadline / assembler buttons (docs/BOT_CONTRACT.md, "Assembly")."""

from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.exceptions import ServiceConflict, ServiceError
from order.assembly.dto import assembly_task
from order.assembly.models import Assembly
from order.assembly.services import (
    active_assemblers,
    assign_assembler,
    finish_assembly,
    set_assembly_due,
)

from .base import BotAPIView


def _get(pk) -> Assembly:
    assembly = (
        Assembly.objects.select_related("order__client", "user", "finished_by", "due_set_by")
        .filter(pk=pk)
        .first()
    )
    if assembly is None:
        raise NotFound("Yig'ish ishi topilmadi")
    return assembly


class AssemblyFinishView(BotAPIView):
    """POST {note} -> {assembly}; 400 {detail, field: "note"} / order not in assembly yet;
    403 not linked or not the assignee; 404; 409 already finished. The assembler's
    «O'rnatildi»."""

    def post(self, request, pk):
        user = self.require_linked_user()
        assembly = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        note = data.get("note")
        if not isinstance(note, str):
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        assembly = finish_assembly(assembly, by=user, note=note)
        return Response({"assembly": assembly_task(assembly)})


class AssemblyDueView(BotAPIView):
    """POST {days: 1..30} -> {assembly}; 400 {detail, field: "due"}; 403; 404; 409 finished.
    The production head's deadline buttons."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        assembly = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        days = data.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ServiceError("Muddat 1 dan 30 kungacha bo'lishi kerak", field="due")
        assembly = set_assembly_due(assembly, by=user, days=days)
        return Response({"assembly": assembly_task(assembly)})


class AssemblyAssemblerView(BotAPIView):
    """POST {user_id} -> {assembly}; 403 not linked / not a production head; 404 job or
    assembler missing; 400 detailing not finished; 409 job finished / a different assembler
    already chosen after start. The head picks the assembler."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        assembly = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        user_id = data.get("user_id")
        assembler = None
        if isinstance(user_id, int) and not isinstance(user_id, bool):
            assembler = active_assemblers().filter(pk=user_id).first()
        if assembler is None:
            raise NotFound("Yig'ish yoki yig'uvchi topilmadi")
        if assembly.installing_done:
            raise ServiceConflict("Yig'ish ishi bajarilgan")
        if assembly.user_id and assembly.started_at and assembly.user_id != assembler.pk:
            raise ServiceConflict(
                f"Jamoa allaqachon tanlangan: {assembly.user.name} — o'zgartirish saytda"
            )
        # the service re-checks «already started» under the row lock (two heads at once)
        assembly = assign_assembler(assembly, assembler, by=user, keep_started=True)
        return Response({"assembly": assembly_task(assembly)})
