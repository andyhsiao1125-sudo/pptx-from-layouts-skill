"""Provider adapters. Each exposes ``generate(request, api_key, timeout)``
returning a ``ProviderResult`` and ``classify(exc)`` returning an
``ImageGenError`` with the right ``Kind``."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str


@dataclass
class ProviderResult:
    images: list[GeneratedImage]
    usage: dict | None                      # exactly what the API returned, or None
    response_meta: dict = field(default_factory=dict)
    text: list[str] = field(default_factory=list)


def get_provider(name: str):
    if name == "openai":
        from imagegen.providers import openai_provider as mod
    elif name == "gemini":
        from imagegen.providers import gemini_provider as mod
    else:  # pragma: no cover - guarded by config validation
        raise ValueError(name)
    return mod
