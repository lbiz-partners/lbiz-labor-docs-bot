"""원본 계산 엔진(node .mjs) 다리. 숫자는 전부 엔진에서 나온다(LLM·파이썬이 만들지 않음)."""
import json
import os
import subprocess
from pathlib import Path

ENGINE = Path(os.environ.get("NOMU_ENGINE_DIR", Path(__file__).resolve().parent.parent / "engine")) / "calc.mjs"


class EngineError(RuntimeError):
    pass


def run(op: str, payload: dict) -> dict:
    proc = subprocess.run(
        ["node", str(ENGINE)],
        input=json.dumps({"op": op, "input": payload}, ensure_ascii=False),
        capture_output=True, text=True, timeout=60,
    )
    try:
        out = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        raise EngineError(f"계산 엔진 응답을 읽지 못했습니다: {proc.stderr[:300]}") from e
    if not out.get("ok"):
        raise EngineError(out.get("error") or proc.stderr[:300])
    return out["result"]


def payroll(inp: dict) -> dict:
    return run("payroll", inp)


def minwage(inp: dict) -> dict:
    return run("minwage", inp)


def hourly_to_monthly(hourly: float, weekly_hours: float) -> dict:
    return run("hourlyToMonthly", {"hourlyWage": hourly, "weeklyHours": weekly_hours})


def week(inp: dict) -> dict:
    return run("week", inp)


def rates(year: int = 2026) -> dict:
    return run("rates", {"year": year})
