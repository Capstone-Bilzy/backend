from fastapi import APIRouter, Request
from models.schemas import SocialLoginRequest, RefreshRequest
from services import auth_service
from core.security import get_current_user
from core.security_logger import log_security_event
from core.limiter import limiter
from fastapi import Depends

router = APIRouter(prefix="/auth", tags=["인증"])


@router.post("/social")
@limiter.limit("10/minute")
async def social_login(body: SocialLoginRequest, request: Request):
    result = await auth_service.social_login(body.provider, body.access_token)
    await log_security_event("LOGIN_SUCCESS", request.client.host, result["user"]["id"])
    return result


@router.post("/refresh")
@limiter.limit("20/minute")
async def refresh(body: RefreshRequest, request: Request):
    return await auth_service.refresh_token(body.refresh_token)


@router.delete("/logout")
async def logout(current_user=Depends(get_current_user)):
    await auth_service.logout(current_user["id"])
    return {"message": "로그아웃 완료"}
