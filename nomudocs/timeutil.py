"""시각·날짜 계산 도우미."""
from datetime import date

DAYS = ["월", "화", "수", "목", "금", "토", "일"]


def to_min(t):
    if not t or ":" not in str(t):
        return None
    h, m = str(t).split(":")[:2]
    return int(h) * 60 + int(m)


def span_minutes(start, end):
    s, e = to_min(start), to_min(end)
    if s is None or e is None:
        return None
    if e <= s:
        e += 1440
    return e - s


def night_minutes(start, end):
    """22:00~06:00 과 겹치는 분."""
    s, e = to_min(start), to_min(end)
    if s is None or e is None:
        return 0
    if e <= s:
        e += 1440
    total = 0
    for base in (-1440, 0, 1440):
        for ns, ne in ((22 * 60, 30 * 60),):
            a, b = max(s, ns + base), min(e, ne + base)
            total += max(0, b - a)
    return total


def break_minutes(breaks):
    tot = 0
    for b in breaks or []:
        if isinstance(b, (int, float)):
            tot += b
        else:
            m = span_minutes(b.get("start"), b.get("end"))
            tot += m or 0
    return tot


def day_work_hours(start, end, brk_min):
    span = span_minutes(start, end)
    if span is None:
        return None
    return max(0, span - (brk_min or 0)) / 60


def parse_date(s):
    if not s:
        return None
    y, m, d = [int(x) for x in str(s)[:10].split("-")]
    return date(y, m, d)


def age_on(birth, on):
    b, o = parse_date(birth), parse_date(on)
    if not b or not o:
        return None
    return o.year - b.year - ((o.month, o.day) < (b.month, b.day))


def months_between(a, b):
    a, b = parse_date(a), parse_date(b)
    if not a or not b:
        return None
    return (b.year - a.year) * 12 + (b.month - a.month) + (1 if b.day >= a.day else 0)


def weekly_holiday_hours(weekly_hours):
    """주휴시간 = 주 소정근로시간 15시간 이상일 때 min(주소정,40)/40×8 (원본 엔진과 같은 식)."""
    if weekly_hours is None or weekly_hours < 15:
        return 0.0
    return min(weekly_hours, 40) / 40 * 8


def monthly_paid_hours(weekly_hours):
    """월 유급 환산시간(소정+주휴)×(365/7/12). 주40시간이면 고시 기준 209시간."""
    if weekly_hours is None:
        return None
    if abs(weekly_hours - 40) < 1e-9:
        return 209
    return round((weekly_hours + weekly_holiday_hours(weekly_hours)) * 365 / 7 / 12, 2)
