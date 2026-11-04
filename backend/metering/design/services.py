"""Write services for Design (used by the REST API and the bot API).

Stage 2 (docs/BOT_CONTRACT.md, "Dizayn va narx"): the measurer hands the design to a
designer with a deadline; the designer presses «Tayyor» on the site; the manager shows it
to the client and records the answer (site or bot).
"""

from core.exceptions import ServiceError, ServiceForbidden
from oauth.constants import DESIGN_PERMISSION

MANAGE = "metering.manage_metering"


def create_design(metering, *, user, due_at, by=None):
    """A Design in work with its first variant («Дизайн-1»: made by the Design signal, its
    Filer folder by the DesignType signal). The designer, if any, gets the task in the bot (SMS when no
    Telegram). Call inside the caller's transaction."""
    from django.db import transaction

    from metering import events
    from metering import services as M

    from .models import Design

    with transaction.atomic():
        design = Design(
            metering=metering, user=user, stage="work", due_at=due_at, assigned_at=M._now()
        )
        design._history_user = by
        design.save()
        if user is not None:
            events.offer_assigned(design, "design", how="new")
            M.queue_offer_sms(design, "design", "assigned")
    return design


def can_work_design(user, design) -> bool:
    """May press «Tayyor» / move the deadline: the designer, a «Bosh menejer», a superuser;
    anyone with oauth.user_design while nobody is assigned."""
    if user is None:
        return False
    if user.is_superuser or user.has_perm(MANAGE):
        return True
    if design.user_id is not None:
        return design.user_id == user.pk
    return user.has_perm(f"oauth.{DESIGN_PERMISSION}")


def design_file_count(design) -> int:
    """Files in the design's variant folders (and their sub-folders)."""
    from metering.services import folder_file_count

    roots = [t.folder_id for t in design.designtype_set.all() if t.folder_id]
    return folder_file_count(roots) if roots else 0


def mark_design_done(design, *, by):
    """«Tayyor» (site only): the design goes to the manager, who shows it to the client.
    Needs at least one uploaded file."""
    from django.db import transaction

    from metering import services as M

    with transaction.atomic():
        m, _, _, locked = M.offer_locked(design, "design")
        if not can_work_design(by, locked):
            raise ServiceForbidden("Bu dizayn sizga biriktirilmagan")
        if locked.stage != "work":
            raise M.offer_stage_error(locked.stage)
        if design_file_count(locked) == 0:
            raise ServiceError("Kamida bitta fayl yuklang", "files")
        M.offer_ready(locked, "design", m, by=by, now=M._now())
    return M._copy_back(design, locked, ["done", "stage", "done_at", "done_by", "rev"])


def set_design_due(design, *, by, due_at=None, preset=None, text=None):
    from metering import services as M

    return M.move_offer_due(
        design, "design", by=by, can_work=can_work_design, due_at=due_at, preset=preset, text=text
    )


def set_designer(design, *, by, user):
    from metering import services as M

    return M.reassign_offer(
        design, "design", by=by, user=user, boss_perm=MANAGE, pool=M.designers()
    )


def record_design_answer(design, *, by, answer, comment="", due_at=None):
    """The manager's record of what the client said: approved | changes | declined.
    Returns {"task": design, "closed_tasks": n}."""
    from django.db import transaction

    from call_center.constants import SolutionChoice
    from call_center.services import close_lead_from_offer
    from metering import events
    from metering import services as M
    from metering.constants import ClientResult

    comment = M.offer_answer_prelude(answer, comment, ("approved", "changes", "declined"))
    closed = 0
    with transaction.atomic():
        m, _, price, locked = M.offer_locked(design, "design")
        M.offer_check_answerable(locked, m, by, "design")
        now = M._now()
        new_due = None
        answered_round = locked.round
        locked._history_user = by
        if answer == "approved":
            locked.stage = "approved"
            locked.confirm = True
            locked.rev += 1
            locked.save(update_fields=["stage", "confirm", "rev"])
        elif answer == "changes":
            new_due = M.offer_send_back(
                locked,
                "design",
                m,
                by=by,
                now=now,
                comment=comment,
                due_at=due_at,
                fix_cfg="DESIGN_FIX_DAYS",
            )
        else:
            locked.stage = "declined"
            locked.done = False  # invariant: done == stage in (review, approved)
            locked.rev += 1
            locked.save(update_fields=["stage", "done", "rev"])
            if price is not None and price.stage == "work":
                price.stage = "cancelled"
                price.rev += 1
                price._history_user = by
                price.save(update_fields=["stage", "rev"])
                events.offer_changed(
                    price,
                    "price",
                    how="cancelled",
                    by=by,
                    to_users=[price.user] if price.user is not None else [],
                )
            m.client_result = ClientResult.design_declined
            m._history_user = by
            m.save(update_fields=["client_result"])
        M.offer_store_answer(
            locked,
            "design",
            m,
            by=by,
            answer=answer,
            comment=comment,
            round_=answered_round,
            due_at=new_due,
            log=answer != "declined",
        )
        if answer == "declined" and m.invoice_id is not None:
            closed = close_lead_from_offer(
                m.invoice,
                by=by,
                solution=SolutionChoice.declined,
                reason=comment,
                metering_id=m.pk,
                event="design_declined",
            )
        M.offer_answered(locked, "design", m, by=by, answer=answer)
    M._copy_back(design, locked, ["stage", "confirm", "done", "round", "due_at", "rev"])
    return {"task": design, "closed_tasks": closed}


def add_design_type(design, name: str):
    """A new design variant; its Filer folder is created by the DesignType signal."""
    from .models import DesignType

    return DesignType.objects.create(design=design, name=name)


def can_create_order(design) -> bool:
    """DesignAdmin.has_create_order_permission minus the user permission check."""
    from order.models import Order

    metering = design.metering
    return (
        design.stage == "approved"
        and (
            metering is None or metering.client_result not in ("design_declined", "price_declined")
        )
        and not Order.objects.filter(metering_id=design.metering_id).exists()
    )
