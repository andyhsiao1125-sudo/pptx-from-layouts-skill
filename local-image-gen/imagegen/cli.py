"""imagegen: local text-to-image via MFLUX.

    imagegen generate --prompt "..." [-o out.png] [--width --height --steps --seed --quantize]
    imagegen generate ... --dry-run     # validate + show the command; runs nothing
    imagegen check                      # find mflux-generate, version, verify its --help flags
    imagegen models                     # configured models and allowed values

stdout carries one JSON object (machine-readable); messages go to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from imagegen import __version__
from imagegen.config import PROJECT_ROOT, build_request, load_config
from imagegen.errors import HINTS, ImageGenError, Kind
from imagegen.providers import local_mflux as mflux
from imagegen.record import record_path, save_and_verify, write_json


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-").lower()
    return s[:limit].strip("-") or "image"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="imagegen", description="以本機 MFLUX 生成圖片並記錄。")
    p.add_argument("--config", type=Path, help="設定檔路徑（預設 local-image-gen/imagegen.toml）")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="生成 1 張圖片")
    src = g.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt")
    src.add_argument("--prompt-file", type=Path, help="從 UTF-8 文字檔讀取提示詞")
    g.add_argument("--output", "-o", type=Path, help="輸出 PNG 路徑；預設 local-image-gen/output/<時間>_<摘要>.png")
    g.add_argument("--model", help="imagegen.toml 中的模型鍵（預設 schnell）")
    g.add_argument("--width", type=int)
    g.add_argument("--height", type=int)
    g.add_argument("--steps", type=int)
    g.add_argument("--seed", type=int, help="未指定時隨機產生並記錄")
    g.add_argument("--quantize", type=int, help="量化位數（預設 4）")
    g.add_argument("--dry-run", action="store_true", help="只驗證並顯示將執行的指令，不執行")
    g.add_argument("--overwrite", action="store_true", help="允許覆寫既有檔案")
    g.add_argument("--allow-download", action="store_true",
                   help="本次允許 MFLUX 下載模型（預設離線，絕不自動下載；須先經使用者同意）")

    sub.add_parser("check", help="檢查 mflux-generate 是否可用、版本與參數")
    sub.add_parser("models", help="列出設定檔中的模型與可用值")
    return p


def cmd_models(cfg: dict) -> int:
    _out({"default_model": cfg["local"]["default_model"], "models": cfg["local"].get("models", {})})
    return 0


def cmd_check(cfg: dict) -> int:
    cmd = mflux.find_command(cfg["local"])
    result = {"platform": mflux.platform_info(), "mflux_generate": cmd,
              "offline_by_default": cfg["local"].get("offline_by_default", True)}
    if cmd is None:
        result.update(status="error", kind=Kind.SETUP.value,
                      hint="找不到 mflux-generate。安裝方式見 README「安裝 MFLUX」。")
        _out(result)
        return ImageGenError(Kind.SETUP, "").exit_code
    missing = mflux.missing_flags(mflux.help_text(cmd))
    result.update(mflux_version=mflux.mflux_version(cmd), required_flags=list(mflux.FLAG_FOR.values()),
                  missing_flags=missing, status="ok" if not missing else "error")
    _out(result)
    return 0 if not missing else ImageGenError(Kind.SETUP, "").exit_code


def cmd_generate(cfg: dict, args) -> int:
    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8").strip()
    req = build_request(cfg, model=args.model, prompt=prompt,
                        options={k: getattr(args, k) for k in ("quantize", "width", "height", "steps", "seed")})

    out = args.output or (PROJECT_ROOT / cfg["defaults"].get("output_dir", "output")
                          / f"{datetime.now():%Y%m%d-%H%M%S}_{_slug(prompt)}.png")
    out = (out if out.is_absolute() else Path.cwd() / out).with_suffix(".png")
    rec = record_path(out)
    if not args.overwrite:
        clash = [str(p) for p in (out, rec) if p.exists()]
        if clash:
            raise ImageGenError(Kind.INVALID, f"檔案已存在：{', '.join(clash)}（加 --overwrite 可覆寫）")

    lcfg = cfg["local"]
    offline = lcfg.get("offline_by_default", True) and not args.allow_download
    cmd = mflux.find_command(lcfg)

    if args.dry_run:
        argv = mflux.build_argv(cmd or lcfg.get("command", "mflux-generate"), req, Path("<tmp>/image.png"))
        _out({"status": "dry_run", "output": str(out), "record": str(rec), "model": req.model,
              "params": req.params, "seed_was_random": req.seed_was_random, "offline": offline,
              "mflux_generate_found": cmd, "command": argv, "model_info": req.model_info})
        _err("dry-run：未執行 mflux-generate。")
        return 0

    if cmd is None:
        raise ImageGenError(Kind.SETUP, "找不到 mflux-generate（PATH 與 ~/.local/bin 皆無）")
    missing = mflux.missing_flags(mflux.help_text(cmd))
    if missing:
        raise ImageGenError(Kind.SETUP, f"目前版本的 mflux-generate --help 沒有這些參數：{', '.join(missing)}")
    version = mflux.mflux_version(cmd)

    record = {
        "tool": {"name": "imagegen", "version": __version__},
        "backend": "mflux (local)",
        "mflux_version": version,
        "model": req.model,
        "mflux_model_arg": req.mflux_model,
        "model_source": req.model_info,
        "quantize": req.params["quantize"],
        "prompt": prompt,
        "seed": req.params["seed"],
        "seed_was_random": req.seed_was_random,
        "steps": req.params["steps"],
        "width": req.params["width"],
        "height": req.params["height"],
        "offline_mode": offline,
        "platform": mflux.platform_info(),
    }

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        data, run_meta = mflux.generate(req, cmd, offline=offline,
                                        timeout=float(cfg["defaults"].get("timeout_seconds", 1800)))
        error = None
    except ImageGenError as e:
        error, data, run_meta = e, None, {}
    duration = round(time.monotonic() - t0, 3)
    record.update(started_at_utc=started.isoformat(timespec="seconds"),
                  finished_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  duration_seconds=duration,
                  duration_note="含模型載入時間（wall-clock）",
                  peak_memory="未量測")

    if error is None:
        try:
            image = save_and_verify(out, data)
        except Exception as e:  # noqa: BLE001 - invalid image bytes
            error = ImageGenError(Kind.NO_IMAGE, f"輸出檔無法以影像開啟：{type(e).__name__}")
    if error is not None:
        record.update(status="error", error={"kind": error.kind.value, "message": error.message, **error.detail})
        err_path = out.with_name(out.stem + ".error.json")
        write_json(err_path, record)
        _out({"status": "error", "kind": error.kind.value, "exit_code": error.exit_code,
              "message": error.message, "hint": HINTS[error.kind], "error_record": str(err_path)})
        _err(f"失敗（{error.kind.value}）：{error.message}\n{HINTS[error.kind]}")
        return error.exit_code

    record.update(status="success", image=image, command=run_meta.get("argv"))
    write_json(rec, record)
    _out({"status": "ok", "image": image["path"], "record": str(rec), "seed": req.params["seed"],
          "duration_seconds": duration, "width": image["width"], "height": image["height"]})
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.cmd == "models":
            return cmd_models(cfg)
        if args.cmd == "check":
            return cmd_check(cfg)
        return cmd_generate(cfg, args)
    except ImageGenError as e:
        _out({"status": "error", "kind": e.kind.value, "exit_code": e.exit_code,
              "message": e.message, "hint": HINTS[e.kind]})
        _err(f"錯誤（{e.kind.value}）：{e.message}")
        return e.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
