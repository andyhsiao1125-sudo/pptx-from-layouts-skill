from __future__ import annotations

import json
from pathlib import Path

from conftest import run

from imagegen.providers import local_mflux

PROMPT = ("A realistic studio photograph of a single white ceramic sphere on a light gray background, "
          "soft lighting, clean composition, no text.")


def _arg(argv, flag):
    return argv[argv.index(flag) + 1]


# ---------------------------------------------------------------- dry run & validation
def test_dry_run_runs_nothing(capsys, mflux):
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "--seed", "42", "--dry-run")
    assert code == 0 and out["status"] == "dry_run"
    assert out["params"] == {"quantize": 4, "width": 512, "height": 512, "steps": 4, "seed": 42}
    assert out["offline"] is True and out["seed_was_random"] is False
    assert mflux.calls == []


def test_random_seed_is_explicit_and_reported(capsys, mflux):
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "--dry-run")
    assert code == 0 and isinstance(out["params"]["seed"], int) and out["seed_was_random"] is True


def test_validation(capsys, mflux):
    for extra in (["--quantize", "7"], ["--steps", "0"], ["--steps", "50"], ["--width", "500"],
                  ["--height", "4096"], ["--seed", "-1"], ["--model", "dev"]):
        code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "--dry-run", *extra)
        assert code == 2 and out["kind"] == "invalid", extra
    assert mflux.calls == []


def test_refuses_to_overwrite(capsys, mflux, tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    code, _, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 2 and mflux.gen_calls == []


# ---------------------------------------------------------------- success
def test_first_run_spec_success(capsys, mflux):
    code, out, cap = run(capsys, "generate", "--prompt", PROMPT, "--seed", "42", "-o", "output/test_seed42.png")
    assert code == 0, cap.err
    argv = mflux.gen_calls[0].argv
    assert _arg(argv, "--model") == "schnell" and _arg(argv, "--quantize") == "4"
    assert (_arg(argv, "--width"), _arg(argv, "--height"), _arg(argv, "--steps"), _arg(argv, "--seed")) == \
           ("512", "512", "4", "42")
    assert _arg(argv, "--prompt") == PROMPT
    assert mflux.gen_calls[0].env["HF_HUB_OFFLINE"] == "1"

    img = Path(out["image"])
    assert img.exists() and img.read_bytes().startswith(b"\x89PNG")
    rec = json.loads(Path(out["record"]).read_text())
    assert rec["status"] == "success" and rec["mflux_version"] == "0.23.0"
    assert rec["model"] == "schnell" and rec["quantize"] == 4 and rec["prompt"] == PROMPT
    assert (rec["seed"], rec["steps"], rec["width"], rec["height"]) == (42, 4, 512, 512)
    assert rec["image"]["width"] == 512 and rec["image"]["format"] == "PNG"
    assert rec["duration_seconds"] >= 0 and rec["peak_memory"] == "未量測"
    assert rec["model_source"]["upstream_repo"] == "black-forest-labs/FLUX.1-schnell"


def test_allow_download_lifts_offline(capsys, mflux, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    code, _, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png", "--allow-download")
    assert code == 0 and "HF_HUB_OFFLINE" not in mflux.gen_calls[0].env


def test_model_from_env_var_must_be_configured(capsys, mflux, monkeypatch):
    monkeypatch.setenv("IMAGEGEN_LOCAL_MODEL", "flux-dev")
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "--dry-run")
    assert code == 2


# ---------------------------------------------------------------- setup checks
def test_missing_binary(capsys, mflux, monkeypatch):
    monkeypatch.setattr(local_mflux, "which", lambda name: None)
    monkeypatch.setattr(local_mflux, "find_command", lambda lcfg: None)
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 3 and out["kind"] == "setup"


def test_help_missing_flag_stops_before_generation(capsys, mflux):
    mflux.help = mflux.help.replace("--quantize {3,4,5,6,8}", "--quantization-bits N")
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 3 and "--quantize" in out["message"] and mflux.gen_calls == []


def test_flag_match_is_exact():
    assert local_mflux.missing_flags("--model-path X --prompt-file F") == list(local_mflux.FLAG_FOR.values())


def test_check_command(capsys, mflux):
    code, out, _ = run(capsys, "check")
    assert code == 0 and out["missing_flags"] == [] and out["mflux_version"] == "0.23.0"
    assert mflux.gen_calls == []


def test_version_unknown_is_null_not_guessed(capsys, mflux):
    mflux.version_out = "usage: unrecognized"
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 0 and json.loads(Path(out["record"]).read_text())["mflux_version"] is None


# ---------------------------------------------------------------- failures (no retry)
def test_model_not_cached_in_offline_mode(capsys, mflux, tmp_path):
    mflux.mode = "not_cached"
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 4 and out["kind"] == "model_not_cached" and len(mflux.gen_calls) == 1
    err = json.loads((tmp_path / "a.error.json").read_text())
    assert "LocalEntryNotFoundError" in err["error"]["stderr_tail"]
    assert not (tmp_path / "a.png").exists()


def test_runtime_failure_kept_and_not_retried(capsys, mflux, tmp_path):
    mflux.mode = "fail"
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")
    assert code == 5 and len(mflux.gen_calls) == 1
    assert "out of memory" in json.loads((tmp_path / "a.error.json").read_text())["error"]["stderr_tail"]


def test_timeout(capsys, mflux):
    mflux.mode = "timeout"
    assert run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")[0] == 6


def test_no_image_and_invalid_image(capsys, mflux, tmp_path):
    mflux.mode = "no_image"
    assert run(capsys, "generate", "--prompt", PROMPT, "-o", "a.png")[0] == 7
    mflux.mode = "garbage"
    code, out, _ = run(capsys, "generate", "--prompt", PROMPT, "-o", "b.png")
    assert code == 7 and out["kind"] == "no_image"


def test_repo_hygiene():
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text().splitlines()
    assert "output/" in ignore and ".env" in ignore
