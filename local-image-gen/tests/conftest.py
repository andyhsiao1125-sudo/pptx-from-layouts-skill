"""Shared fixtures. MFLUX is never actually executed: `run_cmd` and `which`
are replaced by a fake that imitates mflux-generate."""

from __future__ import annotations

import io
import json
import subprocess
from types import SimpleNamespace

import pytest

from imagegen import cli
from imagegen.providers import local_mflux

FULL_HELP = """usage: mflux-generate [-h] --prompt PROMPT [--model MODEL] [--quantize {3,4,5,6,8}]
  --width WIDTH --height HEIGHT --steps STEPS --seed SEED --output OUTPUT --low-ram --make-conf"""


def png_bytes(w=512, h=512) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (220, 220, 220)).save(buf, "PNG")
    return buf.getvalue()


class FakeMflux:
    """mode: ok | fail | not_cached | no_image | garbage | timeout"""

    def __init__(self):
        self.mode = "ok"
        self.help = FULL_HELP
        self.version_out = "mflux 0.23.0"
        self.calls = []

    def __call__(self, argv, *, env=None, timeout=None):
        self.calls.append(SimpleNamespace(argv=list(argv), env=env, timeout=timeout))
        if argv[-1] == "--help":
            return subprocess.CompletedProcess(argv, 0, self.help, "")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, self.version_out, "")
        if argv[:3] == ["uv", "tool", "list"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        # generation call
        if self.mode == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout)
        out = argv[argv.index("--output") + 1]
        if self.mode == "ok":
            w = int(argv[argv.index("--width") + 1]); h = int(argv[argv.index("--height") + 1])
            open(out, "wb").write(png_bytes(w, h))
            return subprocess.CompletedProcess(argv, 0, "done", "")
        if self.mode == "garbage":
            open(out, "wb").write(b"not an image")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if self.mode == "no_image":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if self.mode == "not_cached":
            return subprocess.CompletedProcess(argv, 1, "", "huggingface_hub.errors.LocalEntryNotFoundError: "
                                               "Cannot find the requested files in the disk cache and HF_HUB_OFFLINE is set")
        return subprocess.CompletedProcess(argv, 1, "", "RuntimeError: [metal::malloc] out of memory")

    @property
    def gen_calls(self):
        return [c for c in self.calls if "--prompt" in c.argv]


@pytest.fixture
def mflux(monkeypatch, tmp_path):
    fake = FakeMflux()
    monkeypatch.setattr(local_mflux, "run_cmd", fake)
    monkeypatch.setattr(local_mflux, "which", lambda name: "/fake/bin/mflux-generate")
    monkeypatch.delenv("IMAGEGEN_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("IMAGEGEN_CONFIG", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.chdir(tmp_path)
    return fake


def run(capsys, *argv):
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    payload = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else None
    return code, payload, cap
