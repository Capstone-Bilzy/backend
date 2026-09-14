import asyncio
import time
from datetime import datetime, timedelta
from jose import ExpiredSignatureError, JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.config import settings
from core.database import supabase_admin
import logging

logger = logging.getLogger(__name__)
bearer = HTTPBearer()

# 인증 유저 레코드 단기 캐시(user_id -> (record, expires_at)).
# 모든 인증 요청이 users 테이블을 왕복하던 비용을 제거한다.
# 표시용 프로필은 /users/me가 별도 조회하므로 이 캐시의 영향을 받지 않는다.
_user_cache: dict = {}
_USER_CACHE_TTL = 30  # 초


def invalidate_user_cache(user_id: str = None):
    """유저 캐시 무효화. user_id 미지정 시 전체 비움."""
    if user_id is None:
        _user_cache.clear()
    else:
        _user_cache.pop(user_id, None)


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )


def create_invite_token(settlement_id: str, ttl_hours: int = 24, epoch: int = 1) -> tuple[str, datetime]:
    expire = datetime.utcnow() + timedelta(hours=ttl_hours)
    token = jwt.encode(
        {"sid": settlement_id, "type": "invite", "epoch": epoch, "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )
    return token, expire


def decode_invite_token(token: str) -> dict:
    # 초대 토큰 검증 실패는 로그인 인증 문제가 아니라 비즈니스 검증 실패라서 403을 쓴다.
    # 401로 내려가면 Android OkHttp Authenticator가 모든 401에 반응해 불필요한
    # refresh 재시도/로그아웃을 유발한다(진짜 인증 실패인 get_current_user의 401과는 구분).
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "INVITE_TOKEN_EXPIRED", "message": "초대 링크가 만료됐어요"}
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "INVITE_TOKEN_INVALID", "message": "유효하지 않은 초대 링크예요"}
        )

    if payload.get("type") != "invite":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "INVITE_TOKEN_INVALID", "message": "유효하지 않은 초대 링크예요"}
        )

    return payload


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다"
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="액세스 토큰이 아닙니다")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

    # 보안 로그: 요청 기록
    logger.info(f"AUTH user={user_id[:8]}***")

    # 단기 캐시 히트면 users 테이블 왕복을 건너뛴다.
    now = time.monotonic()
    cached = _user_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]

    # 동기 supabase 클라이언트가 이벤트 루프를 막지 않도록 스레드에서 실행.
    result = await asyncio.to_thread(
        lambda: supabase_admin.table("users").select("*").eq("id", user_id).single().execute()
    )
    if not result.data:
        raise HTTPException(status_code=401, detail="유저를 찾을 수 없습니다")

    _user_cache[user_id] = (result.data, now + _USER_CACHE_TTL)
    return result.data
