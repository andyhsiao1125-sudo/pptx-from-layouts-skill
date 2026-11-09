# CLAUDE.md：local-image-gen（imagegen）

這是一個本機文字生圖的 CLI 工具。它呼叫使用者 Mac 上的 MFLUX（`mflux-generate`），使用 FLUX.1-schnell 的 4-bit 量化版生成圖片，把圖片存進專案，並為每次生成寫一份 JSON 紀錄。

本工具**不使用任何雲端生圖 API**，也沒有 OpenAI 或 Gemini provider。使用者已明確取消這兩項，不要再加回來，也不要建議改用雲端付費 API。

## 執行環境前提

- 本工具只能在已安裝 MFLUX 的機器上執行，也就是使用者的 Apple Silicon Mac。
- 雲端容器沒有 MFLUX，在那裡執行 `imagegen check` 會回傳結束碼 3（kind 為 `setup`）。遇到這種情況，請告知使用者需要在 Mac 上執行，不要嘗試在容器內安裝 MFLUX 或下載模型。

## 模型下載狀態

**目前狀態：尚未下載，也尚未取得使用者同意。**

本工具預設以 `HF_HUB_OFFLINE=1` 執行 MFLUX，只會使用本機已快取的模型，絕不會自動下載。

`--allow-download` 只能在以下兩個條件都成立後使用一次：
1. 使用者已確認模型來源、授權與下載大小（步驟見 README「首次下載模型」）。
2. 使用者明確同意下載。

下載成功後，把上面的狀態改為「已下載」。之後一律不加 `--allow-download`。

## 何時呼叫

使用者用自然語言要求一張圖時就呼叫，例如「生成一張微膠囊剖面概念圖」「做一張封面插圖」「畫一張製程示意圖」。

以下情況**不要**呼叫：
- 使用者要的是資料圖表。這類圖改用程式繪製，例如 matplotlib。
- 圖中需要精確的化學結構式、數據或大量文字標註。這種情況可以先用本工具生成底圖，再到 PPT 或 Word 裡加標註。

## 如何呼叫

從儲存庫根目錄執行：

```bash
local-image-gen/bin/imagegen generate --prompt "<英文提示詞>" -o local-image-gen/output/<簡短檔名>.png
```

- **提示詞用英文。** FLUX 對英文的理解最好。使用者用中文描述時，由 Claude 轉寫成具體的英文提示詞，內容包括主題、構圖、風格、背景，並加上 `no text`。
- **預設參數：** schnell 模型、quantize 4、512×512、steps 4。
- **seed：** 沒有指定 `--seed` 時，工具會隨機產生一個，並寫進紀錄。要重現同一張圖時，帶入紀錄中的 seed。
- **簡報用圖：** 加上 `--width 1024 --height 576`（16:9，寬高都要是 16 的倍數）。
- 尺寸較大時記憶體用量會增加。使用者的 Mac 有 24 GiB 統一記憶體，應先用小尺寸驗證，再逐步放大。
- 參數可用的值，以 `imagegen models` 的輸出為準。

### 讀取結果

stdout 最後一行是 JSON：
- 成功時：`{"status":"ok","image":...,"record":...,"seed":...}`。
- 失敗時：`{"status":"error","kind":...,"hint":...,"error_record":...}`。

| 結束碼 | kind | Claude 的處置 |
|---|---|---|
| 0 | — | 回報圖片路徑。可以用 Read 檢視圖片，確認內容符合要求 |
| 2 | invalid | 依訊息修正參數後重跑 |
| 3 | setup | 告知使用者找不到 MFLUX，或 `--help` 中缺少某個參數。不要自行改用其他參數名稱 |
| 4 | model_not_cached | 停止。說明模型還沒下載，依「模型下載狀態」一節取得使用者同意 |
| 5 | runtime | 讀取 error.json 中的 `stderr_tail` 診斷原因。不要改下載其他模型，也不要調整系統記憶體設定 |
| 6 | timeout | 建議降低尺寸或步數 |
| 7 | no_image | 回報問題，保留錯誤紀錄 |

本工具不會自動重試；要重跑，由 Claude 判斷原因後再執行。

## 生成後插入文件

輸出的圖片是 PNG 檔。插入文件時沿用既有工具：
- Word：docx skill。
- PDF：pdf skill。
- 簡報：本儲存庫的 pptx-from-layouts skill，或 pptx skill。

紀錄 JSON 和圖片放在同一個資料夾，可以作為圖片來源的追溯依據。

## 規則

- 不使用 sudo，不修改系統 Python，不安裝 ComfyUI 或其他外掛。
- 如果需要 Hugging Face 登入，由使用者自己執行 `hf auth login`。權杖不寫進程式碼、設定檔或對話。
- `output/` 已被 git 忽略。成品圖片要先徵得使用者同意，再複製到要用的位置。
- 不要修改 `imagegen.toml` 的模型清單。要新增模型時，先查官方授權，並和使用者確認。

## 開發

```bash
uv run --project local-image-gen pytest -q
```

測試全部離線執行，`mflux-generate` 以假物件取代，不會真的執行。
