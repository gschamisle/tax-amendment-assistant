"""입법예고 의견 수집 어댑터 — 국민참여입법센터 크롤링 + 파일 폴백.

수집 경로를 이중화한다. 사이트 구조가 바뀌거나 접근이 막혀도 분석 파이프라인은
그대로 돌아가야 하기 때문이다:

  1. HTTP 어댑터 — `fetch_opinions()`. 목록 페이지를 순회하며 `OpinionRecord`로 파싱
  2. 파일 폴백  — `load_from_files()`. 브라우저에서 저장한 HTML / CSV / 이전 수집 JSON

파싱은 **셀렉터 설정(XPath) 기반**이다. 사이트 DOM이 바뀌면 `DEFAULT_SELECTORS`
또는 `data/opinion-selectors.json` 한 곳만 고치면 된다. 설정 셀렉터가 0건을 물어오면
반복 블록을 스스로 찾는 `parse_generic_html()`이 받아낸다.

개인정보·예의 원칙(코드로 강제):
  * 작성자 실명은 저장하지 않는다 — 수집 시점에 마스킹하고 안정 해시만 남긴다
  * 기본 요청 간격 1초, 식별 가능한 User-Agent, 페이지 수 상한
  * robots.txt를 확인하고 금지 시 경고한다
  * 수집 원문은 `data/opinions/`(gitignore)에만 저장한다
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
OPINION_DIR = ROOT / "data" / "opinions"
PROBE_DIR = OPINION_DIR / "_probe"
SELECTORS_PATH = ROOT / "data" / "opinion-selectors.json"

BASE_URL = "https://opinion.lawmaking.go.kr"
# 목록 URL 템플릿. {bill_id}·{page}가 채워진다. 페이지 파라미터명은 사이트 확인 후
# --page-param으로 바꿀 수 있다(전자정부 프레임워크 관행상 pageIndex가 기본).
LIST_URL_TEMPLATE = "{base}/gcom/ogLmPp/{bill_id}/myOpn?opnOpYn=Y&{page_param}={page}"

# HTTP 헤더는 latin-1로만 인코딩된다 — 한글을 넣으면 요청 자체가 실패한다
# (UnicodeEncodeError: 'latin-1' codec can't encode characters).
USER_AGENT = (
    "tax-amendment-assistant/0.1 (legislative-opinion-analysis; "
    "contact: MOEF Tax Policy Bureau)"
)
DEFAULT_DELAY = 1.0
DEFAULT_MAX_PAGES = 200

_DATE_RE = re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})")
_ID_IN_ATTR_RE = re.compile(r"(?:opnId|opinionId|seq|id)\W{0,3}(\d{3,})", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d{3,}")
_WS_RE = re.compile(r"[ \t ]+")
_MULTI_NL_RE = re.compile(r"\n{2,}")


# ── 레코드 ────────────────────────────────────────────────────────────────────

@dataclass
class OpinionRecord:
    """의견 1건. 작성자 실명은 담지 않는다."""
    opinion_id: str
    bill_id: str
    body: str
    title: str = ""
    posted_at: str = ""
    author_masked: str = ""
    author_hash: str = ""
    stance_raw: str = ""
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpinionRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ListSelectors:
    """목록 페이지 XPath 설정. row는 의견 1건을 감싸는 요소여야 한다."""
    row: str
    opinion_id: str = ""
    title: str = ""
    body: str = ""
    author: str = ""
    posted_at: str = ""
    stance: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ListSelectors":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# 사이트 확인 전 1차 추정치. `--probe`로 실제 DOM을 받아 확정한다.
DEFAULT_SELECTORS = ListSelectors(
    row='//div[contains(@class,"opnList")]//li | //table[contains(@class,"board")]//tbody/tr',
    opinion_id='.//@data-opn-id | .//a/@href | .//a/@onclick',
    title='.//*[contains(@class,"tit")]//text()',
    body='.//*[contains(@class,"cont") or contains(@class,"txt")]//text()',
    author='.//*[contains(@class,"name") or contains(@class,"writer")]//text()',
    posted_at='.//*[contains(@class,"date") or contains(@class,"reg")]//text()',
    stance='.//*[contains(@class,"opinion") or contains(@class,"agree")]//text()',
)


def load_selectors(path: Path | str | None = None) -> ListSelectors:
    """`data/opinion-selectors.json`이 있으면 그걸 쓰고, 없으면 기본값."""
    target = Path(path) if path else SELECTORS_PATH
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        return ListSelectors.from_dict(data)
    return DEFAULT_SELECTORS


# ── 개인정보 처리 ─────────────────────────────────────────────────────────────

def mask_author(name: str) -> str:
    """'홍길동' → '홍*동', '홍길' → '홍*'. 빈 값은 빈 값."""
    cleaned = _clean_text(name).replace(" ", "")
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned
    if len(cleaned) == 2:
        return cleaned[0] + "*"
    return cleaned[0] + "*" * (len(cleaned) - 2) + cleaned[-1]


def author_fingerprint(name: str) -> str:
    """같은 작성자 판별용 안정 해시. 원문 복원은 불가능하다."""
    cleaned = _clean_text(name).replace(" ", "")
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────

def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _normalize_date(value: str) -> str:
    m = _DATE_RE.search(str(value or ""))
    if not m:
        return _clean_text(value)[:20]
    year, month, day = m.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _synthetic_id(bill_id: str, posted_at: str, body: str) -> str:
    """DOM에 의견 ID가 없을 때 쓰는 대체 식별자.

    두 실패를 동시에 피해야 한다.

    ① 과소집계 — 복붙 캠페인이 절반을 차지하는 게 정상인데, 같은 문구를 낸 서로 다른
      제출이 같은 ID를 받으면 수집 단계에서 버려진다. 군집화가 세어야 할 건수가
      그 전에 사라진다. (날짜만 쓰면 같은 날 같은 문구가 전부 1건으로 접힌다.)
    ② 과대집계 — 목록은 최신순이고 예고 마감일에는 수집 중에도 새 의견이 올라와
      기존 의견이 뒤 페이지로 밀린다. 페이지 내 위치를 ID에 넣으면 밀려서 다시 만난
      같은 의견이 매번 새 ID를 받아 한 건이 십수 번 잡힌다(실측: 1건이 13회).

    그래서 위치는 빼고 **제출시각(분까지) + 본문 전체**로만 만든다. 같은 분에 같은
    문구를 낸 서로 다른 사람은 한 건으로 접히지만, 그 손실은 ②의 배수 과대집계보다
    훨씬 작다. posted_at에는 정규화 전 원문(시:분 포함)을 넘겨야 한다.
    """
    seed = f"{bill_id}|{posted_at}|{_clean_text(body)}"
    return "auto-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _extract_id(raw: str) -> str:
    if not raw:
        return ""
    m = _ID_IN_ATTR_RE.search(raw)
    if m:
        return m.group(1)
    digits = _DIGITS_RE.findall(raw)
    return digits[-1] if digits else ""


# ── HTML 파싱 ─────────────────────────────────────────────────────────────────

def _xpath_text(node: Any, expr: str) -> str:
    if not expr:
        return ""
    try:
        found = node.xpath(expr)
    except Exception:
        return ""
    parts = [
        (item if isinstance(item, str) else getattr(item, "text_content", lambda: "")())
        for item in (found if isinstance(found, list) else [found])
    ]
    return _clean_text(" ".join(p for p in parts if p))


def parse_list_html(
    html: str,
    bill_id: str = "",
    selectors: ListSelectors | None = None,
    *,
    source_url: str = "",
) -> list[OpinionRecord]:
    """설정 XPath로 목록 HTML을 파싱한다. 0건이면 generic 폴백으로 넘어간다.

    순수 함수 — 네트워크를 타지 않으므로 오프라인 테스트로 검증할 수 있다.
    """
    from lxml import html as lxml_html  # lxml은 이미 프로젝트 의존성

    if not html or not html.strip():
        return []
    sel = selectors or load_selectors()
    tree = lxml_html.fromstring(html)

    records: list[OpinionRecord] = []
    try:
        rows = tree.xpath(sel.row)
    except Exception:
        rows = []

    for row in rows:
        body = _xpath_text(row, sel.body)
        title = _xpath_text(row, sel.title)
        if not body and not title:
            continue
        author = _xpath_text(row, sel.author)
        raw_posted = _xpath_text(row, sel.posted_at)   # 분까지 있는 원문 — ID 재료
        posted_at = _normalize_date(raw_posted)
        opinion_id = _extract_id(_xpath_text(row, sel.opinion_id))
        record = OpinionRecord(
            opinion_id=opinion_id or _synthetic_id(bill_id, raw_posted, body or title),
            bill_id=str(bill_id),
            body=body or title,
            title=title if body else "",
            posted_at=posted_at,
            author_masked=mask_author(author),
            author_hash=author_fingerprint(author),
            stance_raw=_xpath_text(row, sel.stance),
            source_url=source_url,
        )
        records.append(record)

    if records:
        return records
    return parse_generic_html(html, bill_id, source_url=source_url)


_GENERIC_ROW_XPATHS: tuple[str, ...] = (
    "//table//tbody/tr",
    "//table//tr",
    '//ul[contains(@class,"list") or contains(@class,"opn") or contains(@class,"board")]/li',
    "//ul/li",
    '//div[contains(@class,"list")]/div',
    "//article",
)

_LABEL_AUTHOR_RE = re.compile(r"(?:작성자|성명|이름|등록자|신청인)\s*[:：]?\s*([^\n|]{1,20})")
_LABEL_DATE_RE = re.compile(r"(?:등록일|작성일|게시일|일자)\s*[:：]?\s*([^\n|]{1,20})")
_MIN_BODY_CHARS = 15


def parse_generic_html(
    html: str, bill_id: str = "", *, source_url: str = ""
) -> list[OpinionRecord]:
    """셀렉터 없이 반복 블록을 추론해 파싱하는 폴백.

    후보 XPath마다 "3건 이상 · 본문이 충분히 길고 · 날짜가 절반 이상 보이는" 블록
    집합을 찾아 가장 점수 높은 하나를 고른다. 사이트가 개편돼도 최소한 본문은 건진다.
    """
    from lxml import html as lxml_html

    if not html or not html.strip():
        return []
    tree = lxml_html.fromstring(html)

    best_rows: list[Any] = []
    best_score = 0.0
    for expr in _GENERIC_ROW_XPATHS:
        try:
            rows = tree.xpath(expr)
        except Exception:
            continue
        texts = [_clean_text(r.text_content()) for r in rows]
        usable = [t for t in texts if len(t) >= _MIN_BODY_CHARS]
        if len(usable) < 3:
            continue
        dated = sum(1 for t in usable if _DATE_RE.search(t))
        score = len(usable) * (1.0 + dated / len(usable))
        if score > best_score:
            best_score, best_rows = score, rows

    records: list[OpinionRecord] = []
    for row in best_rows:
        text = _clean_text(row.text_content())
        if len(text) < _MIN_BODY_CHARS:
            continue
        author_m = _LABEL_AUTHOR_RE.search(text)
        date_m = _LABEL_DATE_RE.search(text) or _DATE_RE.search(text)
        author = author_m.group(1).strip() if author_m else ""
        posted_at = _normalize_date(date_m.group(0) if date_m else "")

        body = text
        if author_m:
            body = body.replace(author_m.group(0), " ")
        if date_m:
            body = body.replace(date_m.group(0), " ")
        body = _clean_text(body)

        attrs = " ".join(
            f"{k}={v}" for k, v in row.attrib.items() if k in ("id", "data-id", "onclick")
        )
        links = " ".join(row.xpath(".//a/@href") + row.xpath(".//a/@onclick"))
        records.append(
            OpinionRecord(
                opinion_id=_extract_id(f"{attrs} {links}") or _synthetic_id(bill_id, posted_at, body),
                bill_id=str(bill_id),
                body=body,
                posted_at=posted_at,
                author_masked=mask_author(author),
                author_hash=author_fingerprint(author),
                source_url=source_url,
            )
        )
    return records


# ── JSON / CSV 파싱 ───────────────────────────────────────────────────────────

_JSON_BODY_KEYS = ("opnCn", "opinionContent", "content", "cn", "body", "의견내용", "내용", "본문")
_JSON_ID_KEYS = ("opnId", "opinionId", "seq", "id", "번호", "의견번호")
_JSON_DATE_KEYS = ("regDt", "registDate", "date", "등록일", "작성일")
_JSON_AUTHOR_KEYS = ("wrtrNm", "userName", "author", "name", "작성자", "성명", "이름")
_JSON_TITLE_KEYS = ("title", "opnSj", "제목")
_JSON_STANCE_KEYS = ("agreYn", "stance", "찬반", "의견구분")


def _pick(row: dict[str, Any], keys: Iterable[str]) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return _clean_text(value)
    return ""


def records_from_rows(rows: Iterable[dict[str, Any]], bill_id: str = "") -> list[OpinionRecord]:
    """dict 행(JSON 응답·CSV 행) → OpinionRecord. 열 이름은 한/영 모두 인식한다."""
    out: list[OpinionRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # 이전 수집 결과(JSON 캐시)면 그대로 복원한다.
        if "body" in row and "opinion_id" in row:
            out.append(OpinionRecord.from_dict(row))
            continue
        body = _pick(row, _JSON_BODY_KEYS)
        title = _pick(row, _JSON_TITLE_KEYS)
        if not body and not title:
            continue
        author = _pick(row, _JSON_AUTHOR_KEYS)
        posted_at = _normalize_date(_pick(row, _JSON_DATE_KEYS))
        opinion_id = _pick(row, _JSON_ID_KEYS)
        out.append(
            OpinionRecord(
                opinion_id=opinion_id or _synthetic_id(bill_id, posted_at, body or title),
                bill_id=str(row.get("bill_id") or bill_id),
                body=body or title,
                title=title if body else "",
                posted_at=posted_at,
                author_masked=mask_author(author),
                author_hash=author_fingerprint(author),
                stance_raw=_pick(row, _JSON_STANCE_KEYS),
            )
        )
    return out


def _iter_json_rows(payload: Any) -> list[dict[str, Any]]:
    """중첩 JSON에서 '의견 목록처럼 보이는' dict 리스트를 찾아낸다."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("opinions", "records", "resultList", "list", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list) and any(isinstance(r, dict) for r in value):
                return [r for r in value if isinstance(r, dict)]
        for value in payload.values():
            found = _iter_json_rows(value)
            if found:
                return found
    return []


