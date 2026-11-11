"""노무 서류 도우미 — 입력 JSON → 점검 → DOCX/PDF 생성기 (연도별 기준값은 RATES_CHECK.md).

만든 곳: 엘비즈파트너스. 저작권·라이선스·원본 엔진 출처는 NOTICE.md.

손님 사장님이 직접 넣은 값으로 양식을 채우고, 빈칸·계산 이상을 알려 주는 '작성 도구'다.
판단·대리 작성·상담은 하지 않는다.
"""
from pathlib import Path

def _read_version():
    p = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return p.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"

__version__ = _read_version()

# 결과물 맨 아래(도구 판 표시 옆)에 찍는 만든 곳 표시. 위치·문구는 NOTICE.md 「표기 위치」 참고.
ATTRIBUTION = "엘비즈파트너스 노무 서류 도우미"


def tool_version_label():
    """결과물(서류·점검결과)에 찍는 짧은 판 표시. 예: 도구 판 v1.1"""
    return f"도구 판 v{__version__}"
