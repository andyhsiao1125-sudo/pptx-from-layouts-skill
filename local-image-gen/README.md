# local-image-gen：本機免費生圖 CLI（imagegen）

本工具在 Apple Silicon Mac 上，用 **MFLUX＋FLUX.1-schnell（4-bit 量化）** 生成圖片：
- 不使用任何付費或雲端生圖 API。
- 每次生成都會留下一份 JSON 紀錄。
- 設計上可以讓 Claude Code 直接呼叫。

架構分兩層：
- **MFLUX：** 負責實際推論。以 `uv tool` 方式獨立安裝，不是本專案的套件依賴。
- **imagegen：** 本專案。負責檢查參數、呼叫 MFLUX、驗證圖片、寫入紀錄。

## 一、前提與安裝

需要的環境：
- Apple Silicon Mac
- Git
- uv
- 不需要 sudo，也不會修改系統 Python

### 1. 安裝 uv（擇一）

**方式一：用 Homebrew**

```bash
brew install uv
```

**方式二：用官方腳本**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

官方腳本會把 uv 裝到 `~/.local/bin`，並修改 shell 設定檔。如果不希望它改設定檔，在指令前加上 `UV_NO_MODIFY_PATH=1`。

### 2. 安裝 MFLUX

這一步會由 uv 管理一份 Python 3.13，安裝位置是 `~/.local/share/uv/`。

```bash
uv tool install --python 3.13 mflux
```

### 3. 安裝 imagegen

在儲存庫根目錄執行。這一步會建立 `local-image-gen/.venv`，唯一的依賴是 Pillow。

```bash
uv sync --project local-image-gen
```

### 4. 確認 MFLUX 可用

這個指令會找到 `mflux-generate`、讀取版本，並檢查目前版本的 `--help` 是否包含本工具會用到的所有參數。

```bash
uv run --project local-image-gen imagegen check
```

## 二、首次下載模型（需要人工確認）

imagegen 預設以 `HF_HUB_OFFLINE=1` 執行 MFLUX，**不會自動下載模型**。第一次下載之前，請依序確認以下三件事。

**1. 預量化模型的來源與大小**

依 MFLUX 的 README，`--quantize 4` 會優先載入 `mflux-community/<model>-mflux-q4` 這類預量化 repo。如果找不到，會退回下載完整的 bf16 權重（約 30 GB 以上）。先用下面的指令查詢：

```bash
curl -s "https://huggingface.co/api/models?author=mflux-community&search=schnell" | python3 -m json.tool
```

找到 repo 後，查它的檔案大小（`<repo>` 換成實際名稱）：

```bash
curl -s "https://huggingface.co/api/models/mflux-community/<repo>?blobs=true" | python3 -m json.tool
```

**2. 授權**

在 model card 上確認兩件事：
- 上游 `black-forest-labs/FLUX.1-schnell` 的授權（預期是 Apache-2.0）。
- 預量化 repo 標示的授權與上游一致。

**3. 停止條件**

出現以下任一情況就停止，不要下載：
- 找不到 q4 的預量化 repo。
- 授權不一致。
- 預量化 repo 的大小接近完整權重。

三件事都確認後，才執行第一次生成。只有這一次加 `--allow-download`：

```bash
uv run --project local-image-gen imagegen generate --allow-download --seed 42 \
  --prompt "A realistic studio photograph of a single white ceramic sphere on a light gray background, soft lighting, clean composition, no text." \
  -o local-image-gen/output/test_seed42.png
```

之後都不加 `--allow-download`。如果模型還沒下載，工具會回傳結束碼 4（`model_not_cached`），不會自己去下載。

## 三、日常使用

```bash
# 試跑：只驗證參數並顯示將執行的指令，不實際執行
uv run --project local-image-gen imagegen generate --prompt "..." --dry-run

# 生成（預設 schnell、q4、512×512、4 步，seed 隨機但會記錄）
uv run --project local-image-gen imagegen generate --prompt "..." -o local-image-gen/output/x.png

# 16:9 簡報用圖
uv run --project local-image-gen imagegen generate --prompt "..." --width 1024 --height 576 -o local-image-gen/output/slide.png
```

| 參數 | 說明 |
|---|---|
| `--prompt` / `--prompt-file` | 提示詞（建議用英文） |
| `-o, --output` | 輸出 PNG 路徑；預設為 `local-image-gen/output/<時間>_<摘要>.png` |
| `--width` `--height` | 256–2048，須為 16 的倍數 |
| `--steps` | 1–8 |
| `--seed` | 非負整數；不指定時隨機產生並寫入紀錄 |
| `--quantize` | 3、4、5、6 或 8（預設 4） |
| `--dry-run` | 不執行 MFLUX，只顯示將執行的指令 |
| `--overwrite` | 允許覆寫既有檔案；預設拒絕覆寫 |
| `--allow-download` | 本次允許下載模型，須先經過第二節的確認 |

## 四、輸出與紀錄

成功時會產生兩個檔案：
- 圖片：`<名稱>.png`。存檔後會用 Pillow 重新開啟，確認是有效的圖片。
- 紀錄：`<名稱>.json`，欄位如下表。

失敗時會產生 `<名稱>.error.json`，內含 MFLUX 結束碼與 stderr 最後 40 行。

| 欄位 | 內容 |
|---|---|
| `mflux_version` | 從 `mflux-generate --version` 或 `uv tool list` 讀取；讀不到時記為 null，不猜測 |
| `model`、`mflux_model_arg`、`model_source` | 模型名稱、傳給 `--model` 的值、上游 repo、授權與量化說明 |
| `quantize`、`prompt`、`seed`、`steps`、`width`、`height` | 實際使用的參數 |
| `started_at_utc`、`duration_seconds` | 開始時間與耗時（含模型載入時間） |
| `peak_memory` | 固定記為「未量測」，因為目前沒有可靠的量測方式 |
| `image` | 路徑、寬高、位元組數、SHA-256 |
| `command` | 實際執行的 mflux-generate 指令 |
| `offline_mode`、`platform` | 是否為離線模式；macOS 版本與晶片架構 |

## 五、測試（不會執行 MFLUX）

```bash
uv run --project local-image-gen pytest -q
```

共 17 項測試，涵蓋：
- 參數驗證、預設離線、`--allow-download` 解除離線
- `--help` 缺少參數時停止
- 模型未快取、記憶體不足、逾時、沒有產出圖片
- 拒絕覆寫既有檔案、JSON 紀錄欄位

## 六、關閉與清理

imagegen 不常駐任何服務，每次執行完即結束。要中止正在進行的生成，按 Ctrl+C。

依需要刪除對應的項目：

```bash
# 只刪生成的圖片與紀錄
rm -rf local-image-gen/output

# 刪除 imagegen 的虛擬環境
rm -rf local-image-gen/.venv

# 移除 MFLUX 工具
uv tool uninstall mflux

# 刪除 MFLUX 的模型快取（macOS 預設位置）
rm -rf ~/Library/Caches/mflux
```

如果模型存放在 Hugging Face 快取，可以用 `hf cache` 指令列出並刪除對應的模型。快取位置由 `HF_HOME` 決定，預設是 `~/.cache/huggingface`。
