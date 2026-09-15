from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class FrontendSettings:
    api_base_url: str = "http://127.0.0.1:8000/api/v1"
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 65.0
    write_timeout_seconds: float = 65.0

    @classmethod
    def from_environment(cls) -> FrontendSettings:
        raw_url = os.getenv("API_BASE_URL", cls.api_base_url).strip().rstrip("/")
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API_BASE_URL harus berupa URL HTTP(S) absolut")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API_BASE_URL tidak boleh memuat kredensial, query, atau fragment")
        return cls(api_base_url=raw_url)
