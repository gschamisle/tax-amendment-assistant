"""병행법령 매트릭스 (오프라인 JSON → 런타임 조회).

`scripts/build_parallel_matrix.py`가 생성하는 data/parallel-law-matrix.json을
로드해 (법령명, 조번호) → 병행·연관 검토 대상 조문 목록을 반환한다.
런타임에는 LLM 호출 없이 조회만 수행한다.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

_JSON_PATH = Path(__file__).resolve().parents[1] / "data" / "parallel-law-matrix.json"

# "제27조의2" / "제27의2조" → "27의2", "제45조" → "45"
_JO_NORM_RE = re.compile(r"^제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)$")


def normalize_jo(jo_no: str) -> str:
    """조번호를 API 형식("27의2", "45")으로 정규화."""
    jo_no = str(jo_no).strip()
    m = _JO_NORM_RE.match(jo_no)
    if not m:
        return jo_no
    if m.group(1) is not None:
        return f"{m.group(1)}의{m.group(2)}"
    jo, sub = m.group(3), m.group(4)
    return f"{jo}의{sub}" if sub else jo


def matrix_key(law_name: str, jo_no: str) -> str:
    return f"{str(law_name).strip()}|{normalize_jo(jo_no)}"


@functools.lru_cache(maxsize=1)
def _load() -> tuple[dict[str, list[dict]], dict]:
    if not _JSON_PATH.is_file():
        return {}, {}
    data = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    meta = {
        "built_at": data.get("built_at", ""),
        "stage": data.get("stage", 0),
        "law_versions": data.get("law_versions", {}),
        "semantic_pairs": data.get("semantic_pairs", []),
        "entry_count": data.get("entry_count", 0),
    }
    return data.get("entries", {}), meta


def matrix_available() -> bool:
    entries, _ = _load()
    return bool(entries)


def matrix_meta() -> dict:
    _, meta = _load()
    return meta


def parallel_hits(law_name: str, jo_no: str) -> list[dict]:
    """(법령명, 조번호)에 등록된 병행·연관 검토 대상 목록."""
    entries, _ = _load()
    return list(entries.get(matrix_key(law_name, jo_no), []))


def covered_laws() -> list[str]:
    """매트릭스가 커버하는 기준 법령 목록."""
    _, meta = _load()
    return sorted(meta.get("law_versions", {}).keys())


def semantic_pair_covered(law_a: str, law_b: str) -> bool:
    """두 법령 쌍이 3단계 LLM 전수 판별을 거쳤는지.

    True면 런타임 병행 검사에서 라이브 LLM 호출이 불필요하다 —
    매트릭스에 없는 조합은 판별 결과 '동일 취지 아님'을 의미한다.
    """
    _, meta = _load()
    want = tuple(sorted((str(law_a).strip(), str(law_b).strip())))
    return any(tuple(sorted(p)) == want for p in meta.get("semantic_pairs", []))
