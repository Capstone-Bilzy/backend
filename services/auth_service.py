import httpx
from fastapi import HTTPException
from core.database import supabase_admin
from core.security import create_access_token, create_refresh_token, invalidate_user_cache
from core.privacy import encrypt_user, decrypt_user, pseudonymize, encrypt
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
    # 닉네임/프로필 미동의 시 카카오는 해당 키를 아예 주지 않는다 → None 으로 둬서
    # "사용자" 폴백을 DB에 쓰지 않고, 기존에 받아둔 실명을 보존한다(social_login에서 조건부 갱신).
    return {
        "id": str(data["id"]),
        "nickname": profile.get("nickname") or None,
        # 카카오는 http://k.kakaocdn.net/... 로 내려주는데 Android는 평문(http) 이미지를 막는다 → https로 저장
        "profile_image_url": _to_https(profile.get("profile_image_url")) or None
    }


def _to_https(url):
    """http:// 로 시작하는 주소를 https:// 로 바꾼다(그 외·빈 값은 그대로)."""
    if isinstance(url, str) and url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


async def get_naver_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://openapi.naver.com/v1/nid/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="네이버 토큰이 유효하지 않습니다")

    data = res.json().get("response", {})
    # 네이버 "별명"(nickname)은 사용자가 따로 설정해야 하는 선택 프로필이라 비어있는 계정이 많다.
    # 콘솔에서 "이름" 제공 동의도 받았다면 실명(name)으로 대체해 "사용자" 폴백을 줄인다.
    return {
        "id": data["id"],
        "nickname": data.get("nickname") or data.get("name") or None,
        "profile_image_url": data.get("profile_image") or None
    }


async def is_registered(provider: str, access_token: str) -> dict:
    """소셜 토큰의 주인이 이미 가입한 회원인지 확인만 한다(계정을 만들거나 로그인시키지 않음).

    앱 회원가입 흐름에서 OAuth 직후 호출해, 이미 가입한 사람이면 약관 동의 화면을 건너뛰고
    바로 로그인시키는 데 쓴다. 유효한 소셜 토큰을 가진 본인만 자기 가입 여부를 알 수 있다.
    """
    if provider == "kakao":
        user_info = await get_kakao_user_info(access_token)
    elif provider == "naver":
        user_info = await get_naver_user_info(access_token)
    else:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider")

    existing = supabase_admin.table("users") \
        .select("id").eq("provider", provider).eq("provider_id", pseudonymize(user_info["id"])) \
        .execute()
    return {"registered": bool(existing.data)}


async def social_login(provider: str, access_token: str) -> dict:
    # 1. 소셜 플랫폼에서 유저 정보 검증
    if provider == "kakao":
        user_info = await get_kakao_user_info(access_token)
    elif provider == "naver":
        user_info = await get_naver_user_info(access_token)
    else:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider")

    # 2. DB upsert — provider_id 가명처리는 항상, 닉네임/프로필은 실제로 받아왔을 때만 갱신한다.
    #    (미동의 폴백으로 기존 실명을 덮어쓰지 않도록 — 한 번 받은 실명은 보존)
    provider_id_hash = pseudonymize(user_info["id"])

    # users.nickname은 not null 컬럼이라, 처음 로그인하는 유저가 닉네임 동의를 안 했으면
    # nickname 키가 아예 빠진 채 INSERT가 되어 not-null 제약 위반(500)이 난다.
    # → 신규 유저인지 먼저 확인해서, 신규인데 닉네임이 없으면 폴백 값을 채운다.
    existing = supabase_admin.table("users") \
        .select("id").eq("provider", provider).eq("provider_id", provider_id_hash) \
        .execute()
    is_new_user = not existing.data

    upsert_data = {
        "provider": provider,
        "provider_id": provider_id_hash,
        "last_login_at": datetime.utcnow().isoformat(),
    }
    if user_info.get("nickname"):
        upsert_data["nickname"] = encrypt(user_info["nickname"])          # AES-256 암호화
    elif is_new_user:
        upsert_data["nickname"] = encrypt("사용자")                        # 신규 유저 폴백 (not null 제약)
    if user_info.get("profile_image_url"):
        upsert_data["profile_image_url"] = encrypt(user_info["profile_image_url"])

    result = supabase_admin.table("users").upsert(
        upsert_data,
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
        {"user_id": user_id, "token": refresh},
        on_conflict="user_id"
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
    invalidate_user_cache(user_id)  # 인증 캐시(30초)에 남은 사용자 정보도 바로 지운다
