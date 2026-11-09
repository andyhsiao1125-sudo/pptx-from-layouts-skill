"""Gemini API adapter (native image models via ``client.models.generate_content``)."""

from __future__ import annotations

from imagegen.errors import ImageGenError, Kind
from imagegen.providers import GeneratedImage, ProviderResult


def make_client(api_key: str, timeout: float):
    from google import genai
    from google.genai import types
    # attempts=1 disables SDK retries; imagegen does its own bounded retry.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(
        timeout=int(timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1)))


def generate(request, api_key: str, timeout: float) -> ProviderResult:
    from google.genai import types

    client = make_client(api_key, timeout)
    image_cfg = {k: request.params[k] for k in ("aspect_ratio", "image_size") if request.params.get(k)}
    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(**image_cfg) if image_cfg else None,
    )
    resp = client.models.generate_content(model=request.model, contents=request.prompt, config=config)

    usage = None
    if getattr(resp, "usage_metadata", None) is not None:
        usage = resp.usage_metadata.model_dump(mode="json", exclude_none=True)

    images, texts, finish = [], [], []
    for cand in resp.candidates or []:
        if getattr(cand, "finish_reason", None) is not None:
            finish.append(str(getattr(cand.finish_reason, "value", cand.finish_reason)))
        for part in (cand.content.parts if cand.content and cand.content.parts else []):
            blob = getattr(part, "inline_data", None)
            if blob is not None and blob.data:
                images.append(GeneratedImage(blob.data, blob.mime_type or "image/png"))
            elif getattr(part, "text", None):
                texts.append(part.text)

    meta = {"model_version": getattr(resp, "model_version", None),
            "response_id": getattr(resp, "response_id", None),
            "finish_reason": finish or None}
    feedback = getattr(resp, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        meta["block_reason"] = str(getattr(feedback.block_reason, "value", feedback.block_reason))
    meta = {k: v for k, v in meta.items() if v is not None}

    if not images:
        detail = meta.get("block_reason") or ",".join(finish) or "no image part"
        raise ImageGenError(Kind.BLOCKED, f"Gemini 回應中沒有圖片（{detail}）", usage=usage)
    return ProviderResult(images=images, usage=usage, response_meta=meta, text=texts)


def classify(exc: Exception) -> ImageGenError:
    from google.genai import errors

    if isinstance(exc, ImageGenError):
        return exc
    if isinstance(exc, errors.APIError):
        status, code = exc.code, exc.status
        msg = f"Gemini HTTP {status} status={code}: {exc.message}"
        if status == 429:
            # RESOURCE_EXHAUSTED covers both rate limits and exhausted quota and the
            # API does not reliably distinguish them, so stop without retrying.
            kind = Kind.BILLING
        elif code == "FAILED_PRECONDITION":   # e.g. billing required / free tier unavailable
            kind = Kind.BILLING
        elif status in (401, 403):
            kind = Kind.AUTH
        elif status and status >= 500:
            kind = Kind.TRANSIENT
        elif status and 400 <= status < 500:
            kind = Kind.INVALID
        else:
            kind = Kind.OTHER
        return ImageGenError(kind, msg, status=status, code=code)
    if _is_transport_error(exc):
        return ImageGenError(Kind.TRANSIENT, f"連線錯誤：{type(exc).__name__}")
    return ImageGenError(Kind.OTHER, f"{type(exc).__name__}: {exc}")


def _is_transport_error(exc: Exception) -> bool:
    for modname in ("httpx2", "httpx"):
        try:
            mod = __import__(modname)
        except ImportError:
            continue
        if isinstance(exc, getattr(mod, "TransportError", ())):
            return True
    return isinstance(exc, (ConnectionError, TimeoutError))
