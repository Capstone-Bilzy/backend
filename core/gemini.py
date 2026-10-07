"""
Gemini 호출 공통 모듈 — 모델 여러 개를 순서대로 시도한다.

한 모델이 일시 과부하(503 UNAVAILABLE)·한도 초과(429 RESOURCE_EXHAUSTED)·사용 불가(404)면 설정된 다음 모델로
넘어간다. 그 밖의 오류(잘못된 요청 등)는 다른 모델로 바꿔도 같으므로 바로 올린다.
"""

import logging
import time

from google import genai
from google.genai import types

from core.config import settings

logger = logging.getLogger(__name__)

# 모델 하나당 기다리는 최대 시간(ms). 과부하일 때 응답이 한참 뒤에야 오는 경우가 있어, 끊고 다음 모델로 넘어간다.
_PER_MODEL_TIMEOUT_MS = 25_000
# 모든 모델을 합쳐 기다리는 최대 시간(초). 앱의 요청 제한(120초)보다 충분히 짧게 잡아, 다 실패해도
# 사용자가 제때 "다시 촬영/직접 입력" 화면을 보게 한다.
_TOTAL_BUDGET_SEC = 60

_client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=_PER_MODEL_TIMEOUT_MS),
)

_RETRYABLE = ("UNAVAILABLE", "503", "RESOURCE_EXHAUSTED", "429", "NOT_FOUND", "404", "DEADLINE_EXCEEDED", "504",
              "timed out", "Timeout", "timeout")


def model_names() -> list:
    return [m.strip() for m in settings.GEMINI_MODELS.split(",") if m.strip()]


def generate(contents, config=None):
    """동기 호출(호출 측에서 asyncio.to_thread로 감싼다). 성공한 첫 모델의 응답을 돌려준다."""
    last_error = None
    started = time.monotonic()
    for name in model_names():
        if last_error is not None and time.monotonic() - started > _TOTAL_BUDGET_SEC:
            break
        try:
            return _client.models.generate_content(model=name, contents=contents, config=config)
        except Exception as e:
            last_error = e
            if not any(marker in str(e) for marker in _RETRYABLE):
                raise
            logger.warning(f"Gemini model {name} unavailable, trying next: {str(e)[:120]}")
    raise last_error or RuntimeError("no Gemini model configured")
