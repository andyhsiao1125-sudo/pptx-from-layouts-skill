from __future__ import annotations

import json
from pathlib import Path

from conftest import gemini_error, gemini_ok, openai_error, openai_ok, png_bytes, run

PROMPT = "microcapsule cross-section concept diagram"
SECRET = "sk-test-SECRET-0123456789abcdef"


# ---------------------------------------------------------------- dry run & validation
def test_dry_run_needs_no_key_and_no_network(capsys):
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "--dry-run")
    assert code == 0 and out["status"] == "dry_run"
    req = out["request"]
    assert req["model"] == "gpt-image-2" and req["n"] == 1
    assert req["params"] == {"size": "1024x1024", "quality": "low", "output_format": "png"}
    assert req["pricing_note"]


def test_model_from_env_var(capsys, monkeypatch):
    monkeypatch.setenv("IMAGEGEN_GEMINI_MODEL", "gemini-nano-banana-2.1")
    code, out, _ = run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "--dry-run")
    assert code == 0 and out["request"]["model"] == "gemini-nano-banana-2.1"
    assert out["request"]["params"]["image_size"] == "1K"


def test_unlisted_model_rejected(capsys):
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--model", "dall-e-3",
                       "--prompt", PROMPT, "--dry-run")
    assert code == 2 and out["kind"] == "invalid"


def test_provider_specific_options_enforced(capsys):
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--aspect-ratio", "16:9",
                       "--prompt", PROMPT, "--dry-run")
    assert code == 2 and "--aspect-ratio" in out["message"]
    code, out, _ = run(capsys, "generate", "--provider", "gemini", "--image-size", "2K",
                       "--prompt", PROMPT, "--dry-run")
    assert code == 2  # gemini-2.5-flash-image has no image_size


def test_default_is_one_image_and_cap_enforced(capsys):
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--n", "2", "--prompt", PROMPT, "--dry-run")
    assert code == 2 and "max_images_per_call" in out["message"]


def test_custom_size_rules(capsys):
    ok, out, _ = run(capsys, "generate", "--provider", "openai", "--size", "1536x864", "--prompt", PROMPT, "--dry-run")
    assert ok == 0 and out["request"]["params"]["size"] == "1536x864"
    for bad in ("1000x1000", "4800x1600", "512x2048"):
        code, _, _ = run(capsys, "generate", "--provider", "openai", "--size", bad, "--prompt", PROMPT, "--dry-run")
        assert code == 2, bad
    code, _, _ = run(capsys, "generate", "--provider", "openai", "--model", "gpt-image-1-mini",
                     "--size", "1536x864", "--prompt", PROMPT, "--dry-run")
    assert code == 2


def test_missing_key_stops_before_any_call(capsys, fake_openai):
    fake = fake_openai(openai_ok())
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 4 and out["kind"] == "auth" and fake.calls == []


def test_refuses_to_overwrite(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_ok())
    (isolated.tmp / "a.png").write_bytes(b"x")
    code, _, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 2 and fake.calls == []


# ---------------------------------------------------------------- success paths
def test_openai_success_saves_image_and_record(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    usage = {"input_tokens": 20, "output_tokens": 196, "total_tokens": 216,
             "input_tokens_details": {"text_tokens": 20, "image_tokens": 0}}
    fake = fake_openai(openai_ok(usage=usage))
    code, out, cap = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "out/a.png")
    assert code == 0, cap.err
    assert fake.calls[0] == {"model": "gpt-image-2", "prompt": PROMPT, "n": 1,
                             "size": "1024x1024", "quality": "low", "output_format": "png"}
    img = Path(out["images"][0])
    assert img.exists() and img.read_bytes().startswith(b"\x89PNG")
    rec = json.loads(Path(out["record"]).read_text())
    assert rec["status"] == "success" and rec["model"] == "gpt-image-2" and rec["prompt"] == PROMPT
    assert rec["usage"] == usage and rec["images"][0]["width"] == 8
    assert rec["started_at_utc"] and rec["duration_seconds"] >= 0
    assert "seed" not in rec and "seed" in rec["fields_not_provided_by_api"]
    assert SECRET not in cap.out + cap.err + Path(out["record"]).read_text()


