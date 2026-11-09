# CLAUDE.md：cloud-image-gen（imagegen）

這是一個 CLI 工具。它呼叫 OpenAI 或 Gemini 的官方圖片生成 API，把回傳的圖片存到專案，並為每次生成寫一份 JSON 紀錄。本檔規定 Claude Code 何時、以及如何呼叫它。

## 付費呼叫授權狀態

**目前狀態：尚未授權。**

使用者還沒確認首筆付費測試要用的模型和費用。在使用者把上面的狀態改為「已授權」之前，規則如下：
- 只能執行 `--dry-run`、`models`、`check`。
- 要實際生圖時，先把 dry-run 的 `model`、`params`、`pricing_note` 列給使用者，取得同意後才能執行不帶 `--dry-run` 的指令。

## 何時呼叫

使用者用自然語言要求一張圖時就呼叫，例如「生成一張微膠囊剖面概念圖」「做一張封面插圖」「畫一張製程示意圖」。

以下情況**不要**呼叫：
- 使用者要的是資料圖表（長條圖、折線圖等）。這類圖要用程式繪製，例如 matplotlib，不該用生圖模型。
- 圖中需要精確的數據、精確的化學結構式，或大量中文標註文字。生圖模型容易把這些畫錯。這種情況建議由模型生成底圖，文字標註再到 PPT 或 Word 裡另外加。

## 如何呼叫

從儲存庫根目錄執行：

```bash
uv run --project cloud-image-gen imagegen generate --prompt "<英文或中文提示詞>" -o cloud-image-gen/output/<簡短檔名>.png
```

- 不指定 `--provider` 和 `--model` 時，使用 `imagegen.toml` 的預設值，或環境變數 `IMAGEGEN_DEFAULT_PROVIDER`、`IMAGEGEN_OPENAI_MODEL`、`IMAGEGEN_GEMINI_MODEL`。使用者指定了 provider 或模型才加上對應參數。
- 圖片設定：
  - OpenAI 可用 `--size`、`--quality`、`--background`、`--output-format`、`--output-compression`、`--moderation`。
  - Gemini 可用 `--aspect-ratio`、`--image-size`。
  - 某個模型可用哪些值，執行 `imagegen models` 查詢。不要自行猜測。
- 簡報用圖：OpenAI 用 `--size 1536x1024`，Gemini 用 `--aspect-ratio 16:9`。
- 每次只生成 1 張，不要加 `--n`。
- 提示詞要具體寫出主題、構圖、風格、背景，以及「不要文字（no text）」。

### 讀取結果

stdout 最後一行是 JSON：
- 成功時：`{"status":"ok","images":[...],"record":"...json"}`。
- 失敗時：`{"status":"error","kind":...,"hint":...}`。

| 結束碼 | kind | Claude 的處置 |
|---|---|---|
| 0 | — | 回報圖片路徑。需要時可以用 Read 檢視圖片內容 |
| 2 | invalid | 依訊息修正參數後重跑（不另外產生費用） |
| 3 | billing | **立即停止**。告知使用者是額度或帳單問題。**不要改用其他 provider 或模型重試** |
| 4 | auth | 停止。請使用者自己設定環境變數。不要要求使用者把金鑰貼進對話 |
| 5 | blocked | 告知被安全政策攔截。可以建議改寫提示詞，但須經使用者同意才重送 |
| 6 / 7 | transient / other | 回報錯誤，不要自行反覆重跑 |

## 生成後插入文件

工具輸出的是一般 PNG、JPEG 或 WebP 檔案，路徑在結果 JSON 的 `images` 欄位。插入文件時沿用既有工具：
- Word：docx skill。
- PDF：pdf skill。
- 簡報：本儲存庫的 pptx-from-layouts skill，或 pptx skill。

紀錄 JSON 和圖片放在同一個資料夾，可以作為圖片來源的追溯依據。

## 安全規則

- 金鑰只從環境變數讀取（`OPENAI_API_KEY`、`GEMINI_API_KEY`，Gemini 另接受 `GOOGLE_API_KEY`），或從 `cloud-image-gen/.env` 載入。
  - 不要讀取或顯示 `.env` 的內容。
  - 不要在指令中寫出金鑰。
  - 不要提交 `.env`。
- 本工具只會把**提示詞文字**送到 API，不會上傳任何檔案。未經使用者同意，不要把專案中的文件或圖片內容抄進提示詞。
- `output/` 已被 git 忽略。需要提交的成品圖片，要先徵得使用者同意，再複製到要用的位置。
- 不要修改 `imagegen.toml` 的模型清單。要新增模型時，先查官方文件，並和使用者確認。

## 開發

```bash
uv run --project cloud-image-gen pytest -q
```

測試全部離線執行：每個 provider client 都換成假物件，若有測試嘗試建立真實 client，該測試會直接失敗。
