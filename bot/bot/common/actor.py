"""Who is writing: the result of `POST whoami/`, stored in handler data as `actor`."""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.types import User


@dataclass
class Actor:
    user: User
    member: dict | None = None  # finance Member DTO or None
    hr: dict = field(default_factory=lambda: {"employee": None, "is_admin": False})
    crm: dict = field(default_factory=dict)
    warehouse: dict = field(default_factory=dict)

    @property
    def tg_id(self) -> int:
        return self.user.id

    # ---- finance
    @property
    def role(self) -> str:
        return (self.member or {}).get("role", "")

    @property
    def is_admin(self) -> bool:
        return bool(self.member and self.member.get("is_admin"))

    @property
    def active(self) -> bool:
        return bool(self.member and self.member.get("is_active_member"))

    @property
    def pending(self) -> bool:
        return self.role == "pending"

    @property
    def blocked(self) -> bool:
        return self.role == "blocked"

    @property
    def task_only(self) -> bool:
        return bool(self.member and self.member.get("is_task_only"))

    @property
    def name(self) -> str:
        return (self.member or {}).get("name") or str(self.user.id)

    # ---- HR
    @property
    def employee(self) -> dict | None:
        return (self.hr or {}).get("employee")

    @property
    def hr_admin(self) -> bool:
        return bool((self.hr or {}).get("is_admin"))

    # ---- CRM
    @property
    def can_add_lead(self) -> bool:
        return bool((self.crm or {}).get("can_add_lead"))

    @property
    def can_set_location(self) -> bool:
        return bool((self.crm or {}).get("can_set_location"))

    @property
    def crm_linked(self) -> bool:
        return bool((self.crm or {}).get("linked"))

    # ---- warehouse
    @property
    def is_keeper(self) -> bool:
        return bool((self.warehouse or {}).get("is_keeper"))

    @classmethod
    def from_whoami(cls, user: User, data: dict) -> "Actor":
        return cls(
            user=user,
            member=data.get("finance_member"),
            hr=data.get("hr") or {"employee": None, "is_admin": False},
            crm=data.get("crm") or {},
            warehouse=data.get("warehouse") or {},
        )
