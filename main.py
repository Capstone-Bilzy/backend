from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from core.limiter import limiter
from core.config import settings
from routers import auth, ocr, settlements, users
from routers import account_router, receipts_router  # ← 한 줄로 합치기
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = FastAPI(
    title="Bilzy API",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["bilzy://"] if not settings.DEBUG else ["*"],
    # 모바일 클라이언트는 Authorization(Bearer) 헤더로 인증 — 쿠키 자격증명 불필요.
    # credentials=False면 와일드카드 origin과 함께여도 크리덴셜 교차출처 읽기 위험이 없다.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(ocr.router)
app.include_router(settlements.router)
app.include_router(users.router)
app.include_router(account_router.router)  # ← 추가
app.include_router(receipts_router.router)  # ← 추가


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    ip = request.client.host
    ip_masked = ".".join(ip.split(".")[:3]) + ".***"
    logging.getLogger("request").info(f"{request.method} {path} from {ip_masked}")
    return await call_next(request)