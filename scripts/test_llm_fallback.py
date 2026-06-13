# -*- coding: utf-8 -*-
"""LLM 모델 폴백 로직 오프라인 테스트 — API 호출 없이 _structured_call 분기만 검증.

Fable 5가 막혔을 때(404/403) Opus 4.8로 자동 폴백하는지, 그리고 스키마 오류 등
모델 가용성과 무관한 에러는 폴백하지 않고 그대로 올라가는지 확인한다.
"""
from __future__ import annotations

import sys

import anthropic
import httpx

import core.llm_review as m


def _make_status_error(cls, status: int):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    return cls("blocked", response=resp, body=None)


def test_fallback_on_unavailable(monkeypatch_calls):
    """첫 모델이 NotFoundError → 다음 후보로 폴백."""
    attempts = []

    def fake_call_one(client, model, system, user_text, schema):
        attempts.append(model)
        if model == "claude-fable-5":
            raise _make_status_error(anthropic.NotFoundError, 404)
        return {"ok": model}

    monkeypatch_calls(fake_call_one)
    result = m._structured_call(
        ["claude-fable-5", "claude-opus-4-8"], "sys", "user", {}, api_key="dummy"
    )
    assert attempts == ["claude-fable-5", "claude-opus-4-8"], attempts
    assert result == {"ok": "claude-opus-4-8"}, result


def test_permission_denied_also_falls_back(monkeypatch_calls):
    """403(권한 없음)도 폴백 트리거."""

    def fake_call_one(client, model, system, user_text, schema):
        if model == "claude-fable-5":
            raise _make_status_error(anthropic.PermissionDeniedError, 403)
        return {"ok": model}

    monkeypatch_calls(fake_call_one)
    result = m._structured_call(["claude-fable-5", "claude-opus-4-8"], "s", "u", {})
    assert result == {"ok": "claude-opus-4-8"}


def test_schema_error_does_not_fall_back(monkeypatch_calls):
    """스키마 오류(BadRequest)는 폴백하지 않고 그대로 올라온다."""

    def fake_call_one(client, model, system, user_text, schema):
        raise _make_status_error(anthropic.BadRequestError, 400)

    monkeypatch_calls(fake_call_one)
    try:
        m._structured_call(["claude-fable-5", "claude-opus-4-8"], "s", "u", {})
    except anthropic.BadRequestError:
        return  # 기대 동작
    raise AssertionError("BadRequestError가 폴백돼 삼켜졌다 — 회귀")


def test_all_unavailable_raises(monkeypatch_calls):
    """모든 후보가 막히면 명확한 RuntimeError."""

    def fake_call_one(client, model, system, user_text, schema):
        raise _make_status_error(anthropic.NotFoundError, 404)

    monkeypatch_calls(fake_call_one)
    try:
        m._structured_call(["claude-fable-5", "claude-opus-4-8"], "s", "u", {})
    except RuntimeError as exc:
        assert "사용 가능한 모델이 없습니다" in str(exc)
        return
    raise AssertionError("모든 모델 불가인데 RuntimeError가 안 났다")


def main() -> int:
    # 가벼운 수동 monkeypatch: _client는 더미로, _call_one은 테스트별로 교체
    def make_monkeypatch():
        def patcher(fake):
            m._client = lambda api_key="": object()
            m._call_one = fake
        return patcher

    for fn in (
        test_fallback_on_unavailable,
        test_permission_denied_also_falls_back,
        test_schema_error_does_not_fall_back,
        test_all_unavailable_raises,
    ):
        orig_client, orig_call = m._client, m._call_one
        try:
            fn(make_monkeypatch())
        finally:
            m._client, m._call_one = orig_client, orig_call

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
