"""Who is writing: the result of `POST whoami/`, stored in handler data as `actor`."""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.types import User


@dataclass
class Actor:
    user: User
    member: dict | None = None  # finance Member DTO or None
    hr: dict = field(default_factory=lambda: {"employee": None, "is_admin": False})

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

    @classmethod
    def from_whoami(cls, user: User, data: dict) -> "Actor":
        return cls(
            user=user,
            member=data.get("finance_member"),
            hr=data.get("hr") or {"employee": None, "is_admin": False},
        )
