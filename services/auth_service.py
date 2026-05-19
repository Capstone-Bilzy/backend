import httpx
from fastapi import HTTPException
from core.database import supabase_admin
from core.security import create_access_token, create_refresh_token
from core.privacy import encrypt_user, decrypt_user, pseudonymize
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def get_kakao_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="카카오 토큰이 유효하지 않습니다")

    data = res.json()
    profile = data.get("kakao_account", {}).get("profile", {})
    return {
        "id": str(data["id"]),
        "nickname": profile.get("nickname", "사용자"),
        "profile_image_url": profile.get("profile_image_url", "")
    }


async def get_naver_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://openapi.naver.com/v1/nid/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="네이버 토큰이 유효하지 않습니다")

    data = res.json().get("response", {})
    return {
        "id": data["id"],
        "nickname": data.get("nickname", "사용자"),
        "profile_image_url": data.get("profile_image", "")
    }


async def social_login(provider: str, access_token: str) -> dict:
    # 1. 소셜 플랫폼에서 유저 정보 검증
    if provider == "kakao":
        user_info = await get_kakao_user_info(access_token)
    elif provider == "naver":
        user_info = await get_naver_user_info(access_token)
    else:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider")

    # 2. 개인정보 암호화 + provider_id 가명처리 후 DB upsert
    encrypted = encrypt_user({
        "provider_id": user_info["id"],
        "nickname": user_info["nickname"],
        "profile_image_url": user_info["profile_image_url"],
    })

    result = supabase_admin.table("users").upsert(
        {
            "provider": provider,
            "provider_id": encrypted["provider_id"],       # 가명처리된 값
            "nickname": encrypted["nickname"],             # AES-256 암호화
            "profile_image_url": encrypted["profile_image_url"],  # AES-256 암호화
            "last_login_at": datetime.utcnow().isoformat(),
        },
        on_conflict="provider,provider_id"
    ).execute()

    user = result.data[0]
    user_id = user["id"]

    # 3. 동의 이력 저장 (개인정보보호법 제22조)
    supabase_admin.table("consent_logs").upsert({
        "user_id": user_id,
        "consent_type": "privacy_policy",
        "agreed": True,
        "agreed_at": datetime.utcnow().isoformat(),
        "version": "1.0"
    }, on_conflict="user_id,consent_type").execute()

    # 4. JWT 발급
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)

    # 5. Refresh token DB 저장 (탈취 시 무효화 가능)
    supabase_admin.table("refresh_tokens").upsert(
        {"user_id": user_id, "token": refresh}
    ).execute()

    logger.info(f"SOCIAL_LOGIN provider={provider} user={user_id[:8]}***")

    # 6. 복호화해서 반환 (앱에는 평문으로)
    decrypted = decrypt_user(user)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": {
            "id": user_id,
            "nickname": decrypted["nickname"],
            "profile_image_url": decrypted["profile_image_url"]
        }
    }


async def refresh_token(refresh_token: str) -> dict:
    from core.security import decode_token

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="리프레시 토큰이 아닙니다")

    user_id = payload["sub"]

    # DB에 저장된 토큰과 일치하는지 확인 (탈취 방어)
    result = supabase_admin.table("refresh_tokens") \
        .select("*").eq("user_id", user_id).eq("token", refresh_token).execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    new_access = create_access_token(user_id)
    return {"access_token": new_access}


async def logout(user_id: str):
    # Refresh token 삭제
    supabase_admin.table("refresh_tokens").delete().eq("user_id", user_id).execute()
