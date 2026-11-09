"""Error kinds and exit codes. Local generation is never retried: a failure
here is a setup, cache, memory or input problem, not a transient one."""

from __future__ import annotations

from enum import Enum


class Kind(str, Enum):
    INVALID = "invalid"                   # bad input / config
    SETUP = "setup"                       # mflux-generate missing, or --help lacks a flag we use
    MODEL_NOT_CACHED = "model_not_cached" # offline mode and the model is not downloaded yet
    RUNTIME = "runtime"                   # mflux exited non-zero (e.g. out of memory)
    TIMEOUT = "timeout"
    NO_IMAGE = "no_image"                 # mflux exited 0 but no valid image was produced


EXIT_CODES = {
    Kind.INVALID: 2,
    Kind.SETUP: 3,
    Kind.MODEL_NOT_CACHED: 4,
    Kind.RUNTIME: 5,
    Kind.TIMEOUT: 6,
    Kind.NO_IMAGE: 7,
}

HINTS = {
    Kind.INVALID: "請檢查參數（imagegen models 可查可用值）。",
    Kind.SETUP: "找不到 mflux-generate，或目前版本的參數與預期不同。執行 imagegen check 查看細節；不要自行改用其他參數名稱。",
    Kind.MODEL_NOT_CACHED: "模型尚未下載到本機（目前為離線模式，不會自動下載）。請先依 README「首次下載模型」確認來源、授權與大小，經使用者同意後才加 --allow-download。",
    Kind.RUNTIME: "MFLUX 執行失敗。請看 error.json 中的 stderr_tail 診斷原因；不要自行改下載其他模型，也不要調整系統記憶體設定。",
    Kind.TIMEOUT: "生成逾時。可先降低解析度或步數再試。",
    Kind.NO_IMAGE: "MFLUX 結束但沒有產生可開啟的圖片。",
}


class ImageGenError(Exception):
    def __init__(self, kind: Kind, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail or {}

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.kind]