def parse_json_payload(payload: Any, bill_id: str = "") -> list[OpinionRecord]:
    return records_from_rows(_iter_json_rows(payload), bill_id)


def load_from_files(paths: Iterable[Path | str], bill_id: str = "") -> list[OpinionRecord]:
    """저장한 HTML / CSV / JSON 파일에서 의견을 읽는다 (크롤링 폴백)."""
    records: list[OpinionRecord] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
        suffix = path.suffix.lower()
        if suffix in (".html", ".htm"):
            records.extend(
                parse_list_html(
                    path.read_text(encoding="utf-8", errors="replace"),
                    bill_id,
                    source_url=path.resolve().as_uri(),
                )
            )
        elif suffix == ".json":
            records.extend(parse_json_payload(json.loads(path.read_text(encoding="utf-8")), bill_id))
        elif suffix in (".csv", ".tsv"):
            delimiter = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                records.extend(records_from_rows(csv.DictReader(fh, delimiter=delimiter), bill_id))
        elif suffix in (".xlsx", ".xls"):
            raise ValueError(
                f"{path.name}: 엑셀은 직접 지원하지 않습니다. CSV로 저장해 다시 넣어 주세요 "
                "(엑셀 → 다른 이름으로 저장 → CSV UTF-8)."
            )
        else:
            raise ValueError(f"{path.name}: 지원하지 않는 형식입니다 (.html/.csv/.tsv/.json)")
    return dedupe_records(records)


