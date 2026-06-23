"""
main.py 내부 순수 헬퍼 함수 테스트 — 토큰 추정 / 기간 정규화 / 히스토리 구성 /
HF 에러 메시지 변환 / 제목 생성. (DB·네트워크 없이, 필요한 경우만 목 사용)
"""

import asyncio
import types

import main


# --- 토큰 추정 ---------------------------------------------------------------
def test_estimate_tokens_empty_is_zero():
    assert main.estimate_tokens("") == 0


def test_estimate_tokens_roughly_three_chars_each():
    """대략 3자당 1토큰. 'abcdef'(6자) → 2."""
    assert main.estimate_tokens("abcdef") == 2


def test_estimate_tokens_minimum_one():
    """짧아도 최소 1토큰."""
    assert main.estimate_tokens("a") == 1


def test_estimate_messages_tokens_sums_contents():
    msgs = [{"content": "abcdef"}, {"content": "abc"}]  # 2 + 1
    assert main.estimate_messages_tokens(msgs) == 3


def test_usage_from_api_when_present():
    """API가 usage를 주면 그 값을 그대로 쓴다."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert main.usage_from_api_or_estimate(usage, [], "") == (10, 5, 15)


def test_usage_from_api_fills_missing_total():
    """total이 없으면 prompt+completion으로 채운다."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    assert main.usage_from_api_or_estimate(usage, [], "") == (10, 5, 15)


def test_usage_falls_back_to_estimate():
    """usage가 없으면 추정치(입력 메시지 + 응답)를 쓴다."""
    msgs = [{"content": "abcdef"}]  # 2
    p, c, t = main.usage_from_api_or_estimate(None, msgs, "abc")  # c=1
    assert (p, c, t) == (2, 1, 3)


# --- 기간 정규화 -------------------------------------------------------------
def test_parse_date_valid():
    d = main._parse_date("2026-01-15")
    assert (d.year, d.month, d.day) == (2026, 1, 15)


def test_parse_date_invalid_returns_none():
    assert main._parse_date("not-a-date") is None
    assert main._parse_date(None) is None


def test_normalize_range_defaults_to_last_30_days():
    """값이 없으면 끝=오늘, 시작=끝-29일(총 30일)."""
    s, e = main.normalize_range(None, None)
    from datetime import date

    sd = date.fromisoformat(s)
    ed = date.fromisoformat(e)
    assert (ed - sd).days == 29


def test_normalize_range_swaps_when_start_after_end():
    """시작 > 끝이면 서로 바꾼다."""
    s, e = main.normalize_range("2026-02-10", "2026-02-01")
    assert s == "2026-02-01"
    assert e == "2026-02-10"


# --- 히스토리 구성 -----------------------------------------------------------
def _fake_convo(roles_and_texts):
    """build_history 테스트용 가짜 대화 객체."""
    msgs = [types.SimpleNamespace(role=r, content=t) for r, t in roles_and_texts]
    return types.SimpleNamespace(messages=msgs)


def test_build_history_maps_bot_to_assistant_and_prepends_system():
    convo = _fake_convo([("user", "안녕"), ("bot", "반가워요")])
    history = main.build_history(convo)
    assert history[0] == {"role": "system", "content": main.SYSTEM_PROMPT}
    assert history[1] == {"role": "user", "content": "안녕"}
    assert history[2] == {"role": "assistant", "content": "반가워요"}


def test_build_history_respects_window(monkeypatch):
    """system은 항상 유지하고, 나머지는 최근 HISTORY_WINDOW개만 보낸다."""
    monkeypatch.setattr(main, "HISTORY_WINDOW", 2)
    convo = _fake_convo([("user", "1"), ("bot", "2"), ("user", "3"), ("bot", "4")])
    history = main.build_history(convo)
    # system 1개 + 최근 2개
    assert len(history) == 3
    assert history[1]["content"] == "3"
    assert history[2]["content"] == "4"


# --- HF 에러 메시지 변환 -----------------------------------------------------
def test_friendly_error_model_not_supported():
    body = '{"error": {"code": "model_not_supported"}}'
    msg = main.friendly_hf_error(404, body, "some/model")
    assert "provider" in msg
    assert "some/model" in msg


def test_friendly_error_auth():
    assert "HF_TOKEN" in main.friendly_hf_error(401, "{}", "m")


def test_friendly_error_rate_limit():
    assert "한도" in main.friendly_hf_error(429, "{}", "m")


def test_friendly_error_generic_truncates_body():
    body = "x" * 500
    msg = main.friendly_hf_error(500, body, "m")
    # 본문은 200자까지만 노출
    assert "x" * 200 in msg
    assert "x" * 201 not in msg


# --- 제목 생성(목) -----------------------------------------------------------
def test_generate_title_uses_model_output(monkeypatch):
    async def fake_call_hf(prompt, model, **kwargs):
        return "파이썬 엑셀 파일 읽기", None

    monkeypatch.setattr(main, "call_hf", fake_call_hf)
    title = asyncio.run(main.generate_title("파이썬으로 엑셀 읽는 법", "m"))
    assert title == "파이썬 엑셀 파일 읽기"


def test_generate_title_falls_back_on_sentence(monkeypatch):
    """모델이 제목 대신 '문장'으로 답하면 원문으로 폴백한다."""
    async def fake_call_hf(prompt, model, **kwargs):
        return "다음과 같습니다.", None

    monkeypatch.setattr(main, "call_hf", fake_call_hf)
    title = asyncio.run(main.generate_title("엑셀 읽는 법 알려줘", "m"))
    assert title == "엑셀 읽는 법 알려줘"


def test_generate_title_truncates_to_40_chars(monkeypatch):
    async def fake_call_hf(prompt, model, **kwargs):
        return "가" * 100, None

    monkeypatch.setattr(main, "call_hf", fake_call_hf)
    title = asyncio.run(main.generate_title("길게", "m"))
    assert len(title) == 40
