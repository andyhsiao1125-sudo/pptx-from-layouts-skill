"""Read-only pre-download check for the FLUX.1-schnell 4-bit MFLUX weights.

Queries the public Hugging Face API (no login, nothing downloaded except JSON
metadata) and reports, for the upstream repo and each mflux-community
pre-quantized schnell candidate: license, gated flag, file count and total
size. Emits a verdict; downloading is only offered when every check passes.

Usage: python hf_model_check.py [--out report.json]
Exit codes: 0 = all checks passed, 1 = a check failed, 2 = network/API error.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

API = "https://huggingface.co/api/models"
UPSTREAM = "black-forest-labs/FLUX.1-schnell"
EXPECTED_LICENSE = "apache-2.0"
WEIGHT_EXT = (".safetensors", ".bin", ".gguf", ".npz")


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "imagegen-model-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def summarize(info: dict) -> dict:
    files = info.get("siblings") or []
    weights = [f for f in files if f.get("rfilename", "").endswith(WEIGHT_EXT)]
    lic = (info.get("cardData") or {}).get("license")
    if not lic:
        lic = next((t.split(":", 1)[1] for t in info.get("tags", []) if t.startswith("license:")), None)
    return {
        "id": info.get("id"),
        "sha": info.get("sha"),
        "license": lic,
        "gated": info.get("gated"),
        "weight_files": len(weights),
        "weight_bytes": sum(int(f.get("size") or 0) for f in weights),
        "total_bytes": sum(int(f.get("size") or 0) for f in files),
        "sizes_complete": all(f.get("size") is not None for f in files),
    }


def is_q4(repo_id: str) -> bool:
    name = repo_id.lower()
    return any(k in name for k in ("q4", "4bit", "4-bit"))


def verdict(upstream: dict | None, candidates: list[dict]) -> dict:
    """Pure decision logic (unit-tested). Picks the q4 candidate and checks it."""
    checks, chosen = [], None
    q4 = [c for c in candidates if is_q4(c["id"] or "")]
    checks.append(("找到 schnell 的 4-bit 預量化 repo", bool(q4)))
    if q4:
        chosen = q4[0]
        checks.append(("檔案大小資訊完整", chosen["sizes_complete"] and chosen["weight_bytes"] > 0))
        lic = (chosen["license"] or "").lower()
        checks.append((f"預量化 repo 授權為 {EXPECTED_LICENSE}", lic == EXPECTED_LICENSE))
        if upstream:
            checks.append((f"上游 {UPSTREAM} 授權為 {EXPECTED_LICENSE}",
                           (upstream["license"] or "").lower() == EXPECTED_LICENSE))
            if upstream["weight_bytes"]:
                checks.append(("預量化權重小於上游完整權重的 50%",
                               chosen["weight_bytes"] < 0.5 * upstream["weight_bytes"]))
        checks.append(("不需要登入（非 gated）", not chosen["gated"]))
    return {"chosen": chosen, "checks": [{"check": n, "pass": bool(p)} for n, p in checks],
            "all_pass": bool(checks) and all(p for _, p in checks)}


def gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        upstream = summarize(fetch(f"{API}/{UPSTREAM}?blobs=true"))
        listing = fetch(f"{API}?author=mflux-community&search=schnell&limit=50")
        candidates = [summarize(fetch(f"{API}/{m['id']}?blobs=true")) for m in listing if m.get("id")]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"無法查詢 Hugging Face API：{e}", file=sys.stderr)
        return 2

    v = verdict(upstream, candidates)
    report = {"upstream": upstream, "candidates": candidates, **v}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"\n上游 {UPSTREAM}：授權 {upstream['license']}，gated={upstream['gated']}，"
          f"權重 {gb(upstream['weight_bytes'])}")
    print("mflux-community 的 schnell repo：")
    for c in candidates:
        mark = " <= 將使用" if v["chosen"] and c["id"] == v["chosen"]["id"] else ""
        print(f"  - {c['id']}：授權 {c['license']}，權重 {gb(c['weight_bytes'])}（{c['weight_files']} 個檔）{mark}")
    if not candidates:
        print("  （無）")
    print("檢查項目：")
    for c in v["checks"]:
        print(f"  [{'OK' if c['pass'] else 'NG'}] {c['check']}")
    return 0 if v["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