TITLE_SEP = " ; "


def merge_title(kept: OpinionRecord, other: OpinionRecord) -> None:
    """접힌 중복이 달고 있던 '대상 개정항목'을 살아남는 레코드에 합친다.

    사이트는 의견 1건을 **그 의견이 지정한 개정항목마다 한 행씩** 렌더링한다
    (실측: 1페이지 20행 = 고유 의견 8건, 한 의견이 13행). 그래서 목록의
    '입법의견건수'는 의견 수가 아니라 (의견 × 대상항목) 행 수다.

    본문 기준으로 접지 않으면 한 사람의 의견이 열세 번 집계되고, 그냥 접으면
    어느 개정항목에 달린 의견인지가 사라진다 — 분류에서 가장 쓸모 있는 축이다.
    그래서 접되 대상만 합쳐 둔다.
    """
    if not other.title or other.title == kept.title:
        return
    parts = kept.title.split(TITLE_SEP) if kept.title else []
    if other.title not in parts:
        parts.append(other.title)
        kept.title = TITLE_SEP.join(parts)


def dedupe_records(records: Iterable[OpinionRecord]) -> list[OpinionRecord]:
    """의견 ID 기준 중복 제거 (수집 순서 유지, 대상 개정항목은 합침)."""
    index: dict[str, OpinionRecord] = {}
    out: list[OpinionRecord] = []
    for r in records:
        kept = index.get(r.opinion_id)
        if kept is not None:
            merge_title(kept, r)
            continue
        index[r.opinion_id] = r
        out.append(r)
    return out


