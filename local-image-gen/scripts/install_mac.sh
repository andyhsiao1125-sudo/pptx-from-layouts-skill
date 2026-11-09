#!/bin/bash
# local-image-gen 一鍵安裝與首張測試圖（Apple Silicon Mac）
#
#   bash local-image-gen/scripts/install_mac.sh
#
# 會做的事（每一步都可重複執行，已完成的會略過）：
#   1. 檢查環境：macOS、arm64、記憶體、磁碟、不是 root
#   2. 安裝 uv（有 Homebrew 就用 brew；否則用官方腳本，不修改 shell 設定檔）  ← 先問你 y/N
#   3. uv tool install --python 3.13 mflux（uv 管理的 Python，不動系統 Python）
#   4. 建立 imagegen 環境，並執行 imagegen check（核對 mflux-generate --help 參數）
#   5. 唯讀查詢 Hugging Face：q4 預量化 repo、授權、大小                       ← 任一項不合格就停止
#   6. 下載模型並生成測試圖（schnell / q4 / 512x512 / 4 步 / seed 42）        ← 先問你 y/N
#   7. 確認 PNG 存在且可開啟，列出 JSON 紀錄
#
# 不使用 sudo，不修改系統 Python，不安裝 ComfyUI 或其他外掛，不需要 API 金鑰。
# 相容 macOS 內建的 bash 3.2。

set -euo pipefail
RC=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${PROJECT_DIR}/output"
LOG="${OUT_DIR}/install_$(date +%Y%m%d-%H%M%S).log"
TEST_PNG="${OUT_DIR}/test_seed42.png"
PROMPT="A realistic studio photograph of a single white ceramic sphere on a light gray background, soft lighting, clean composition, no text."
MIN_FREE_GB=50

