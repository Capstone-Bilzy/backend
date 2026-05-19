from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from core.config import settings
from routers import auth, ocr, settlements, users
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# Rate Limiter 설정
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Bilzy API",
    version="1.0.0",
    # 운영 환경에서는 Swagger 비노출 (보안)
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - 앱에서만 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["bilzy://"] if not settings.DEBUG else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(ocr.router)
app.include_router(settlements.router)
app.include_router(users.router)


@app.get("/health", include_in_schema=False)
async def health():
    """Render 슬립 방지용 헬스체크"""
    return {"status": "ok"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """요청 로깅 - 개인정보 마스킹"""
    path = request.url.path
    ip = request.client.host
    # IP 마스킹 (마지막 옥텟 숨김)
    ip_masked = ".".join(ip.split(".")[:3]) + ".***"
    logging.getLogger("request").info(f"{request.method} {path} from {ip_masked}")
    return await call_next(request)
