"""병행법령 매트릭스 골든 recall·스키마 테스트 (오프라인)."""
from __future__ import annotations

import sys

from core.parallel_golden import golden_entries
from core.parallel_matrix import matrix_available, matrix_meta, parallel_hits

_REQUIRED_FIELDS = ("target_law", "target_article", "relation_type", "confidence", "source")


def main() -> int:
    if not matrix_available():
        print("SKIP: parallel-law-matrix.json 없음 — build_parallel_matrix.py 실행 필요")
        return 0

    meta = matrix_meta()
    assert meta.get("entry_count", 0) > 0, meta
    assert meta.get("law_versions"), meta

    # 골든 recall 100%: 매뉴얼 매핑이 매트릭스에 전부 있어야 함
    missing: list[str] = []
    checked = 0
    for key, items in golden_entries().items():
        law, jo = key.split("|", 1)
        hits = parallel_hits(law, jo)
        have = {(h["target_law"], h["target_article"]) for h in hits}
        # 조번호 수준 비교 (표기 차이 허용)
        have_laws = {h["target_law"] for h in hits}
        for item in items:
            checked += 1
            if (item["target_law"], item["target_article"]) in have:
                continue
            if item["target_law"] in have_laws:
                # 같은 법령의 다른 표기 — 조번호로 재확인
                from scripts.build_parallel_matrix import _article_jo
                want_jo = _article_jo(item["target_article"])
                if any(
                    h["target_law"] == item["target_law"]
                    and _article_jo(h["target_article"]) == want_jo
                    for h in hits
                ):
                    continue
            missing.append(f"{key} → {item['target_law']} {item['target_article']}")
    assert not missing, "골든 매핑 누락:\n" + "\n".join(missing)

    # 스키마: 대표 키의 모든 엔트리에 필수 필드
    sample = parallel_hits("법인세법", "27의2")
    assert sample, "법인세법 27의2 엔트리 없음"
    for e in sample:
        for f in _REQUIRED_FIELDS:
            assert e.get(f), (f, e)
    assert any(
        e["target_law"] == "소득세법" and e["target_article"] == "제33조의2"
        for e in sample
    ), sample

    # 조번호 표기 정규화 조회 ("제27조의2"로도 동일 결과)
    assert parallel_hits("법인세법", "제27조의2") == sample

    print(f"ALL OK (golden={checked}, entry_count={meta['entry_count']}, "
          f"stage={meta.get('stage')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
