"""Per-person section levels are no longer set over the API (owner's rule: rights come
from the lavozim). The level logic itself (oauth.access.set_access) is still what
lavozims use, so the tests drive it directly with this API-like result."""

from dataclasses import dataclass, field


@dataclass
class Result:
    status_code: int
    data: dict = field(default_factory=dict)


def set_levels(user, levels) -> Result:
    from core.exceptions import ServiceError
    from oauth.access import set_access

    try:
        return Result(200, set_access(user, levels))
    except ServiceError as e:
        return Result(400, {"detail": e.message})
