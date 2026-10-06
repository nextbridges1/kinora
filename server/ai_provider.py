"""Speech and conversation providers.

OpenAIProvider makes real API calls. DemoProvider returns fixed, clearly
labelled text so the interface can be reviewed without an API key. The rest of
the app only talks to the shared interface (reply / transcribe / speak), so a
Realtime provider can be added later without touching the UI or session code.
"""
import itertools
import logging

from .config import Settings

log = logging.getLogger("kinora.provider")


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class OpenAIProvider:
    demo = False

    def __init__(self, settings: Settings):
        from openai import OpenAI

        self.s = settings
        # max_retries=0: an automatic retry after a timeout could be billed twice.
        # The browser offers a manual retry that reuses the same request ID instead.
        self.client = OpenAI(api_key=settings.openai_api_key,
                             timeout=settings.request_timeout_s, max_retries=0)

    def reply(self, instructions: str, messages: list, max_output_tokens: int):
        kwargs = dict(
            model=self.s.chat_model,
            instructions=instructions,
            input=[{"role": m["role"], "content": m["content"]} for m in messages],
            max_output_tokens=max_output_tokens,
            store=False,  # don't keep conversations on OpenAI's side for later retrieval
        )
        if self.s.chat_reasoning_effort:
            kwargs["reasoning"] = {"effort": self.s.chat_reasoning_effort}
        response = self._call(lambda: self.client.responses.create(**kwargs))
        text = (response.output_text or "").strip()
        if not text:
            raise ProviderError("empty_reply", "The reply came back empty. Try sending again.")
        usage = getattr(response, "usage", None)
        return text, {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }

    def transcribe(self, filename: str, data: bytes, content_type: str) -> str:
        result = self._call(lambda: self.client.audio.transcriptions.create(
            model=self.s.transcribe_model, file=(filename, data, content_type)))
        return (result.text or "").strip()

    def speak(self, text: str, voice: str, voice_instructions: str) -> bytes:
        def call():
            with self.client.audio.speech.with_streaming_response.create(
                model=self.s.tts_model, voice=voice, input=text,
                instructions=voice_instructions, response_format="mp3",
            ) as response:
                return response.read()
        return self._call(call)

    @staticmethod
    def _call(fn):
        import openai

        try:
            return fn()
        except openai.APITimeoutError:
            raise ProviderError("timeout", "The AI service took too long to answer. Try again.", 504)
        except openai.APIConnectionError:
            raise ProviderError("network", "Kinora couldn't reach the AI service. Check your internet connection and try again.", 502)
        except openai.AuthenticationError:
            raise ProviderError("auth", "The OpenAI API key was rejected. Check OPENAI_API_KEY in your .env file.", 502)
        except openai.PermissionDeniedError:
            raise ProviderError("permission", "This API key doesn't have access to the configured model. Check the model names in .env.", 502)
        except openai.RateLimitError as e:
            if "insufficient_quota" in str(e):
                raise ProviderError("quota", "The OpenAI account is out of credit. Add billing credit on the OpenAI platform.", 502)
            raise ProviderError("provider_busy", "The AI service is busy right now. Wait a moment, then try again.", 503)
        except openai.BadRequestError as e:
            log.warning("provider bad request: %s", type(e).__name__)
            raise ProviderError("bad_request", "The AI service couldn't process that request. If it was audio, try recording again.", 400)
        except openai.APIStatusError as e:
            log.warning("provider status %s", e.status_code)
            raise ProviderError("provider_error", "The AI service had a problem. Try again in a moment.", 502)


class DemoProvider:
    """Fixed responses for reviewing the interface. Not AI."""

    demo = True
    _replies = itertools.cycle([
        "This is a demo reply, not a real AI response. In connected mode, your companion would respond to the specific things you just wrote.",
        "Demo mode is on, so this text is fixed. Once an OpenAI API key is added, your companion will listen and reply to what you actually said.",
        "Still a demo reply. The buttons, recording, transcript and limits all work. Only the words here are placeholders.",
    ])

    def reply(self, instructions, messages, max_output_tokens):
        return next(self._replies), {"input_tokens": 0, "output_tokens": 0}

    def transcribe(self, filename, data, content_type):
        return "(Demo transcription. Speech-to-text isn't connected yet, so edit this text before sending.)"

    def speak(self, text, voice, voice_instructions):
        raise ProviderError("voice_demo", "AI voice isn't connected in demo mode.", 503)


def make_provider(settings: Settings):
    return DemoProvider() if settings.demo_mode else OpenAIProvider(settings)
