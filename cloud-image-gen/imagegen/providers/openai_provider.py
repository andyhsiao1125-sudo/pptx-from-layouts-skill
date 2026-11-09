"""OpenAI Images API adapter (``client.images.generate``)."""

from __future__ import annotations

import base64

from imagegen.errors import ImageGenError, Kind
from imagegen.providers import GeneratedImage, ProviderResult

# error.code values that mean "money / quota", per developers.openai.com error-codes guide.
BILLING_CODES = {
    "insufficient_quota",
    "billing_hard_limit_reached",
    "billing_not_active",
    "project_spend_limit_exceeded",
    "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}
RATE_LIMIT_CODES = {"rate_limit_exceeded", "slow_down"}
BLOCKED_CODES = {"moderation_blocked", "content_policy_violation"}

MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}

# Factory is a module attribute so tests can swap in a fake client.
def make_client(api_key: str, timeout: float):
    from openai import OpenAI
    # SDK auto-retry disabled: imagegen does its own bounded, billing-aware retry.
    return OpenAI(api_key=api_key, max_retries=0, timeout=timeout)


def generate(request, api_key: str, timeout: float) -> ProviderResult:
    client = make_client(api_key, timeout)
    kwargs = {"model": request.model, "prompt": request.prompt, "n": request.n, **request.params}
    resp = client.images.generate(**kwargs)

    fmt = getattr(resp, "output_format", None) or request.params.get("output_format", "png")
    images = []
    for item in resp.data or []:
        b64 = getattr(item, "b64_json", None)
        if b64:
            images.append(GeneratedImage(base64.b64decode(b64), MIME.get(fmt, "image/png")))
    if not images:
        raise ImageGenError(Kind.BLOCKED, "OpenAI 回應中沒有圖片資料", usage=_usage(resp))

    meta = {k: getattr(resp, k, None) for k in ("created", "size", "quality", "output_format", "background")}
    revised = [getattr(i, "revised_prompt", None) for i in resp.data or []]
    if any(revised):
        meta["revised_prompt"] = revised
    return ProviderResult(images=images, usage=_usage(resp),
                          response_meta={k: v for k, v in meta.items() if v is not None})


def _usage(resp) -> dict | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    return usage.model_dump(mode="json", exclude_none=True) if hasattr(usage, "model_dump") else dict(usage)


def classify(exc: Exception) -> ImageGenError:
    import openai

    if isinstance(exc, ImageGenError):
        return exc
    if isinstance(exc, openai.APIConnectionError):  # includes APITimeoutError
        return ImageGenError(Kind.TRANSIENT, f"連線錯誤：{type(exc).__name__}")
    if isinstance(exc, openai.APIStatusError):
        status, code, etype = exc.status_code, exc.code, getattr(exc, "type", None)
        msg = f"OpenAI HTTP {status} code={code} type={etype}: {exc.message}"
        if code in BILLING_CODES or etype == "insufficient_quota" or status == 402:
            kind = Kind.BILLING
        elif status == 429:
            # Only explicit rate-limit codes are retried; an unrecognised 429 is
            # treated as a billing/quota stop (conservative by design).
            kind = Kind.TRANSIENT if code in RATE_LIMIT_CODES else Kind.BILLING
        elif status in (401, 403):
            kind = Kind.AUTH
        elif code in BLOCKED_CODES:
            kind = Kind.BLOCKED
        elif status >= 500:
            kind = Kind.TRANSIENT
        elif 400 <= status < 500:
            kind = Kind.INVALID
        else:
            kind = Kind.OTHER
        err = ImageGenError(kind, msg, status=status, code=code)
        try:
            ra = exc.response.headers.get("retry-after")
            err.retry_after = float(ra) if ra else None
        except (AttributeError, ValueError):
            pass
        return err
    return ImageGenError(Kind.OTHER, f"{type(exc).__name__}: {exc}")
