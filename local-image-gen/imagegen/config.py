"""Load imagegen.toml and turn CLI options into a validated request."""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from imagegen.errors import ImageGenError, Kind

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "imagegen.toml"
OPTIONS = ("quantize", "width", "height", "steps", "seed")


@dataclass
class Request:
    model: str            # key in [local.models]
    mflux_model: str      # value passed to --model
    prompt: str
    params: dict = field(default_factory=dict)
    seed_was_random: bool = False
    model_info: dict = field(default_factory=dict)


def load_config(path: Path | None = None) -> dict:
    path = Path(path) if path else Path(os.environ.get("IMAGEGEN_CONFIG", DEFAULT_CONFIG))
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ImageGenError(Kind.INVALID, f"找不到設定檔：{path}")


def build_request(cfg: dict, *, model: str | None, prompt: str, options: dict | None = None) -> Request:
    if not prompt or not prompt.strip():
        raise ImageGenError(Kind.INVALID, "prompt 不可為空")
    lcfg = cfg["local"]
    model = model or os.environ.get("IMAGEGEN_LOCAL_MODEL") or lcfg["default_model"]
    mcfg = lcfg.get("models", {}).get(model)
    if mcfg is None:
        raise ImageGenError(Kind.INVALID, f"模型 {model} 不在 imagegen.toml（可用：{', '.join(lcfg.get('models', {}))}）")

    given = {k: v for k, v in (options or {}).items() if v is not None and k in OPTIONS}
    params = {**mcfg.get("defaults", {}), **given}

    if params.get("quantize") not in mcfg["quantize_values"]:
        raise ImageGenError(Kind.INVALID, f"quantize={params.get('quantize')} 不支援（可用：{mcfg['quantize_values']}）")
    lo, hi = mcfg["steps_range"]
    if not lo <= int(params["steps"]) <= hi:
        raise ImageGenError(Kind.INVALID, f"steps 必須介於 {lo}–{hi}")
    smin, smax = mcfg["size_range"]
    for dim in ("width", "height"):
        v = int(params[dim])
        if not smin <= v <= smax or v % 16:
            raise ImageGenError(Kind.INVALID, f"{dim}={v}：須介於 {smin}–{smax} 且為 16 的倍數")

    seed_was_random = "seed" not in params
    if seed_was_random:
        params["seed"] = secrets.randbelow(2**31)   # explicit seed so the run is reproducible and recorded truthfully
    if int(params["seed"]) < 0:
        raise ImageGenError(Kind.INVALID, "seed 必須為非負整數")

    info = {k: mcfg[k] for k in ("upstream_repo", "license", "quantize_note") if k in mcfg}
    return Request(model=model, mflux_model=mcfg.get("mflux_model", model), prompt=prompt,
                   params=params, seed_was_random=seed_was_random, model_info=info)
