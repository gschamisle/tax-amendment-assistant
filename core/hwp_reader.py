"""HWP/HWPX 텍스트 추출 — 업로드 조문안 검토용.

.hwpx: ZIP 내 Contents/section*.xml에서 텍스트 노드 추출.
.hwp(5.0 바이너리): olefile로 BodyText 섹션을 zlib 해제 후
HWPTAG_PARA_TEXT 레코드의 UTF-16LE 텍스트를 걷어낸다.
추출이 빈약하면 한컴오피스 COM(HWPFrame.HwpObject) 변환으로 폴백.
"""
from __future__ import annotations

import re
import struct
import zipfile
import zlib
from pathlib import Path

_HWPTAG_PARA_TEXT = 67  # HWPTAG_BEGIN(0x10) + 51

# 제어문자 분류 (HWP 5.0 스펙): 인라인/확장 컨트롤은 8 WCHAR를 차지한다
_CTRL_ONE_WCHAR = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def read_hwpx_text(path: str | Path) -> str:
    """HWPX(OWPML ZIP)에서 본문 텍스트 추출."""
    out: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = sorted(n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml", n))
        for name in names:
            xml = zf.read(name).decode("utf-8", "replace")
            # 문단 단위 개행 보존: </hp:p> → \n, 나머지 태그 제거
            xml = re.sub(r"</hp:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
            out.append(text)
    return _clean("\n".join(out))


def _hwp_records(data: bytes):
    """레코드 (tag, payload) 순회. 헤더 4바이트: tag(10b)|level(10b)|size(12b)."""
    pos = 0
    while pos + 4 <= len(data):
        (header,) = struct.unpack_from("<I", data, pos)
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, data[pos:pos + size]
        pos += size


def _para_text(payload: bytes) -> str:
    """HWPTAG_PARA_TEXT payload(UTF-16LE + 제어문자)에서 텍스트만 추출."""
    chars: list[str] = []
    i = 0
    n = len(payload) - 1
    while i < n:
        code = payload[i] | (payload[i + 1] << 8)
        if code < 32:
            if code in (10, 13):
                chars.append("\n")
            if code in _CTRL_ONE_WCHAR or code == 9:
                if code == 9:
                    chars.append("\t")
                i += 2
            else:
                i += 16  # 인라인·확장 컨트롤: 8 WCHAR
        else:
            chars.append(chr(code))
            i += 2
    return "".join(chars)


def read_hwp_text(path: str | Path) -> str:
    """HWP 5.0 바이너리에서 본문 텍스트 추출 (olefile 직접 파싱)."""
    import olefile

    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 0x01)
        sections = sorted(
            (e for e in ole.listdir() if e[0] == "BodyText"),
            key=lambda e: int(re.sub(r"\D", "", e[1]) or 0),
        )
        paras: list[str] = []
        for entry in sections:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            for tag, payload in _hwp_records(data):
                if tag == _HWPTAG_PARA_TEXT:
                    paras.append(_para_text(payload))
        return _clean("\n".join(paras))
    finally:
        ole.close()


def read_hwp_text_via_com(path: str | Path) -> str:
    """한컴오피스 COM으로 텍스트 추출 (설치되어 있을 때 폴백)."""
    import win32com.client

    hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        hwp.Open(str(Path(path).resolve()), "HWP", "forceopen:true")
        txt_path = Path(path).with_suffix(".extracted.txt")
        hwp.SaveAs(str(txt_path), "TEXT")
        text = txt_path.read_text(encoding="utf-16", errors="replace")
        txt_path.unlink(missing_ok=True)
        return _clean(text)
    finally:
        hwp.Quit()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(path: str | Path) -> str:
    """확장자에 따라 적절한 추출기 선택. 결과가 빈약하면 COM 폴백."""
    p = Path(path)
    if p.suffix.lower() == ".hwpx":
        return read_hwpx_text(p)
    text = ""
    try:
        text = read_hwp_text(p)
    except Exception:
        pass
    if len(text) < 100:
        try:
            text = read_hwp_text_via_com(p)
        except Exception:
            pass
    return text