# ── 저장 / 로드 ───────────────────────────────────────────────────────────────

def cache_path(bill_id: str) -> Path:
    return OPINION_DIR / f"{bill_id}.json"


def save_records(bill_id: str, records: list[OpinionRecord], *, meta: dict[str, Any] | None = None) -> Path:
    OPINION_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(bill_id)
    payload = {
        "bill_id": str(bill_id),
        "count": len(records),
        "meta": meta or {},
        "opinions": [r.to_dict() for r in records],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_records(bill_id: str) -> list[OpinionRecord]:
    path = cache_path(bill_id)
    if not path.exists():
        raise FileNotFoundError(
            f"수집 결과가 없습니다: {path}\n"
            f"먼저 `uv run python scripts/fetch_opinions.py --bill {bill_id}` 를 실행하세요."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [OpinionRecord.from_dict(r) for r in payload.get("opinions", [])]


# ── HTTP 수집 ─────────────────────────────────────────────────────────────────

@dataclass
class FetchReport:
    bill_id: str
    pages_fetched: int = 0
    records: list[OpinionRecord] = field(default_factory=list)
    stopped_reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _build_session():
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    return session


def robots_allows(url: str, session=None) -> tuple[bool, str]:
    """robots.txt 확인. 판단 불가하면 (True, 사유)로 통과시키되 사유를 남긴다."""
    from urllib.robotparser import RobotFileParser

    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        sess = session or _build_session()
        resp = sess.get(robots_url, timeout=10)
        if resp.status_code >= 400:
            return True, f"robots.txt 조회 실패({resp.status_code}) — 확인 없이 진행"
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        allowed = parser.can_fetch(USER_AGENT, url)
        return allowed, "" if allowed else "robots.txt가 이 경로의 수집을 금지합니다"
    except Exception as exc:  # 네트워크 문제로 수집 자체를 막지는 않는다
        return True, f"robots.txt 확인 불가({exc}) — 확인 없이 진행"


def list_url(bill_id: str, page: int, *, page_param: str = "pageIndex", base: str = BASE_URL) -> str:
    return LIST_URL_TEMPLATE.format(base=base, bill_id=bill_id, page_param=page_param, page=page)


def probe(bill_id: str, *, page_param: str = "pageIndex", base: str = BASE_URL) -> Path:
    """1페이지 원문 HTML과 응답 헤더를 저장한다 — 셀렉터 확정용."""
    session = _build_session()
    url = list_url(bill_id, 1, page_param=page_param, base=base)
    resp = session.get(url, timeout=20)
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    html_path = PROBE_DIR / f"{bill_id}-page1.html"
    html_path.write_text(resp.text, encoding="utf-8")
    (PROBE_DIR / f"{bill_id}-page1.headers.json").write_text(
        json.dumps(
            {"url": url, "status": resp.status_code, "headers": dict(resp.headers)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return html_path


def fetch_opinions(
    bill_id: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    delay: float = DEFAULT_DELAY,
    page_param: str = "pageIndex",
    base: str = BASE_URL,
    selectors: ListSelectors | None = None,
    session=None,
    check_robots: bool = True,
    on_page=None,
    known: Iterable[OpinionRecord] | None = None,
) -> FetchReport:
    """목록 페이지를 순회하며 의견을 수집한다.

    페이지 파라미터가 사이트와 맞지 않으면 매 페이지가 같은 내용을 돌려준다. 새 의견이
    하나도 없으면 즉시 멈춰서 같은 페이지를 수백 번 긁는 사고를 막는다.

    known을 주면(증분 수집) 이미 가진 의견을 처음부터 '본 것'으로 깔고 시작한다.
    목록이 최신순이라 새 의견은 앞 페이지에 쌓이므로, 아는 의견만 나오는 페이지에
    닿으면 그 뒤는 전부 아는 것이다 — 거기서 멈춘다. 접수기간 중 매일 돌려도
    새로 올라온 몫만 받아 온다. report.records에는 **새 의견만** 담긴다.
    """
    report = FetchReport(bill_id=str(bill_id))
    sess = session or _build_session()
    sel = selectors or load_selectors()

    first_url = list_url(bill_id, 1, page_param=page_param, base=base)
    if check_robots:
        allowed, note = robots_allows(first_url, sess)
        if note:
            report.warnings.append(note)
        if not allowed:
            report.stopped_reason = "robots.txt 금지"
            return report

    seen: dict[str, OpinionRecord] = {r.opinion_id: r for r in (known or [])}
    known_count = len(seen)
    for page in range(1, max_pages + 1):
        url = list_url(bill_id, page, page_param=page_param, base=base)
        resp = sess.get(url, timeout=20)
        if resp.status_code >= 400:
            report.stopped_reason = f"HTTP {resp.status_code} (page {page})"
            break
        report.pages_fetched = page

        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type.lower():
            page_records = parse_json_payload(resp.json(), bill_id)
        else:
            page_records = parse_list_html(resp.text, bill_id, sel, source_url=urljoin(base, url))

        # 같은 의견이 대상 개정항목마다 한 행씩 나온다 → 접되 대상은 합친다
        fresh: list[OpinionRecord] = []
        for r in page_records:
            kept = seen.get(r.opinion_id)
            if kept is not None:
                merge_title(kept, r)
                continue
            seen[r.opinion_id] = r
            fresh.append(r)
        if not fresh:
            if not page_records:
                report.stopped_reason = "파싱 결과 0건 — 셀렉터 확인 필요(--probe)"
            elif known_count:
                # 최신순이라 이 뒤는 전부 이미 가진 의견이다
                report.stopped_reason = (
                    f"기존 수집분에 도달 (page {page}) — 여기부터는 이미 가진 의견입니다"
                )
            else:
                report.stopped_reason = (
                    "새 의견 없음 — 마지막 페이지이거나 페이지 파라미터가 맞지 않습니다"
                )
            break

        report.records.extend(fresh)
        if on_page:
            on_page(page, len(fresh), len(report.records))
        if delay:
            time.sleep(delay)
    else:
        report.stopped_reason = f"최대 페이지({max_pages}) 도달"

    return report
