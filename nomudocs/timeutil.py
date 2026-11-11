"""시각·날짜 계산 도우미."""
from datetime import date, timedelta

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


def _add_months(d, n):
    """d 에서 n개월 뒤 같은 날. 그 달에 그 날이 없으면 None."""
    y, m = divmod(d.month - 1 + n, 12)
    try:
        return date(d.year + y, m + 1, d.day)
    except ValueError:
        return None


def _month_last_day(y, m):
    nxt = date(y + (m // 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _end_of_months(a, n):
    """a 일부터 n개월이 끝나는 날(민법 §157·§160: 첫날 포함 기준으로 n개월 뒤 같은 날의 전날, 그날이 없으면 그 달 말일)."""
    if n == 0:
        return a - timedelta(days=1)
    same = _add_months(a, n)
    if same is not None:
        return same - timedelta(days=1)
    y, m = divmod(a.month - 1 + n, 12)
    return _month_last_day(a.year + y, m + 1)


def tenure_ymd(a, b):
    """a(첫날)부터 b(끝날)까지, 두 날 모두 포함한 기간을 (년, 개월, 일)로. 올림 없음.
    꽉 찬 달만 개월로 세고 남는 날은 일로 센다. a > b 이거나 날짜가 없으면 None."""
    a, b = parse_date(a), parse_date(b)
    if not a or not b or b < a:
        return None
    n = (b.year - a.year) * 12 + (b.month - a.month) + 1
    while n > 0 and _end_of_months(a, n) > b:
        n -= 1
    days = (b - _end_of_months(a, n)).days
    y, m = divmod(n, 12)
    return y, m, days


def tenure_text(a, b):
    """예: 「4년 8개월 8일」, 「1개월」, 「1일」. 0인 단위는 쓰지 않는다."""
    t = tenure_ymd(a, b)
    if t is None:
        return ""
    y, m, d = t
    parts = [f"{y}년" if y else "", f"{m}개월" if m else "", f"{d}일" if d else ""]
    return " ".join(x for x in parts if x)


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
