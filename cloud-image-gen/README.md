# cloud-image-gen：雲端生圖 CLI（imagegen）

本工具透過 **OpenAI** 或 **Google Gemini** 的官方圖片生成 API 生成圖片，自動存檔，並寫一份 JSON 紀錄。設計目標是讓 Claude Code 能直接呼叫，使用者不必開啟 ChatGPT 或 Gemini 網頁。

## 一、安裝

需求：Python 3.11 以上，以及 [uv](https://docs.astral.sh/uv/)。

```bash
cd cloud-image-gen
```

```bash
uv sync
```

`uv sync` 會在 `cloud-image-gen/.venv` 建立獨立的虛擬環境，並依 `uv.lock` 安裝固定版本的套件，不會動到系統 Python。

## 二、設定金鑰

兩種方式擇一。

**方式一：用 `.env` 檔**

```bash
cp .env.example .env
```

複製後用編輯器打開 `.env`，填入 `OPENAI_API_KEY` 或 `GEMINI_API_KEY`。

**方式二：在 shell 設定環境變數**

```bash
export OPENAI_API_KEY=...
```

說明：
- `.env` 已列在 `.gitignore`，不會被提交。
- 如果環境變數和 `.env` 都有設定，以環境變數為準。
- 本工具不會把金鑰印到終端機。錯誤訊息中如果出現金鑰，也會先遮蔽再顯示。

確認金鑰是否已設定（只顯示有或沒有，不顯示內容）：

```bash
uv run imagegen check
```

## 三、使用方式

```bash
# 先試跑：只驗證參數並顯示請求內容，不連網、不需要金鑰、不計費
uv run imagegen generate --provider openai --prompt "..." --dry-run

# 實際生成（會計費）
uv run imagegen generate --provider openai --prompt "..." -o output/test.png

# Gemini，16:9
uv run imagegen generate --provider gemini --aspect-ratio 16:9 --prompt "..." -o output/g.png

# 列出模型、可用參數與官方價格備註
uv run imagegen models
```

從儲存庫根目錄執行時，改用 `uv run --project cloud-image-gen imagegen ...`。

| 參數 | 適用 | 說明 |
|---|---|---|
| `--provider` | 共通 | `openai` 或 `gemini`（預設值見設定檔） |
| `--model` | 共通 | 必須是 `imagegen.toml` 列出的模型 |
| `--prompt` / `--prompt-file` | 共通 | 提示詞，或 UTF-8 文字檔 |
| `-o, --output` | 共通 | 輸出圖片路徑；預設為 `output/<時間>_<provider>_<摘要>.png` |
| `--n` | 共通 | 張數，預設 1；上限由設定檔的 `max_images_per_call` 決定（目前為 1） |
| `--dry-run` | 共通 | 只驗證參數，不送出請求 |
| `--overwrite` | 共通 | 允許覆寫既有檔案；預設拒絕覆寫 |
| `--max-retries` | 共通 | 暫時性錯誤的重試次數（預設 2，最多 5） |
| `--size` `--quality` `--background` `--output-format` `--output-compression` `--moderation` | OpenAI | 可用值依模型而定，見 `models` |
| `--aspect-ratio` `--image-size` | Gemini | 可用值依模型而定，見 `models` |

## 四、模型切換

模型名稱只寫在 `imagegen.toml` 和環境變數裡，程式碼中沒有寫死任何模型。選用優先順序：

1. 指令列的 `--model`
2. 環境變數 `IMAGEGEN_OPENAI_MODEL` 或 `IMAGEGEN_GEMINI_MODEL`
3. `imagegen.toml` 的 `default_model`

要新增模型時，先查官方文件，再在 `imagegen.toml` 加一段 `[providers.<name>.models."<id>"]`，填入可用參數與價格備註。

## 五、輸出與紀錄

每次生成會產生下列檔案：
- 圖片檔。副檔名依 API 實際回傳的格式決定。存檔後會用 Pillow 重新開啟驗證，確認是有效的圖片。
- 同名的 `.json` 紀錄，欄位如下表。
- 失敗時另寫 `<檔名>.error.json`，記錄錯誤類型、HTTP 狀態與錯誤碼。若 API 有回傳用量，也一併記錄。

| 欄位 | 內容 |
|---|---|
| `provider`、`model`、`prompt`、`request_params` | 實際送出的請求內容 |
| `started_at_utc`、`finished_at_utc`、`duration_seconds`、`attempts` | 生成時間、耗時與嘗試次數 |
| `images[]` | 路徑、格式、寬高、位元組數、SHA-256 |
| `usage` | **API 原樣回傳的用量資訊**；API 沒有回傳時，以 `usage_note` 說明 |
| `response_meta` | API 回傳的中繼資料，例如 OpenAI 的 size、quality，Gemini 的 model_version、finish_reason |
| `fields_not_provided_by_api` | 說明為什麼沒有 seed 與實際費用（兩者皆不捏造） |

## 六、錯誤與重試政策

| 狀況 | 處理方式 | 結束碼 |
|---|---|---|
| 額度不足、帳單未啟用、花費上限（OpenAI `insufficient_quota`、`*_spend_limit_exceeded` 等；Gemini 429、`FAILED_PRECONDITION`） | **立即停止，不重試，也不切換模型** | 3 |
| 金鑰無效或權限不足 | 停止 | 4 |
| 參數錯誤 | 停止 | 2 |
| 被安全政策攔截，或回應中沒有圖片 | 停止 | 5 |
| 連線錯誤、5xx、OpenAI 明確標示為速率限制的 429 | 有上限地重試（預設 2 次，遵守 `Retry-After`） | 6 |

補充說明：
- SDK 內建的自動重試已關閉，重試完全由本工具控制。
- OpenAI 沒有標明錯誤碼的 429，以及 Gemini 的所有 429，一律視為額度問題處理。這是刻意的保守設計，因為 Gemini 的 429 同時涵蓋速率限制和額度耗盡，無法可靠區分。

## 七、測試（不發出 API 請求）

```bash
uv run pytest -q
```

共 24 項測試，涵蓋：參數驗證、預設 1 張、兩個 provider 的存檔與 JSON 紀錄、額度錯誤立即停止、重試上限、金鑰遮蔽、`.gitignore` 檢查。

## 八、清理

依需要刪除對應的項目：

```bash
# 只刪生成的圖片與紀錄
rm -rf cloud-image-gen/output

# 刪除虛擬環境（之後可用 uv sync 重建）
rm -rf cloud-image-gen/.venv

# 刪除本機金鑰檔
rm -f cloud-image-gen/.env
```

本工具不常駐任何服務，執行完即結束，不需要另外關閉。

## 九、資料與隱私

- 只會把提示詞文字送到 API，不會上傳專案內的任何檔案。
- 兩家供應商對 API 資料的使用條款不同。Gemini 價目表註明：免費層的資料會被用於改善產品，付費層則不會。正式使用前，請自行查閱兩家的資料使用條款。
