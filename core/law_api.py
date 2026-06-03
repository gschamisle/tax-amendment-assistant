"""법제처 Open API 클라이언트."""
import base64
import hashlib
import re
import requests
import xml.etree.ElementTree as ET
from typing import Any
from config import LAW_API_KEY, LAW_SEARCH_URL, LAW_SERVICE_URL, OPENAI_API_KEY

_IMG_SRC_RE = re.compile(r'<img[^>]*src="([^"]*flDownload[^"]*)"[^>]*>', re.IGNORECASE)
_IMG_RE = re.compile(r'<img[^>]*alt="([^"]*)"[^>]*>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')

_IMG_CACHE_MAX = 300
_img_cache: dict[str, str] = {}


def _ocr_image_url(url: str, openai_key: str) -> str:
    """법제처 이미지(GIF) → GPT-4o 비전으로 텍스트 추출."""
    if url in _img_cache:
        return _img_cache[url]
    try:
        img_bytes = requests.get(url, timeout=10).content
        b64 = base64.b64encode(img_bytes).decode()
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/gif;base64,{b64}"}},
                    {"type": "text",
                     "text": "이 이미지는 한국 세법 조문의 표(세율표 등)입니다. "
                             "표의 내용을 텍스트로 그대로 옮겨 주세요. "
                             "열 구분은 ' | '로, 행 구분은 줄바꿈으로 표현하세요. "
                             "설명 없이 표 내용만 출력하세요."},
                ],
            }],
            max_tokens=500,
        )
        result = resp.choices[0].message.content or ""
        if len(_img_cache) >= _IMG_CACHE_MAX:
            try:
                del _img_cache[next(iter(_img_cache))]
            except StopIteration:
                pass
        _img_cache[url] = result
        return result
    except Exception:
        return "[표 — 이미지 변환 실패]"


def _clean(text: str, openai_key: str = "") -> str:
    """법제처 img 태그 → GPT-4o OCR 텍스트 치환, 나머지 HTML 태그 제거."""
    def replace_img(m: re.Match) -> str:
        url = m.group(1)
        if openai_key:
            return _ocr_image_url(url, openai_key)
        # API 키 없으면 alt 텍스트로 대체
        alt_m = re.search(r'alt="([^"]*)"', m.group(0))
        return f"[{alt_m.group(1) if alt_m else '표'}]"

    text = _IMG_SRC_RE.sub(replace_img, text)
    text = _TAG_RE.sub("", text)
    return text.strip()


def search_laws(keyword: str, api_key: str = "", display: int = 20, page: int = 1) -> list[dict[str, str]]:
    """법령명으로 검색. 결과: [{법령명, MST, 법령종류}]"""
    key = api_key or LAW_API_KEY
    params = {
        "OC": key,
        "target": "law",
        "type": "JSON",
        "query": keyword,
        "display": display,
        "page": page,
    }
    resp = requests.get(LAW_SEARCH_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    laws = data.get("LawSearch", {}).get("law", [])
    if isinstance(laws, dict):
        laws = [laws]
    return [
        {
            "법령명": law.get("법령명한글", ""),
            "MST": law.get("법령일련번호", ""),
            "종류": law.get("법령구분명", ""),
        }
        for law in laws
    ]


def list_all_laws(api_key: str = "", max_pages: int = 30, display: int = 100) -> list[dict[str, str]]:
    """법제처 법령 목록을 페이지 단위로 조회한다.

    전체 검색은 API 호출량이 크므로 UI에서 max_pages로 상한을 둔다.
    """
    all_laws: list[dict[str, str]] = []
    for page in range(1, max_pages + 1):
        laws = search_laws("", api_key, display=display, page=page)
        if not laws:
            break
        all_laws.extend(laws)
        if len(laws) < display:
            break
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for law in all_laws:
        key = law.get("MST") or law.get("법령명", "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(law)
    return deduped


def get_law_text(law_mst: str, api_key: str = "", openai_key: str = "") -> dict[str, Any]:
    """MST로 법령 전문 조회. 결과: {법령명, 조문목록: [{조번호, 조제목, 내용}]}"""
    key = api_key or LAW_API_KEY
    oai_key = openai_key  # caller passes "" to skip OCR; don't fall back to global
    params = {
        "OC": key,
        "target": "law",
        "MST": law_mst,
        "type": "XML",
    }
    resp = requests.get(LAW_SERVICE_URL, params=params, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    law_name = root.findtext("기본정보/법령명_한글", "")
    articles: list[dict[str, str]] = []
    for jo in root.findall(".//조문단위"):
        if jo.findtext("조문여부", "") != "조문":
            continue
        no = jo.findtext("조문번호", "")
        sub = jo.findtext("조문가지번호", "")
        title = jo.findtext("조문제목", "")

        parts: list[str] = []
        jo_text = _clean(jo.findtext("조문내용") or "", oai_key)
        if jo_text:
            parts.append(jo_text)

        for hang in jo.findall("항"):
            hang_text = _clean(hang.findtext("항내용") or "", oai_key)
            if hang_text:
                parts.append(hang_text)
            for ho in hang.findall("호"):
                ho_text = _clean(ho.findtext("호내용") or "", oai_key)
                if ho_text:
                    parts.append("  " + ho_text)
                for mok in ho.findall("목"):
                    mok_text = _clean(mok.findtext("목내용") or "", oai_key)
                    if mok_text:
                        parts.append("    " + mok_text)

        articles.append({
            "조번호": f"{no}의{sub}" if sub else no,
            "제목": title,
            "내용": "\n".join(parts),
        })
    digest = hashlib.sha256(
        "\n".join(
            f"{a['조번호']}|{a['제목']}|{a['내용']}"
            for a in articles
        ).encode("utf-8"),
    ).hexdigest()[:16]
    return {
        "법령명": law_name,
        "MST": law_mst,
        "시행일자": (root.findtext("기본정보/시행일자", "") or "").strip(),
        "공포일자": (root.findtext("기본정보/공포일자", "") or "").strip(),
        "조문목록": articles,
        "article_count": len(articles),
        "content_hash": digest,
    }


def get_article(law_mst: str, jo_no: str, api_key: str = "", openai_key: str = "") -> str:
    """특정 조문 텍스트 반환."""
    data = get_law_text(law_mst, api_key, openai_key)
    for art in data["조문목록"]:
        if art["조번호"] == jo_no:
            return art["내용"]
    return ""
