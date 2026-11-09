"""Error taxonomy and exit codes.

Each provider maps its SDK exceptions onto one of these kinds. Only
``TRANSIENT`` is ever retried; everything else stops immediately. Billing and
quota problems are never retried and never trigger a switch to another model.
"""

from __future__ import annotations

import os
from enum import Enum


class Kind(str, Enum):
    TRANSIENT = "transient"   # connection error, timeout, 5xx, OpenAI rate limit
    BILLING = "billing"       # quota / credit / spend limit / billing not enabled
    AUTH = "auth"             # missing / invalid key, permission, org verification
    INVALID = "invalid"       # bad request, unknown model, unsupported parameter
    BLOCKED = "blocked"       # safety / moderation refusal, no image returned
    OTHER = "other"


EXIT_CODES = {
    Kind.INVALID: 2,
    Kind.BILLING: 3,
    Kind.AUTH: 4,
    Kind.BLOCKED: 5,
    Kind.TRANSIENT: 6,
    Kind.OTHER: 7,
}

HINTS = {
    Kind.BILLING: "額度不足或帳單問題：已立即停止，未重試，也未改用其他模型。請至供應商帳單後台確認後再執行。",
    Kind.AUTH: "金鑰缺漏、無效或權限不足：請確認環境變數已設定正確金鑰（本工具不會顯示金鑰內容）。",
    Kind.INVALID: "請求參數不被接受：請檢查模型名稱與圖片設定。",
    Kind.BLOCKED: "API 未回傳圖片（可能因安全政策攔截）：請調整提示詞。",
    Kind.TRANSIENT: "暫時性錯誤，已達重試上限。",
    Kind.OTHER: "未分類錯誤。",
}


class ImageGenError(Exception):
    def __init__(self, kind: Kind, message: str, *, status: int | None = None,
                 code: str | None = None, usage: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.code = code
        self.usage = usage
        self.retry_after: float | None = None

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.kind]


SECRET_ENV_VARS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def redact(text: str) -> str:
    """Remove any API key value that might appear in a message."""
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            text = text.replace(value, f"<{name} redacted>")
    return text
