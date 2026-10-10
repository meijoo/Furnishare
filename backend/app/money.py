"""Integer-cent money rules: splits, limits, formatting."""


class InfeasibleSplit(ValueError):
    pass


def dollars(cents: int) -> str:
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    return f'{sign}${whole:,}' if frac == 0 else f'{sign}${whole:,}.{frac:02d}'


def solve_split(total_cents: int, members: list[str], limits: dict[str, int | None]) -> dict[str, int]:
    """Split as evenly as possible while respecting each member's limit.

    Water-filling: everyone pays min(limit, level) for the smallest level that covers the total.
    Leftover cents go to members in list order, never past a limit. A missing or None limit is unlimited.
    """
    if type(total_cents) is not int or total_cents <= 0:
        raise ValueError('Total must be positive integer cents')
    if not members or len(set(members)) != len(members):
        raise ValueError('Members must be unique and nonempty')
    caps = {}
    for m in members:
        limit = limits.get(m)
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError('Limits must be nonnegative integer cents')
        caps[m] = limit
    capacity = sum(c for c in caps.values() if c is not None)
    if all(c is not None for c in caps.values()) and capacity < total_cents:
        raise InfeasibleSplit(f'Combined limits {dollars(capacity)} are below {dollars(total_cents)}')

    shares = {m: 0 for m in members}
    remaining = total_cents
    open_members = list(members)
    while remaining > 0 and open_members:
        level = remaining // len(open_members)
        capped = [m for m in open_members if caps[m] is not None and caps[m] - shares[m] <= level]
        if capped:
            for m in capped:
                remaining -= caps[m] - shares[m]
                shares[m] = caps[m]
                open_members.remove(m)
            continue
        for m in open_members:
            shares[m] += level
        remaining -= level * len(open_members)
        for m in open_members:
            if remaining == 0:
                break
            if caps[m] is None or shares[m] < caps[m]:
                shares[m] += 1
                remaining -= 1
        break
    if remaining:
        raise InfeasibleSplit('Limits cannot cover the total')
    return shares


def validate_split(total_cents: int, shares: dict[str, int], limits: dict[str, int | None]) -> None:
    if sum(shares.values()) != total_cents:
        raise ValueError('Shares must sum exactly to total')
    for m, s in shares.items():
        if type(s) is not int or s < 0:
            raise ValueError('Shares must be nonnegative integer cents')
        if limits.get(m) is not None and s > limits[m]:
            raise ValueError(f'Share for {m} exceeds their limit')
