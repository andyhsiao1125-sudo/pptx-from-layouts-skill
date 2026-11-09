"""Local MFLUX backend: runs the `mflux-generate` CLI as a subprocess.

Safety properties:
- Every flag we pass must appear in the installed `mflux-generate --help`
  output, otherwise we stop (no guessing renamed flags).
- By default the child runs with HF_HUB_OFFLINE=1, so it can only use models
  already in the local cache and never downloads weights on its own.
- No network calls are made by this module itself.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from imagegen.errors import ImageGenError, Kind

FLAG_FOR = {"model": "--model", "prompt": "--prompt", "output": "--output", "quantize": "--quantize",
            "width": "--width", "height": "--height", "steps": "--steps", "seed": "--seed"}

# stderr fragments that indicate "offline and not cached" (huggingface_hub wording)
_NOT_CACHED = re.compile(r"HF_HUB_OFFLINE|LocalEntryNotFound|offline mode|not (?:found )?in (?:the )?(?:local |disk )?cache",
                         re.IGNORECASE)
_VERSION = re.compile(r"\bmflux\b[^\n\d]*v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)


# Indirection points so tests can run without MFLUX installed.
def run_cmd(argv, *, env=None, timeout=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)


def which(name: str) -> str | None:
    return shutil.which(name)


def find_command(lcfg: dict) -> str | None:
    cmd = lcfg.get("command", "mflux-generate")
    found = which(cmd)
    if found:
        return found
    for d in lcfg.get("search_paths", []):
        cand = Path(os.path.expanduser(d)) / cmd
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def help_text(cmd: str) -> str:
    try:
        r = run_cmd([cmd, "--help"], timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ImageGenError(Kind.SETUP, f"無法執行 {cmd} --help：{type(e).__name__}")
    return (r.stdout or "") + (r.stderr or "")


def missing_flags(help_out: str) -> list[str]:
    return [f for f in FLAG_FOR.values() if not re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", help_out)]


def mflux_version(cmd: str) -> str | None:
    """Best-effort; returns None rather than guessing."""
    for argv in ([cmd, "--version"], ["uv", "tool", "list"]):
        try:
            r = run_cmd(argv, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        out = (r.stdout or "") + (r.stderr or "")
        if argv[-1] == "--version" and r.returncode == 0:
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out)
            if m:
                return m.group(1)
        m = _VERSION.search(out)
        if m:
            return m.group(1)
    return None


def platform_info() -> dict:
    info = {"system": platform.system(), "machine": platform.machine()}
    if info["system"] == "Darwin":
        info["macos"] = platform.mac_ver()[0]
    return info


def build_argv(cmd: str, req, output: Path) -> list[str]:
    p = req.params
    return [cmd, FLAG_FOR["model"], req.mflux_model, FLAG_FOR["prompt"], req.prompt,
            FLAG_FOR["quantize"], str(p["quantize"]), FLAG_FOR["width"], str(p["width"]),
            FLAG_FOR["height"], str(p["height"]), FLAG_FOR["steps"], str(p["steps"]),
            FLAG_FOR["seed"], str(p["seed"]), FLAG_FOR["output"], str(output)]


def child_env(offline: bool) -> dict:
    env = dict(os.environ)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    else:
        env.pop("HF_HUB_OFFLINE", None)
    return env


def generate(req, cmd: str, *, offline: bool, timeout: float) -> tuple[bytes, dict]:
    """Run mflux-generate into a temp dir; return (png bytes, run metadata)."""
    with tempfile.TemporaryDirectory(prefix="imagegen-") as tmp:
        target = Path(tmp) / "image.png"
        argv = build_argv(cmd, req, target)
        try:
            r = run_cmd(argv, env=child_env(offline), timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ImageGenError(Kind.TIMEOUT, f"超過 {timeout:.0f} 秒未完成")
        except OSError as e:
            raise ImageGenError(Kind.SETUP, f"無法執行 mflux-generate：{e}")
        tail = "\n".join(((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-40:])
        if r.returncode != 0:
            kind = Kind.MODEL_NOT_CACHED if offline and _NOT_CACHED.search(tail) else Kind.RUNTIME
            raise ImageGenError(kind, f"mflux-generate 結束碼 {r.returncode}",
                                detail={"returncode": r.returncode, "stderr_tail": tail})
        produced = target if target.is_file() else next(iter(sorted(Path(tmp).glob("*.png"))), None)
        if produced is None:
            raise ImageGenError(Kind.NO_IMAGE, "mflux-generate 未產生 PNG", detail={"stderr_tail": tail})
        return produced.read_bytes(), {"argv": [a if a != str(target) else "<tmp>/image.png" for a in argv]}
