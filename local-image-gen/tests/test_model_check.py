import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "hf_model_check", Path(__file__).resolve().parent.parent / "scripts" / "hf_model_check.py")
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)

GB = 10**9


def info(id_, lic="apache-2.0", sizes=(GB * 3,), gated=False, ext=".safetensors"):
    return {"id": id_, "sha": "abc", "gated": gated, "cardData": {"license": lic},
            "siblings": [{"rfilename": f"w{i}{ext}", "size": s} for i, s in enumerate(sizes)]
                        + [{"rfilename": "README.md", "size": 100}]}


UP = mc.summarize(info("black-forest-labs/FLUX.1-schnell", sizes=(GB * 24, GB * 9)))


def test_all_pass():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/flux1-schnell-mflux-q8", sizes=(GB * 12,))),
                        mc.summarize(info("mflux-community/flux1-schnell-mflux-q4"))])
    assert v["all_pass"] and v["chosen"]["id"].endswith("q4")


def test_no_q4_repo_fails():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/flux1-schnell-mflux-q8"))])
    assert not v["all_pass"] and v["chosen"] is None


def test_license_mismatch_fails():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/schnell-4bit", lic="other"))])
    assert not v["all_pass"]


def test_too_large_fails():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/schnell-q4", sizes=(GB * 30,)))])
    assert not v["all_pass"]


def test_missing_sizes_and_gated_fail():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/schnell-q4", sizes=(None,)))])
    assert not v["all_pass"]
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/schnell-q4", gated="auto"))])
    assert not v["all_pass"]


def test_license_from_tags():
    s = mc.summarize({"id": "x", "tags": ["license:apache-2.0"], "siblings": []})
    assert s["license"] == "apache-2.0"


def test_controlnet_variant_is_not_chosen():
    # Regression: the user's real run picked this ControlNet repo as "schnell q4".
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/flux-1-schnell-controlnet-canny-mflux-q4",
                                          sizes=(GB * 10.61,)))])
    assert not v["all_pass"] and v["chosen"] is None


def test_base_chosen_among_variants():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/flux-1-schnell-controlnet-canny-mflux-q4")),
                        mc.summarize(info("mflux-community/flux-1-schnell-depth-mflux-q4")),
                        mc.summarize(info("mflux-community/flux-1-schnell-mflux-q4"))])
    assert v["all_pass"] and v["chosen"]["id"] == "mflux-community/flux-1-schnell-mflux-q4"


def test_multiple_base_candidates_is_ambiguous():
    v = mc.verdict(UP, [mc.summarize(info("mflux-community/flux-1-schnell-mflux-q4")),
                        mc.summarize(info("mflux-community/schnell-4bit"))])
    assert not v["all_pass"] and v["chosen"] is None
