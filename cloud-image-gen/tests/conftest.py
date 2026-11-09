"""Shared fixtures. No test in this suite makes a network request: every
provider client is replaced by a fake, and any attempt to build a real client
fails the test."""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

import pytest

from imagegen import cli
from imagegen.providers import gemini_provider, openai_provider

KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "IMAGEGEN_DEFAULT_PROVIDER", "IMAGEGEN_OPENAI_MODEL", "IMAGEGEN_GEMINI_MODEL", "IMAGEGEN_CONFIG")


def png_bytes(w=8, h=6, fmt="PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)
    sleeps = []
    monkeypatch.setattr(cli, "_sleep", sleeps.append)

    def no_network(*a, **k):
        raise AssertionError("real client construction attempted")
    monkeypatch.setattr(openai_provider, "make_client", no_network)
    monkeypatch.setattr(gemini_provider, "make_client", no_network)
    monkeypatch.chdir(tmp_path)
    return SimpleNamespace(tmp=tmp_path, sleeps=sleeps)


def run(capsys, *argv):
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    payload = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else None
    return code, payload, cap


# ---------------------------------------------------------------- fake OpenAI
class FakeOpenAI:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.images = SimpleNamespace(generate=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        return out


def openai_ok(data: bytes | None = None, usage: dict | None = None):
    from openai.types import ImagesResponse
    payload = {"created": 1762650000, "output_format": "png", "quality": "low", "size": "1024x1024",
               "data": [{"b64_json": base64.b64encode(data or png_bytes()).decode()}]}
    if usage is not None:
        payload["usage"] = usage
    return ImagesResponse.model_validate(payload)


def openai_error(status: int, code: str | None, etype: str | None = None, message="err", headers=None):
    import httpx2
    import openai
    req = httpx2.Request("POST", "https://api.openai.com/v1/images/generations")
    resp = httpx2.Response(status, request=req, headers=headers or {})
    cls = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
           429: openai.RateLimitError, 500: openai.InternalServerError}.get(status, openai.APIStatusError)
    return cls(message, response=resp, body={"code": code, "type": etype, "message": message})


@pytest.fixture
def fake_openai(monkeypatch):
    def install(*outcomes):
        fake = FakeOpenAI(outcomes)
        monkeypatch.setattr(openai_provider, "make_client", lambda key, timeout: fake)
        return fake
    return install


# ---------------------------------------------------------------- fake Gemini
class FakeGemini:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        return out


def gemini_ok(data: bytes | None = None, mime="image/png", with_image=True):
    from google.genai import types
    parts = [types.Part(text="Here is your image.")]
    if with_image:
        parts.append(types.Part(inline_data=types.Blob(data=data or png_bytes(), mime_type=mime)))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=12, candidates_token_count=1290, total_token_count=1302),
        model_version="gemini-2.5-flash-image",
        response_id="resp-123",
    )


def gemini_error(code: int, status: str, message="err"):
    from google.genai import errors
    body = {"error": {"code": code, "status": status, "message": message}}
    return (errors.ClientError if code < 500 else errors.ServerError)(code, body)


@pytest.fixture
def fake_gemini(monkeypatch):
    def install(*outcomes):
        fake = FakeGemini(outcomes)
        monkeypatch.setattr(gemini_provider, "make_client", lambda key, timeout: fake)
        return fake
    return install
