"""Focused tests for security boundaries, limits and failure paths.

Run with:  .venv\\Scripts\\python -m pytest
These use a fake provider, so they never call OpenAI or cost anything.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from server.ai_provider import ProviderError
from server.config import load_settings
from server.main import create_app

H = {"X-Kinora": "1"}


class FakeProvider:
    demo = False

    def __init__(self):
        self.reply_calls = []
        self.speak_calls = 0
        self.fail_next = None
        self.transcript = "hello there"

    def reply(self, instructions, messages, max_output_tokens):
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err
        self.reply_calls.append({"instructions": instructions, "messages": messages, "max": max_output_tokens})
        return f"reply {len(self.reply_calls)}", {"input_tokens": 10, "output_tokens": 5}

    def transcribe(self, filename, data, content_type):
        return self.transcript

    def speak(self, text, voice, voice_instructions):
        self.speak_calls += 1
        return b"ID3fake-mp3"


def make(**overrides):
    base = dataclasses.replace(load_settings(), openai_api_key="test", force_demo=False, access_code="",
                               admin_token="", rate_limit_per_minute=1000, client_daily_replies=100)
    settings = dataclasses.replace(base, **overrides)
    provider = FakeProvider()
    app = create_app(settings, provider)
    return app, provider


def start(client):
    r = client.post("/api/sessions", json={"companion_id": "mira"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def send(client, sid, text="hi", cid="msg-0000001", **extra):
    return client.post(f"/api/sessions/{sid}/messages",
                       json={"client_message_id": cid, "text": text, **extra}, headers=H)


def test_config_never_exposes_instructions_or_key():
    app, _ = make()
    body = TestClient(app).get("/api/config").text
    assert "instructions" not in body
    assert "You are Mira" not in body
    assert "test" not in body.split('"mode"')[0]  # api key value not echoed
    assert '"mode":"connected"' in body


def test_mutating_requests_need_custom_header():
    app, _ = make()
    c = TestClient(app)
    assert c.post("/api/sessions", json={"companion_id": "mira"}).status_code == 403


def test_unknown_companion_rejected():
    app, _ = make()
    r = TestClient(app).post("/api/sessions", json={"companion_id": "nobody"}, headers=H)
    assert r.status_code == 400


@pytest.mark.parametrize("companion_id,marker", [("sunny", "You are Sunny"), ("rowan", "You are Rowan")])
def test_each_companion_gets_its_own_instructions(companion_id, marker):
    app, provider = make()
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"companion_id": companion_id}, headers=H).json()["session_id"]
    send(c, sid)
    assert marker in provider.reply_calls[0]["instructions"]
    assert "You are Mira" not in provider.reply_calls[0]["instructions"]


def test_other_browser_cannot_touch_session():
    app, _ = make()
    alice, bob = TestClient(app), TestClient(app)
    sid = start(alice)
    assert send(bob, sid).status_code == 404
    assert bob.post(f"/api/sessions/{sid}/speech", json={"message_id": "x"}, headers=H).status_code == 404
    assert bob.delete(f"/api/sessions/{sid}", headers=H).status_code == 404
    assert send(alice, sid).status_code == 200


def test_duplicate_send_returns_same_reply_without_second_call():
    app, provider = make()
    c = TestClient(app)
    sid = start(c)
    first = send(c, sid, cid="same-id-123").json()
    second = send(c, sid, cid="same-id-123").json()
    assert first["reply"]["id"] == second["reply"]["id"]
    assert len(provider.reply_calls) == 1


def test_sessions_do_not_share_context():
    app, provider = make()
    c = TestClient(app)
    s1, s2 = start(c), start(c)
    send(c, s1, text="secret about s1", cid="a-00000001")
    send(c, s2, text="hello s2", cid="b-00000001")
    second_context = " ".join(m["content"] for m in provider.reply_calls[1]["messages"])
    assert "secret about s1" not in second_context


def test_prompt_includes_shared_policy_and_companion():
    app, provider = make()
    c = TestClient(app)
    send(c, start(c), reply_length="full")
    call = provider.reply_calls[0]
    assert "Do not invent specific phone numbers" in call["instructions"]
    assert "You are Mira" in call["instructions"]
    assert call["max"] == 900
    assert call["messages"][0]["role"] == "assistant"  # opening line kept in context


def test_message_size_limits():
    app, _ = make(max_message_chars=10)
    c = TestClient(app)
    sid = start(c)
    assert send(c, sid, text="   ").status_code == 400
    assert send(c, sid, text="x" * 11).json()["error"]["code"] == "message_too_long"


def test_daily_reply_allowance_enforced():
    app, _ = make(client_daily_replies=2)
    c = TestClient(app)
    sid = start(c)
    assert send(c, sid, cid="m-00000001").status_code == 200
    assert send(c, sid, cid="m-00000002").status_code == 200
    r = send(c, sid, cid="m-00000003")
    assert r.status_code == 429 and r.json()["error"]["code"] == "client_budget"


def test_global_allowance_enforced_across_browsers():
    app, _ = make(global_daily_replies=1)
    a, b = TestClient(app), TestClient(app)
    assert send(a, start(a)).status_code == 200
    r = send(b, start(b))
    assert r.status_code == 429 and r.json()["error"]["code"] == "global_budget"


def test_failed_provider_call_refunds_allowance_and_explains():
    app, provider = make(client_daily_replies=1)
    c = TestClient(app)
    sid = start(c)
    provider.fail_next = ProviderError("timeout", "The AI service took too long to answer. Try again.", 504)
    r = send(c, sid, cid="t-00000001")
    assert r.status_code == 504 and "too long" in r.json()["error"]["message"]
    assert send(c, sid, cid="t-00000001").status_code == 200  # retry with same id succeeds


def test_rate_limit_enforced():
    app, _ = make(rate_limit_per_minute=2)
    c = TestClient(app)
    start(c)
    start(c)
    r = c.post("/api/sessions", json={"companion_id": "mira"}, headers=H)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_session_turn_limit():
    app, _ = make(max_user_turns_per_session=1)
    c = TestClient(app)
    sid = start(c)
    assert send(c, sid, cid="u-00000001").status_code == 200
    assert send(c, sid, cid="u-00000002").json()["error"]["code"] == "session_full"


def test_ended_session_rejects_messages():
    app, _ = make()
    c = TestClient(app)
    sid = start(c)
    assert c.delete(f"/api/sessions/{sid}", headers=H).status_code == 200
    assert send(c, sid).status_code == 404


def audio_post(client, sid, data, ctype="audio/webm", duration=3000):
    return client.post(f"/api/sessions/{sid}/transcribe", headers=H,
                       files={"audio": ("voice.webm", data, ctype)}, data={"duration_ms": str(duration)})


def test_transcription_checks():
    app, provider = make(max_audio_bytes=5000)
    c = TestClient(app)
    sid = start(c)
    assert audio_post(c, sid, b"x" * 2000, ctype="audio/ogg").status_code == 415
    assert audio_post(c, sid, b"x" * 10).json()["error"]["code"] == "audio_empty"
    assert audio_post(c, sid, b"x" * 6000).status_code == 413
    ok = audio_post(c, sid, b"x" * 2000, ctype="audio/webm;codecs=opus")
    assert ok.status_code == 200 and ok.json()["text"] == "hello there"
    provider.transcript = ""
    assert audio_post(c, sid, b"x" * 2000).json()["error"]["code"] == "no_speech"


def test_audio_allowance_enforced():
    app, _ = make(client_daily_audio_seconds=5)
    c = TestClient(app)
    sid = start(c)
    assert audio_post(c, sid, b"x" * 2000, duration=4000).status_code == 200
    assert audio_post(c, sid, b"x" * 2000, duration=4000).json()["error"]["code"] == "client_budget"


def test_speech_is_cached_per_reply():
    app, provider = make()
    c = TestClient(app)
    sid = start(c)
    reply_id = send(c, sid).json()["reply"]["id"]
    for _ in range(2):
        r = c.post(f"/api/sessions/{sid}/speech", json={"message_id": reply_id}, headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert provider.speak_calls == 1


def test_speech_only_for_replies_in_session():
    app, _ = make()
    c = TestClient(app)
    sid = start(c)
    user_id = send(c, sid).json()["user_message"]["id"]
    assert c.post(f"/api/sessions/{sid}/speech", json={"message_id": user_id}, headers=H).status_code == 404


def test_access_code_required_when_set():
    app, _ = make(access_code="open-sesame")
    c = TestClient(app)
    assert c.get("/api/config").json()["access_required"] is True
    r = c.post("/api/sessions", json={"companion_id": "mira"}, headers=H)
    assert r.status_code == 401 and r.json()["error"]["code"] == "access_required"
    assert c.post("/api/access", json={"code": "wrong"}, headers=H).status_code == 403
    assert c.post("/api/access", json={"code": "open-sesame"}, headers=H).status_code == 200
    assert c.get("/api/config").json()["access_required"] is False
    assert start(c)
    # A different browser still needs the code.
    assert TestClient(app).post("/api/sessions", json={"companion_id": "mira"}, headers=H).status_code == 401


def test_no_access_code_means_open():
    app, _ = make(access_code="")
    c = TestClient(app)
    assert c.get("/api/config").json()["access_required"] is False
    assert start(c)


def test_admin_report_locked():
    app, _ = make(admin_token="")
    assert TestClient(app).get("/api/admin/usage").status_code == 404
    app, _ = make(admin_token="t0ken")
    c = TestClient(app)
    assert c.get("/api/admin/usage").status_code == 404
    assert c.get("/api/admin/usage", headers={"X-Admin-Token": "t0ken"}).status_code == 200


def test_demo_mode_labels_replies_and_has_no_voice():
    settings = dataclasses.replace(load_settings(), openai_api_key="", force_demo=False, access_code="",
                                   rate_limit_per_minute=1000)
    c = TestClient(create_app(settings))
    assert c.get("/api/config").json()["mode"] == "demo"
    sid = start(c)
    reply = send(c, sid).json()["reply"]
    assert reply["demo"] is True
    r = c.post(f"/api/sessions/{sid}/speech", json={"message_id": reply["id"]}, headers=H)
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_demo"
