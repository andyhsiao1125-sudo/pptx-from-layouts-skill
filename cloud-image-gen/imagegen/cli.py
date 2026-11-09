"""imagegen CLI.

    imagegen generate --provider openai --prompt "..." [--output out.png] [model options]
    imagegen generate ... --dry-run      # validate + show request, no network, no key needed
    imagegen models                      # configured models, options, price notes
    imagegen check                       # which key env vars are set (never their values)

stdout carries one JSON object (machine-readable result); messages go to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from imagegen import __version__
from imagegen.config import PROJECT_ROOT, build_request, key_envs, load_config, read_api_key
from imagegen.errors import HINTS, ImageGenError, Kind, redact
from imagegen.providers import get_provider
from imagegen.record import image_paths, record_path, save_and_verify, write_json

_sleep = time.sleep  # swapped out in tests

NOT_PROVIDED = {
    "seed": "本工具未送出 seed，API 回應也不含 seed，故不記錄（OpenAI Images API 無 seed 參數）。",
    "actual_cost": "API 不回傳實際費用；請以 usage 對照官方價目，或至帳單後台核對。",
}


def _err(msg: str) -> None:
    print(redact(msg), file=sys.stderr)


def _out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _load_dotenv() -> None:
    """Load cloud-image-gen/.env into the environment (never overrides existing vars)."""
    env = PROJECT_ROOT / ".env"
    if env.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError:  # pragma: no cover
            return
        load_dotenv(env, override=False)


def _sdk_versions() -> dict:
    out = {}
    for pkg in ("openai", "google-genai"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-").lower()
    return s[:limit].strip("-") or "image"


def _default_output(cfg: dict, provider: str, prompt: str, ext: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / cfg["defaults"].get("output_dir", "output") / f"{stamp}_{provider}_{_slug(prompt)}{ext}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="imagegen", description="以 OpenAI / Gemini 官方 API 生成圖片並存檔。")
    p.add_argument("--config", type=Path, help="設定檔路徑（預設 cloud-image-gen/imagegen.toml）")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="生成圖片")
    g.add_argument("--provider", choices=["openai", "gemini"])
    g.add_argument("--model", help="模型 ID（須列在設定檔中）")
    src = g.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt")
    src.add_argument("--prompt-file", type=Path, help="從 UTF-8 文字檔讀取提示詞")
    g.add_argument("--output", "-o", type=Path, help="輸出圖片路徑；預設 cloud-image-gen/output/<時間>_<provider>_<摘要>.png")
    g.add_argument("--n", type=int, default=1, help="張數（預設 1；上限見設定檔）")
    g.add_argument("--dry-run", action="store_true", help="只驗證並顯示請求，不連網、不需金鑰、不計費")
    g.add_argument("--overwrite", action="store_true", help="允許覆寫既有檔案")
    g.add_argument("--allow-unlisted-model", action="store_true", help="允許設定檔未列出的模型（不做參數檢查）")
    g.add_argument("--max-retries", type=int, help="暫時性錯誤重試次數（預設見設定檔，最多 5）")
    oa = g.add_argument_group("OpenAI 選項")
    oa.add_argument("--size", help="例：1024x1024、1536x1024、auto；gpt-image-2 系列可自訂 WxH")
    oa.add_argument("--quality", help="low / medium / high / auto（2.5 系列另有 xhigh / max）")
    oa.add_argument("--background", help="auto / opaque / transparent")
    oa.add_argument("--output-format", dest="output_format", help="png / jpeg / webp")
    oa.add_argument("--output-compression", dest="output_compression", type=int, help="0–100，限 jpeg / webp")
    oa.add_argument("--moderation", help="auto / low")
    ge = g.add_argument_group("Gemini 選項")
    ge.add_argument("--aspect-ratio", dest="aspect_ratio", help="例：1:1、16:9、4:3")
    ge.add_argument("--image-size", dest="image_size", help="1K / 2K / 4K（僅部分模型）")

    sub.add_parser("models", help="列出設定檔中的模型、可用參數與價格備註")
    sub.add_parser("check", help="檢查金鑰環境變數是否已設定（不顯示內容）")
    return p


def cmd_models(cfg: dict) -> int:
    out = {"default_provider": cfg["defaults"]["provider"], "providers": {}}
    for name, pcfg in cfg["providers"].items():
        out["providers"][name] = {
            "default_model": pcfg["default_model"],
            "model_env": pcfg.get("model_env"),
            "models": {m: {k: v for k, v in mc.items()} for m, mc in pcfg.get("models", {}).items()},
        }
    _out(out)
    return 0


def cmd_check(cfg: dict) -> int:
    import os
    status = {}
    for name in cfg["providers"]:
        status[name] = {env: bool(os.environ.get(env, "").strip()) for env in key_envs(cfg, name)}
    _out({"api_keys_set": status, "config": str(PROJECT_ROOT / "imagegen.toml"), "sdk_versions": _sdk_versions()})
    return 0


def cmd_generate(cfg: dict, args) -> int:
    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8").strip()
    options = {k: getattr(args, k) for k in
               ("size", "quality", "background", "output_format", "output_compression", "moderation",
                "aspect_ratio", "image_size")}
    req = build_request(cfg, provider=args.provider, model=args.model, prompt=prompt, n=args.n,
                        options=options, allow_unlisted_model=args.allow_unlisted_model)

    expected_ext = {"jpeg": ".jpg", "webp": ".webp"}.get(req.params.get("output_format"), ".png")
    base = args.output or _default_output(cfg, req.provider, prompt, expected_ext)
    if not base.is_absolute():
        base = Path.cwd() / base
    if not base.suffix:
        base = base.with_suffix(expected_ext)
    planned, _ = image_paths(base, ["image/" + expected_ext.lstrip(".").replace("jpg", "jpeg")] * req.n)
    rec_path = record_path(base)
    if not args.overwrite:
        clash = [str(p) for p in [*planned, rec_path] if p.exists()]
        if clash:
            raise ImageGenError(Kind.INVALID, f"檔案已存在：{', '.join(clash)}（加 --overwrite 可覆寫）")

    max_retries = cfg["defaults"].get("max_retries", 2) if args.max_retries is None else args.max_retries
    max_retries = max(0, min(int(max_retries), 5))

    plan = {"provider": req.provider, "model": req.model, "prompt": prompt, "n": req.n,
            "params": req.params, "output": [str(p) for p in planned], "record": str(rec_path),
            "max_retries": max_retries, "pricing_note": req.pricing_note,
            "api_key_env": list(req.api_key_env)}
    if args.dry_run:
        _out({"status": "dry_run", "request": plan})
        _err("dry-run：未發出任何 API 請求。")
        return 0

    api_key = read_api_key(req.api_key_env)
    provider = get_provider(req.provider)
    timeout = float(cfg["defaults"].get("timeout_seconds", 300))

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    attempt, result, error = 0, None, None
    while True:
        attempt += 1
        try:
            result = provider.generate(req, api_key, timeout)
            break
        except Exception as exc:  # noqa: BLE001 - classified below
            error = provider.classify(exc)
            if error.kind is Kind.TRANSIENT and attempt <= max_retries:
                delay = error.retry_after or 2 ** attempt
                _err(f"[重試 {attempt}/{max_retries}] {error.message}；{delay:.0f} 秒後再試")
                _sleep(min(delay, 60))
                continue
            break
    duration = round(time.monotonic() - t0, 3)
    finished = datetime.now(timezone.utc)

    record = {
        "tool": {"name": "imagegen", "version": __version__, "sdk_versions": _sdk_versions()},
        "provider": req.provider,
        "model": req.model,
        "prompt": prompt,
        "request_params": {"n": req.n, **req.params},
        "started_at_utc": started.isoformat(timespec="seconds"),
        "finished_at_utc": finished.isoformat(timespec="seconds"),
        "duration_seconds": duration,
        "attempts": attempt,
    }

    if result is None:
        record.update(status="error", error={"kind": error.kind.value, "status": error.status,
                                             "code": error.code, "message": redact(error.message)},
                      usage=error.usage, fields_not_provided_by_api=NOT_PROVIDED)
        err_path = base.with_name(base.stem + ".error.json")
        write_json(err_path, record)
        _out({"status": "error", "kind": error.kind.value, "exit_code": error.exit_code,
              "message": redact(error.message), "hint": HINTS[error.kind], "error_record": str(err_path)})
        _err(f"失敗（{error.kind.value}）：{error.message}\n{HINTS[error.kind]}")
        return error.exit_code

    paths, notes = image_paths(base, [img.mime_type for img in result.images])
    saved = [save_and_verify(p, img.data) for p, img in zip(paths, result.images)]
    record.update(
        status="success",
        images=[{**s, "mime_type": img.mime_type} for s, img in zip(saved, result.images)],
        usage=result.usage,
        usage_note=None if result.usage else "API 本次未回傳用量資訊。",
        response_meta=result.response_meta,
        model_text=result.text or None,
        notes=notes or None,
        fields_not_provided_by_api=NOT_PROVIDED,
    )
    record = {k: v for k, v in record.items() if v is not None}
    write_json(rec_path, record)
    _out({"status": "ok", "images": [s["path"] for s in saved], "record": str(rec_path),
          "model": req.model, "duration_seconds": duration, "usage": result.usage})
    for n in notes:
        _err(n)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _load_dotenv()
    try:
        cfg = load_config(args.config)
        if args.cmd == "models":
            return cmd_models(cfg)
        if args.cmd == "check":
            return cmd_check(cfg)
        return cmd_generate(cfg, args)
    except ImageGenError as e:
        _out({"status": "error", "kind": e.kind.value, "exit_code": e.exit_code,
              "message": redact(e.message), "hint": HINTS[e.kind]})
        _err(f"錯誤（{e.kind.value}）：{e.message}")
        return e.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
