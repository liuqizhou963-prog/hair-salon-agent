"""会员等级展示规则。

余额是当前门店 VIP 分档的事实来源；旧的 MemberLevel 保留用于兼容历史会员资料。
"""


def vip_level_for_balance(balance_cents: int | None) -> str | None:
    """余额大于 0 时返回 VIP 等级，每满 2000 元升一级。"""
    cents = int(balance_cents or 0)
    if cents <= 0:
        return None
    return f"VIP{1 + (cents - 1) // 200_000}"


def member_display_level(member_level: str, balance_cents: int | None) -> str:
    """有余额优先展示动态 VIP，无余额保留旧等级，兼容历史数据。"""
    return vip_level_for_balance(balance_cents) or member_level
