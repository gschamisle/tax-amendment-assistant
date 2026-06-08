"""간접 연쇄 유형 분류 테스트."""
from __future__ import annotations

import sys

from core.related_article_hints import lookup_related_hints
from core.related_relation_types import classify_relation, relation_label


def main() -> int:
    hints = lookup_related_hints("소득세법", "129", "1", "3")
    types = {classify_relation(h["law_name"], h["article"], h["reason"], h.get("relation_type", "")) for h in hints}
    assert "rate_application" in types
    assert "calculation_rule" in types
    assert "law_to_decree" in types
    assert len(types) >= 3, types

    label = relation_label("rate_application")
    assert "세율" in label

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
