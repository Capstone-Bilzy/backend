from fastapi import HTTPException, Request
from core.database import supabase_admin
from core.privacy import encrypt, decrypt, decrypt_user
from core.access_logger import log_access
import logging

logger = logging.getLogger(__name__)


async def get_profile(user_id: str, request: Request = None) -> dict:
    result = supabase_admin.table("users").select("id, nickname, profile_image_url, provider, created_at") \
        .eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")

    # 접근 로그 기록
    ip = request.client.host if request else None
    await log_access(user_id, "READ", "users", user_id, ip)

    # 복호화 후 반환
    return decrypt_user(result.data)


async def update_profile(user_id: str, nickname: str, request: Request = None) -> dict:
    # 닉네임 암호화 후 저장
    encrypted_nickname = encrypt(nickname)
    result = supabase_admin.table("users") \
        .update({"nickname": encrypted_nickname}).eq("id", user_id).execute()

    ip = request.client.host if request else None
    await log_access(user_id, "UPDATE", "users", user_id, ip)

    row = result.data[0]
    return {**row, "nickname": nickname}  # 복호화된 값 반환


async def delete_account(user_id: str):
    """회원탈퇴 - 개인정보보호법 제21조: 즉시 파기"""

    # 1. 영수증 이미지 삭제
    settlements = supabase_admin.table("settlements") \
        .select("id, receipt_image_url").eq("created_by", user_id).execute()

    for s in settlements.data or []:
        if s.get("receipt_image_url"):
            try:
                path = s["receipt_image_url"].split("/receipts/")[-1]
                supabase_admin.storage.from_("receipts").remove([f"receipts/{path}"])
            except Exception:
                pass

    # 2. 연관 데이터 삭제
    settlement_ids = [s["id"] for s in settlements.data or []]
    if settlement_ids:
        supabase_admin.table("receipt_items") \
            .delete().in_("settlement_id", settlement_ids).execute()
        supabase_admin.table("settlement_members") \
            .delete().in_("settlement_id", settlement_ids).execute()
        supabase_admin.table("settlements") \
            .delete().eq("created_by", user_id).execute()

    supabase_admin.table("settlement_members").delete().eq("user_id", user_id).execute()
    supabase_admin.table("history").delete().eq("user_id", user_id).execute()
    supabase_admin.table("refresh_tokens").delete().eq("user_id", user_id).execute()
    supabase_admin.table("consent_logs").delete().eq("user_id", user_id).execute()
    supabase_admin.table("access_logs").delete().eq("user_id", user_id).execute()

    # 3. 유저 삭제
    supabase_admin.table("users").delete().eq("id", user_id).execute()

    logger.info(f"ACCOUNT_DELETED user={user_id[:8]}*** - 개인정보 즉시 파기 완료")


async def get_history(user_id: str, request=None) -> list:
    await log_access(user_id, "READ", "history", None,
                     request.client.host if request else None)
    result = supabase_admin.table("history") \
        .select("*, settlements(id, title, total_amount, status, created_at, settlement_members(count))") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()

    # settlement_members(count) → member_count 평탄화
    for row in result.data:
        s = row.get("settlements")
        if s:
            members = s.pop("settlement_members", None)
            count = 0
            if isinstance(members, list) and members:
                count = members[0].get("count", 0)
            elif isinstance(members, dict):
                count = members.get("count", 0)
            s["member_count"] = count
    return result.data


async def get_history_detail(settlement_id: str, user_id: str, request=None) -> dict:
    # 본인 내역만 조회
    history = supabase_admin.table("history") \
        .select("*").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not history.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    await log_access(user_id, "READ", "settlements", settlement_id,
                     request.client.host if request else None)

    settlement = supabase_admin.table("settlements") \
        .select("*").eq("id", settlement_id).single().execute()

    members = supabase_admin.table("settlement_members") \
        .select("*").eq("settlement_id", settlement_id).execute()

    items = supabase_admin.table("receipt_items") \
        .select("*").eq("settlement_id", settlement_id).execute()

    return {
        **settlement.data,
        "members": members.data,
        "items": items.data
    }