def test_openai_without_usage_is_recorded_as_absent(capsys, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake_openai(openai_ok())
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    rec = json.loads(Path(out["record"]).read_text())
    assert code == 0 and "usage" not in rec and rec["usage_note"]


def test_gemini_success_records_usage_metadata(capsys, monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    fake = fake_gemini(gemini_ok())
    code, out, cap = run(capsys, "generate", "--provider", "gemini", "--aspect-ratio", "16:9",
                         "--prompt", PROMPT, "-o", "g.png")
    assert code == 0, cap.err
    cfg = fake.calls[0]["config"]
    assert fake.calls[0]["model"] == "gemini-2.5-flash-image"
    assert cfg.image_config.aspect_ratio == "16:9" and cfg.image_config.image_size is None
    rec = json.loads(Path(out["record"]).read_text())
    assert rec["usage"]["total_token_count"] == 1302
    assert rec["response_meta"]["model_version"] == "gemini-2.5-flash-image"
    assert rec["model_text"] == ["Here is your image."]


def test_gemini_jpeg_gets_correct_extension(capsys, monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    fake_gemini(gemini_ok(data=png_bytes(fmt="JPEG"), mime="image/jpeg"))
    code, out, _ = run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "-o", "g.png")
    assert code == 0 and out["images"][0].endswith("g.jpg")


# ---------------------------------------------------------------- failure policy
def test_openai_insufficient_quota_stops_immediately(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(429, "insufficient_quota", "insufficient_quota"))
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 3 and out["kind"] == "billing"
    assert len(fake.calls) == 1 and isolated.sleeps == []
    assert not (isolated.tmp / "a.png").exists()
    assert json.loads((isolated.tmp / "a.error.json").read_text())["error"]["code"] == "insufficient_quota"


def test_openai_spend_limit_stops(capsys, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(429, "project_spend_limit_exceeded"))
    code, _, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 3 and len(fake.calls) == 1


def test_openai_unknown_429_is_not_retried(capsys, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(429, None))
    code, _, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 3 and len(fake.calls) == 1


def test_openai_rate_limit_retried_then_succeeds(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(429, "rate_limit_exceeded", headers={"retry-after": "3"}), openai_ok())
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 0 and len(fake.calls) == 2 and isolated.sleeps == [3.0]
    assert json.loads(Path(out["record"]).read_text())["attempts"] == 2


def test_transient_errors_bounded(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(503, "server_is_overloaded"))
    code, out, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 6 and len(fake.calls) == 3  # 1 + max_retries(2)
    code, _, _ = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "b.png",
                     "--max-retries", "0")
    assert code == 6 and len(fake.calls) == 4


def test_auth_and_bad_request_not_retried(capsys, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake = fake_openai(openai_error(401, "invalid_api_key"))
    assert run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")[0] == 4
    fake = fake_openai(openai_error(400, "moderation_blocked"))
    assert run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "b.png")[0] == 5
    assert len(fake.calls) == 1


def test_gemini_429_and_billing_precondition_stop(capsys, isolated, monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    fake = fake_gemini(gemini_error(429, "RESOURCE_EXHAUSTED"))
    assert run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "-o", "a.png")[0] == 3
    assert len(fake.calls) == 1
    fake = fake_gemini(gemini_error(400, "FAILED_PRECONDITION"))
    assert run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "-o", "b.png")[0] == 3
    assert isolated.sleeps == []


def test_gemini_server_error_retried(capsys, monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    fake = fake_gemini(gemini_error(503, "UNAVAILABLE"), gemini_ok())
    assert run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "-o", "a.png")[0] == 0
    assert len(fake.calls) == 2


def test_gemini_no_image_is_blocked(capsys, monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    fake_gemini(gemini_ok(with_image=False))
    code, out, _ = run(capsys, "generate", "--provider", "gemini", "--prompt", PROMPT, "-o", "a.png")
    assert code == 5 and out["kind"] == "blocked"


# ---------------------------------------------------------------- secrets
def test_key_is_redacted_from_error_output(capsys, isolated, monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake_openai(openai_error(401, "invalid_api_key", message=f"Incorrect API key provided: {SECRET}"))
    code, _, cap = run(capsys, "generate", "--provider", "openai", "--prompt", PROMPT, "-o", "a.png")
    assert code == 4
    assert SECRET not in cap.out + cap.err + (isolated.tmp / "a.error.json").read_text()


def test_check_reports_presence_only(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    code, out, cap = run(capsys, "check")
    assert code == 0 and out["api_keys_set"]["openai"]["OPENAI_API_KEY"] is True
    assert out["api_keys_set"]["gemini"]["GEMINI_API_KEY"] is False
    assert SECRET not in cap.out + cap.err


def test_repo_hygiene():
    root = Path(__file__).resolve().parent.parent
    ignore = (root / ".gitignore").read_text().splitlines()
    assert ".env" in ignore and "output/" in ignore
    for line in (root / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            assert line.endswith("="), f".env.example must not contain values: {line}"
