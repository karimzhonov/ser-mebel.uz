"""Who may call the API.

The admin only lets `is_staff` users in, and every changelist is gated by the
model's `view_*` permission. The API keeps both rules:

- IsStaffUser — default for every endpoint (settings.REST_FRAMEWORK).
- ModelPermissions — CRUD endpoints: GET needs view_*, POST add_*, PATCH change_*,
  DELETE delete_* (DRF's own DjangoModelPermissions lets any GET through).

Custom actions (POST /orders/{id}/detailing/ …) check the exact permission the
matching admin button checks, via `require_perm`.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, DjangoModelPermissions


def is_staff(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


class IsStaffUser(BasePermission):
    message = "Panelga kirish huquqi yo'q."

    def has_permission(self, request, view):
        return is_staff(request.user)


class IsSuperUser(BasePermission):
    def has_permission(self, request, view):
        return is_staff(request.user) and request.user.is_superuser


class ModelPermissions(DjangoModelPermissions):
    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    STANDARD_ACTIONS = {"list", "retrieve", "create", "update", "partial_update", "destroy"}

    def has_permission(self, request, view):
        if not is_staff(request.user):
            return False
        action = getattr(view, "action", None)
        if action and action not in self.STANDARD_ACTIONS:
            # Custom @action endpoints (POST /orders/{id}/detailing/ …) are not
            # create/update of this model: being able to see it is enough here, and
            # the action itself checks the exact permission with require_perm().
            model = self._queryset(view).model
            return request.user.has_perms(self.get_required_permissions("GET", model))
        return super().has_permission(request, view)


def require_perm(user, *perms: str) -> None:
    if not user.has_perms(perms):
        raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
