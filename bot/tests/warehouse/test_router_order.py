"""The warehouse routers sit where they must: after offer / before crm, and the fallback after
HR private (a keeper's HR answers) and before finance (receipts)."""

from crm.conftest import env  # noqa: F401


def test_router_order(env):  # noqa: F811
    names = [r.name for r in env.dp.sub_routers]
    assert names.index("offer") < names.index("warehouse") < names.index("crm")
    assert names.index("warehouse_fallback") == names.index("finance") - 1
    assert names.index("warehouse_fallback") > names.index(
        [n for n in names if n.startswith("hr") and "group" not in n][-1]
    )
