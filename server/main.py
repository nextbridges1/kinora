"""Kinora web server.

Run with:  python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
"""
import hashlib
import logging
import secrets
import time
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_provider import ProviderError, make_provider
from .companions import get_companion, public_list
from .config import ROOT, Settings, load_settings
from .policy import MAX_OUTPUT_TOKENS, build_instructions
from .sessions import Message, SessionNotFound, SessionStore
from .usage import LimitExceeded, UsageTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# Event log: types, timings and counts only. Never message text or audio.
events = logging.getLogger("kinora.events")

COOKIE = "kinora_client"
ALLOWED_AUDIO = {"audio/webm", "audio/mp4", "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/m4a", "audio/x-m4a"}
AUDIO_EXT = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/mp3": "mp3",
             "audio/wav": "wav", "audio/x-wav": "wav", "audio/m4a": "m4a", "audio/x-m4a": "m4a"}
PREVIEW_DIR = ROOT / ".cache" / "voice-previews"
ACCESS_COOKIE = "kinora_access"
OPEN_PATHS = {"/api/config", "/api/access", "/api/admin/usage"}


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class StartSession(BaseModel):
    companion_id: str


class SendMessage(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=64)
    text: str
    reply_length: str = "short"


class SpeechRequest(BaseModel):
    message_id: str


class AccessRequest(BaseModel):
    code: str = Field(max_length=200)


