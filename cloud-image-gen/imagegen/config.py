"""Load imagegen.toml and turn CLI options into a validated request."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from imagegen.errors import ImageGenError, Kind

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "imagegen.toml"

# CLI option -> (provider, model-config key listing allowed values)
OPENAI_OPTIONS = {
    "size": "sizes",
    "quality": "qualities",
    "background": "backgrounds",
    "output_format": "output_formats",
    "moderation": "moderations",
    "output_compression": None,   # integer 0-100, jpeg/webp only
}
GEMINI_OPTIONS = {
    "aspect_ratio": "aspect_ratios",
    "image_size": "image_sizes",
}

_SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


@dataclass
class Request:
    provider: str
    model: str
    prompt: str
    n: int
    params: dict = field(default_factory=dict)
    pricing_note: str | None = None
    api_key_env: tuple[str, ...] = ()


def load_config(path: Path | None = None) -> dict:
    path = Path(path) if path else Path(os.environ.get("IMAGEGEN_CONFIG", DEFAULT_CONFIG))
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ImageGenError(Kind.INVALID, f"找不到設定檔：{path}")


def resolve_provider(cfg: dict, provider: str | None) -> str:
    provider = provider or os.environ.get("IMAGEGEN_DEFAULT_PROVIDER") or cfg["defaults"]["provider"]
    if provider not in cfg.get("providers", {}):
        raise ImageGenError(Kind.INVALID, f"不支援的 provider：{provider}（可用：{', '.join(cfg['providers'])}）")
    return provider


def resolve_model(cfg: dict, provider: str, model: str | None) -> str:
    pcfg = cfg["providers"][provider]
    return model or os.environ.get(pcfg.get("model_env", "")) or pcfg["default_model"]


def key_envs(cfg: dict, provider: str) -> tuple[str, ...]:
    pcfg = cfg["providers"][provider]
    names = [pcfg["api_key_env"]]
    if pcfg.get("api_key_env_fallback"):
        names.append(pcfg["api_key_env_fallback"])
    return tuple(names)


def read_api_key(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise ImageGenError(Kind.AUTH, f"未設定 API 金鑰環境變數：{' 或 '.join(names)}")


def _validate_size(value: str, mcfg: dict) -> None:
    if value in mcfg.get("sizes", []):
        return
    m = _SIZE_RE.match(value)
    if not (m and mcfg.get("custom_size")):
        raise ImageGenError(Kind.INVALID, f"size={value} 不在此模型可用值 {mcfg.get('sizes')}"
                            + ("" if mcfg.get("custom_size") else "，且此模型不支援自訂尺寸"))
    w, h = int(m.group(1)), int(m.group(2))
    if w % 16 or h % 16:
        raise ImageGenError(Kind.INVALID, f"自訂尺寸 {value}：寬高須為 16 的倍數")
    if not (1 / 3 <= w / h <= 3):
        raise ImageGenError(Kind.INVALID, f"自訂尺寸 {value}：長寬比須介於 1:3 與 3:1")
    if w * h > 3840 * 2160 or max(w, h) > 3840:
        raise ImageGenError(Kind.INVALID, f"自訂尺寸 {value}：超過官方上限 3840x2160")


def build_request(cfg: dict, *, provider: str | None, model: str | None, prompt: str,
                  n: int = 1, options: dict | None = None, allow_unlisted_model: bool = False) -> Request:
    if not prompt or not prompt.strip():
        raise ImageGenError(Kind.INVALID, "prompt 不可為空")
    provider = resolve_provider(cfg, provider)
    model = resolve_model(cfg, provider, model)
    pcfg = cfg["providers"][provider]
    options = {k: v for k, v in (options or {}).items() if v is not None}

    allowed = OPENAI_OPTIONS if provider == "openai" else GEMINI_OPTIONS
    foreign = sorted(set(options) - set(allowed))
    if foreign:
        flags = ", ".join("--" + k.replace("_", "-") for k in foreign)
        raise ImageGenError(Kind.INVALID, f"{provider} 不支援這些參數：{flags}")

    max_n = int(cfg["defaults"].get("max_images_per_call", 1))
    if n < 1 or n > max_n:
        raise ImageGenError(Kind.INVALID, f"--n 必須介於 1 與 {max_n}（設定檔 max_images_per_call）")
    if provider == "gemini" and n != 1:
        raise ImageGenError(Kind.INVALID, "gemini 每次呼叫只生成 1 張")

    mcfg = pcfg.get("models", {}).get(model)
    if mcfg is None:
        if not allow_unlisted_model:
            raise ImageGenError(Kind.INVALID,
                                f"模型 {model} 不在 imagegen.toml 的 {provider} 清單（可用：{', '.join(pcfg.get('models', {}))}）。"
                                "如確認官方已提供，請先加入設定檔，或加 --allow-unlisted-model（不做參數檢查）。")
        params = dict(options)
        pricing = None
    else:
        params = {**mcfg.get("defaults", {}), **options}
        for key, list_key in allowed.items():
            if key not in params:
                continue
            value = params[key]
            if key == "size":
                _validate_size(value, mcfg)
            elif key == "output_compression":
                if not 0 <= int(value) <= 100:
                    raise ImageGenError(Kind.INVALID, "output_compression 必須介於 0–100")
                if params.get("output_format", "png") == "png":
                    raise ImageGenError(Kind.INVALID, "output_compression 只適用 jpeg 或 webp")
            else:
                values = mcfg.get(list_key, [])
                if value not in values:
                    raise ImageGenError(Kind.INVALID, f"{key}={value} 不被 {model} 支援（可用：{values or '無'}）")
        if params.get("background") == "transparent" and params.get("output_format", "png") == "jpeg":
            raise ImageGenError(Kind.INVALID, "透明背景需搭配 png 或 webp")
        pricing = mcfg.get("pricing_note")

    return Request(provider=provider, model=model, prompt=prompt, n=n, params=params,
                   pricing_note=pricing, api_key_env=key_envs(cfg, provider))