mkdir -p "${OUT_DIR}"
exec > >(tee -a "${LOG}") 2>&1

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   [OK] %s\n' "$*"; }
fail() { printf '   [停止] %s\n   完整紀錄：%s\n' "$*" "${LOG}"; exit 1; }
ask()  {  # ask "問題" -> 0 if yes
  local reply
  printf '\n>>> %s [y/N] ' "$1"
  read -r reply </dev/tty || reply=""
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------- 1. 環境
say "1/7 檢查環境"
[ "$(id -u)" -ne 0 ] || fail "請不要用 root 或 sudo 執行本腳本"
[ "$(uname -s)" = "Darwin" ] || fail "本腳本只支援 macOS（目前：$(uname -s)）"
[ "$(uname -m)" = "arm64" ] || fail "需要 Apple Silicon（arm64），目前：$(uname -m)"
MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
FREE_GB=$(df -g "${HOME}" | awk 'NR==2 {print $4}')
ok "macOS $(sw_vers -productVersion)，$(sysctl -n machdep.cpu.brand_string)，記憶體 ${MEM_GB} GiB，可用磁碟 ${FREE_GB} GiB"
[ "${FREE_GB}" -ge "${MIN_FREE_GB}" ] || fail "可用磁碟少於 ${MIN_FREE_GB} GiB（若 MFLUX 退回下載完整權重約需 30 GB 以上）"
command -v git >/dev/null || fail "找不到 git"
ok "git $(git --version | awk '{print $3}')；系統 python3：$(command -v python3 || echo 無)（不會被修改）"

export PATH="${HOME}/.local/bin:${PATH}"   # 只影響本腳本執行期間

# ---------------------------------------------------------------- 2. uv
say "2/7 uv"
if command -v uv >/dev/null; then
  ok "已安裝 $(uv --version)，略過"
else
  if command -v brew >/dev/null; then
    METHOD="brew install uv（安裝到 $(brew --prefix)/bin）"
  else
    METHOD="uv 官方腳本，安裝到 ~/.local/bin，設定 UV_NO_MODIFY_PATH=1（不修改 ~/.zshrc 等設定檔）"
  fi
  echo "   將要安裝 uv：${METHOD}"
  echo "   之後會用 uv 安裝 MFLUX（含 uv 管理的 Python 3.13，位於 ~/.local/share/uv/）。"
  ask "確認安裝 uv 與 MFLUX？" || fail "使用者取消安裝"
  CONFIRMED_INSTALL=1
  if command -v brew >/dev/null; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  fi
  command -v uv >/dev/null || fail "uv 安裝後仍找不到"
  ok "$(uv --version)"
fi

# ---------------------------------------------------------------- 3. MFLUX
say "3/7 MFLUX"
if uv tool list 2>/dev/null | grep -q '^mflux '; then
  ok "已安裝：$(uv tool list | grep '^mflux ')，略過"
else
  if [ -z "${CONFIRMED_INSTALL:-}" ]; then
    ask "將執行 uv tool install --python 3.13 mflux，確認？" || fail "使用者取消安裝"
  fi
  uv tool install --python 3.13 mflux
  ok "$(uv tool list | grep '^mflux ')"
fi
command -v mflux-generate >/dev/null || fail "找不到 mflux-generate（~/.local/bin 是否存在？）"
mflux-generate --help > "${OUT_DIR}/mflux_help.txt" 2>&1 || true
ok "已把 mflux-generate --help 存到 ${OUT_DIR}/mflux_help.txt"

# ---------------------------------------------------------------- 4. imagegen
say "4/7 imagegen 環境與參數核對"
uv sync --project "${PROJECT_DIR}" --quiet
CHECK_OUT=$(uv run --project "${PROJECT_DIR}" imagegen check) || { echo "${CHECK_OUT}"; fail "imagegen check 未通過（參數與目前 MFLUX 版本不符）"; }
echo "   ${CHECK_OUT}"
ok "mflux-generate 參數齊全"

# ---------------------------------------------------------------- 5. 模型來源 / 授權 / 大小
say "5/7 下載前檢查（唯讀查詢 Hugging Face，不下載模型）"
set +e
uv run --project "${PROJECT_DIR}" python "${SCRIPT_DIR}/hf_model_check.py" --out "${OUT_DIR}/model_check.json"
RC=$?
set -e
[ ${RC} -eq 0 ] || fail "下載前檢查未全部通過（詳見上方與 ${OUT_DIR}/model_check.json），依規則不下載模型"
ok "來源、授權與大小均符合；報告存於 ${OUT_DIR}/model_check.json"

# ---------------------------------------------------------------- 6. 下載 + 測試圖
say "6/7 下載模型並生成測試圖"
if [ -f "${TEST_PNG}" ]; then
  ok "測試圖已存在（${TEST_PNG}），略過"
else
  echo "   設定：model=schnell quantize=4 width=512 height=512 steps=4 seed=42"
  echo "   提示詞：${PROMPT}"
  echo "   注意：實際下載由 MFLUX 決定；正常會取用上方檢查的 q4 預量化 repo。"
  ask "確認下載上方列出的模型並生成測試圖？" || fail "使用者取消下載（之後重新執行本腳本即可從這一步繼續）"
  set +e
  uv run --project "${PROJECT_DIR}" imagegen generate --allow-download \
      --seed 42 --width 512 --height 512 --steps 4 --quantize 4 \
      --prompt "${PROMPT}" -o "${TEST_PNG}"
  RC=$?
  set -e
  [ ${RC} -eq 0 ] || fail "生成失敗（結束碼 ${RC}）；錯誤紀錄：${TEST_PNG%.png}.error.json。請把它貼給 Claude 診斷，不要自行改下載其他模型"
fi

# ---------------------------------------------------------------- 7. 驗證
say "7/7 驗證輸出"
[ -s "${TEST_PNG}" ] || fail "找不到 ${TEST_PNG}"
file "${TEST_PNG}"
sips -g pixelWidth -g pixelHeight "${TEST_PNG}" | tail -2
[ -f "${TEST_PNG%.png}.json" ] && cat "${TEST_PNG%.png}.json"
open "${TEST_PNG}" || true
ok "完成。測試圖：${TEST_PNG}"
echo
echo "後續：在 local-image-gen/CLAUDE.md 把「模型下載狀態」改為「已下載」，"
echo "之後在本專案用 Claude Code 說「生成一張…」即可直接呼叫 imagegen。"
echo "安裝紀錄：${LOG}"