def create_app(settings: Settings = None, provider=None) -> FastAPI:
    settings = settings or load_settings()
    provider = provider or make_provider(settings)
    store = SessionStore(settings.session_idle_minutes, settings.max_active_sessions)
    usage = UsageTracker(settings)
    preview_cache: dict = {}

    app = FastAPI(title="Kinora", docs_url=None, redoc_url=None)
    app.state.settings, app.state.store, app.state.usage = settings, store, usage

    @app.middleware("http")
    async def client_identity(request: Request, call_next):
        """Anonymous per-browser ID (Stage A has no accounts). Sessions are tied to it."""
        client_id = request.cookies.get(COOKIE)
        new_cookie = not client_id or len(client_id) != 32
        if new_cookie:
            client_id = secrets.token_hex(16)
        request.state.client_id = client_id
        request.state.has_access = has_access(request)
        path = request.url.path

        if path.startswith("/api/") and request.method in ("POST", "DELETE"):
            # Custom header blocks cross-site form posts (browsers can't add it without CORS, which we don't allow).
            if request.headers.get("x-kinora") != "1":
                return error(403, "forbidden", "Request blocked.")

        if path.startswith("/api/") and path not in OPEN_PATHS and not request.state.has_access:
            return error(401, "access_required", "Enter the access code to use Kinora.")

        response = await call_next(request)
        if new_cookie:
            set_cookie(request, response, COOKIE, client_id)
        return response

    def access_token() -> str:
        return hashlib.sha256(f"kinora-access:{settings.access_code}".encode()).hexdigest()

    def has_access(request: Request) -> bool:
        if not settings.access_code:
            return True
        return secrets.compare_digest(request.cookies.get(ACCESS_COOKIE, ""), access_token())

    def set_cookie(request: Request, response, name: str, value: str):
        response.set_cookie(name, value, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30,
                            secure=request.url.scheme == "https")

    def guard(request: Request):
        usage.check_rate(request.state.client_id)

    @app.exception_handler(LimitExceeded)
    async def on_limit(_, exc: LimitExceeded):
        return error(429, exc.code, exc.message)

    @app.exception_handler(ProviderError)
    async def on_provider(_, exc: ProviderError):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(SessionNotFound)
    async def on_missing(_, exc):
        return error(404, "session_not_found", "This conversation has ended or expired. Start a new one.")

    # ---------- routes ----------

    @app.get("/api/config")
    def get_config(request: Request):
        return {
            "mode": "demo" if settings.demo_mode else "connected",
            "access_required": not request.state.has_access,
            "companions": public_list(),
            "limits": {
                "max_message_chars": settings.max_message_chars,
                "max_recording_seconds": settings.max_recording_seconds,
                "max_audio_bytes": settings.max_audio_bytes,
                "max_turns_per_session": settings.max_user_turns_per_session,
            },
            "usage": usage.summary(request.state.client_id),
        }

    @app.get("/api/usage")
    def get_usage(request: Request):
        return usage.summary(request.state.client_id)

    @app.post("/api/sessions")
    def start_session(body: StartSession, request: Request):
        guard(request)
        companion = get_companion(body.companion_id)
        if not companion or not companion.get("available"):
            return error(400, "companion_unavailable", "That companion isn't available yet.")
        try:
            session = store.create(request.state.client_id, companion["id"], companion["opening"])
        except OverflowError:
            return error(503, "busy", "Kinora has too many open conversations right now. Try again shortly.")
        events.info("session_start companion=%s", companion["id"])
        return {"session_id": session.id, "messages": [m.public() for m in session.messages]}

    @app.delete("/api/sessions/{session_id}")
    def end_session(session_id: str, request: Request):
        store.end(request.state.client_id, session_id)
        events.info("session_end")
        return {"ok": True}

    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, body: SendMessage, request: Request):
        client_id = request.state.client_id
        session = store.get(client_id, session_id)

        # Same request ID sent again (retry after a network drop): return the original reply.
        if body.client_message_id in session.completed:
            return session.completed[body.client_message_id]

        text = body.text.strip()
        if not text:
            return error(400, "empty_message", "Type or record a message first.")
        if len(text) > settings.max_message_chars:
            return error(400, "message_too_long", f"Messages can be up to {settings.max_message_chars} characters. Try splitting it up.")
        if session.user_turns >= settings.max_user_turns_per_session:
            return error(409, "session_full", "This conversation has reached its length limit. End it and start a fresh one.")
        if body.reply_length not in MAX_OUTPUT_TOKENS:
            body.reply_length = "short"

        if not store.try_lock(session):
            return error(409, "busy", "Still replying to your last message.")
        try:
            guard(request)
            usage.reserve(client_id, "replies", 1)
            companion = get_companion(session.companion_id)
            context = [{"role": m.role, "content": m.content} for m in session.messages]
            context.append({"role": "user", "content": text})
            context = context[-settings.context_messages:]
            started = time.time()
            try:
                reply_text, tokens = provider.reply(
                    build_instructions(companion, body.reply_length), context,
                    MAX_OUTPUT_TOKENS[body.reply_length])
            except ProviderError:
                usage.release(client_id, "replies", 1)
                raise
            usage.add_tokens(client_id, tokens["input_tokens"], tokens["output_tokens"])
            events.info("reply ms=%d in=%d out=%d demo=%s", (time.time() - started) * 1000,
                        tokens["input_tokens"], tokens["output_tokens"], provider.demo)

            # The session may have been ended while we waited. Don't revive it.
            if not store.exists(session.id):
                return error(404, "session_not_found", "This conversation was ended.")

            user_msg = Message(id=uuid.uuid4().hex, role="user", content=text)
            reply_msg = Message(id=uuid.uuid4().hex, role="assistant", content=reply_text, demo=provider.demo)
            session.messages += [user_msg, reply_msg]
            result = {"user_message": user_msg.public(), "reply": reply_msg.public(),
                      "usage": usage.summary(client_id)}
            session.completed[body.client_message_id] = result
            return result
        finally:
            store.unlock(session)

    @app.post("/api/sessions/{session_id}/transcribe")
    def transcribe(session_id: str, request: Request, audio: UploadFile = File(...),
                   duration_ms: int = Form(0)):
        client_id = request.state.client_id
        store.get(client_id, session_id)
        guard(request)
        content_type = (audio.content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_AUDIO:
            return error(415, "unsupported_audio", "This browser recorded audio in a format Kinora can't use. Try Chrome, Edge, Firefox or Safari, or type instead.")
        data = audio.file.read(settings.max_audio_bytes + 1)
        if len(data) > settings.max_audio_bytes:
            return error(413, "audio_too_large", "That recording is too large. Keep voice messages under a minute.")
        if len(data) < 1000:
            return error(400, "audio_empty", "The recording was empty. Hold the mic button a little longer, or type instead.")
        seconds = max(1, min(duration_ms / 1000, settings.max_recording_seconds))
        usage.reserve(client_id, "audio_seconds", seconds)
        try:
            text = provider.transcribe(f"voice.{AUDIO_EXT[content_type]}", data, content_type)
        except ProviderError:
            usage.release(client_id, "audio_seconds", seconds)
            raise
        finally:
            del data  # raw audio is never stored
        events.info("transcribe seconds=%.1f demo=%s", seconds, provider.demo)
        if not text:
            return error(422, "no_speech", "Kinora couldn't make out any words. Try again closer to the mic, or type instead.")
        return {"text": text, "demo": provider.demo}

    @app.post("/api/sessions/{session_id}/speech")
    def speech(session_id: str, body: SpeechRequest, request: Request):
        client_id = request.state.client_id
        session = store.get(client_id, session_id)
        message = session.find_message(body.message_id)
        if not message or message.role != "assistant":
            return error(404, "message_not_found", "That reply isn't in this conversation.")
        if message.id in session.audio:
            return Response(session.audio[message.id], media_type="audio/mpeg")
        if provider.demo:
            raise ProviderError("voice_demo", "AI voice isn't connected in demo mode.", 503)
        guard(request)
        chars = len(message.content)
        usage.reserve(client_id, "tts_chars", chars)
        voice = get_companion(session.companion_id)["voice"]
        try:
            audio_bytes = provider.speak(message.content, voice["id"], voice["instructions"])
        except ProviderError:
            usage.release(client_id, "tts_chars", chars)
            raise
        session.audio[message.id] = audio_bytes
        events.info("speech chars=%d", chars)
        return Response(audio_bytes, media_type="audio/mpeg")

    @app.get("/api/companions/{companion_id}/voice-preview")
    def voice_preview(companion_id: str, request: Request):
        companion = get_companion(companion_id)
        if not companion:
            return error(404, "not_found", "Unknown companion.")
        if provider.demo:
            raise ProviderError("voice_demo", "AI voice isn't connected in demo mode.", 503)
        voice = companion["voice"]
        key = hashlib.sha256(f"{settings.tts_model}|{voice['id']}|{voice['instructions']}|{voice['preview_text']}".encode()).hexdigest()[:16]
        path = PREVIEW_DIR / f"{companion_id}-{key}.mp3"
        if key not in preview_cache:
            if path.exists():
                preview_cache[key] = path.read_bytes()
            else:
                guard(request)
                usage.reserve(request.state.client_id, "tts_chars", len(voice["preview_text"]))
                audio_bytes = provider.speak(voice["preview_text"], voice["id"], voice["instructions"])
                PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(audio_bytes)
                preview_cache[key] = audio_bytes
        return Response(preview_cache[key], media_type="audio/mpeg")

    @app.post("/api/access")
    def grant_access(body: AccessRequest, request: Request):
        guard(request)  # rate limit slows down code guessing
        if not settings.access_code:
            return {"ok": True}
        if not secrets.compare_digest(body.code.strip(), settings.access_code):
            events.info("access_denied")
            return error(403, "wrong_code", "That access code isn't right. Check it with the person who shared Kinora.")
        response = JSONResponse({"ok": True})
        set_cookie(request, response, ACCESS_COOKIE, access_token())
        return response

    @app.get("/api/admin/usage")
    def admin_usage(request: Request):
        # Disabled unless KINORA_ADMIN_TOKEN is set; then send it in the X-Admin-Token header.
        token = request.headers.get("x-admin-token", "")
        if not settings.admin_token or not secrets.compare_digest(token, settings.admin_token):
            return error(404, "not_found", "Not found.")
        return usage.global_report()

    @app.get("/healthz")
    def health():
        return {"ok": True}

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


app = create_app()
