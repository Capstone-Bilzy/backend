from fastapi import HTTPException, Request
from core.storage import remove_settlement_files, remove_receipt_file
from core.security import invalidate_user_cache
from core.database import supabase_admin
from core.privacy import encrypt, decrypt, decrypt_user
from core.access_logger import log_access
import logging

logger = logging.getLogger(__name__)

# 계산이 끝난 방에 남기는 탈퇴자 행의 표시 이름
WITHDRAWN_NICKNAME = "탈퇴한 사용자"


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

    settlements = supabase_admin.table("settlements") \
        .select("id").eq("created_by", user_id).execute()
    settlement_ids = [s["id"] for s in settlements.data or []]

    # 1. 영수증 이미지 삭제
    # receipt_image_url은 settlements가 아니라 다차 정산 재설계 이후 라운드별 receipts 테이블에 있음
    receipt_ids = []
    if settlement_ids:
        receipts = supabase_admin.table("receipts") \
            .select("id, receipt_image_url").in_("settlement_id", settlement_ids).execute()
        for r in receipts.data or []:
            receipt_ids.append(r["id"])

    # 정산방 폴더를 통째로 지운다(차수별 영수증 + 추가 첨부 사진). 예전엔 경로를 잘못 만들어 하나도 못 지웠고
    # 추가 첨부 사진은 아예 대상이 아니었다.
    for sid in settlement_ids:
        try:
            remove_settlement_files(sid)
        except Exception as e:
            logger.error(f"Account delete: files remove failed for settlement {sid}: {e}")

    # 2. 연관 데이터 삭제
    if receipt_ids:
        # receipt_items는 settlement_id가 아니라 receipt_id로 receipts를 참조함
        supabase_admin.table("receipt_items") \
            .delete().in_("receipt_id", receipt_ids).execute()
    if settlement_ids:
        supabase_admin.table("settlement_members") \
            .delete().in_("settlement_id", settlement_ids).execute()
        supabase_admin.table("settlements") \
            .delete().eq("created_by", user_id).execute()

    # 남의 방에 올린 첨부 사진: 행은 users 삭제 때 같이 지워지지만 파일은 따로 지워야 한다(예전엔 버킷에 남았다).
    my_photos = supabase_admin.table("settlement_extra_photos") \
        .select("id, image_url").eq("uploaded_by", user_id).execute()
    for p in my_photos.data or []:
        try:
            remove_receipt_file(p["image_url"])
        except Exception as e:
            logger.error(f"Account delete: extra photo remove failed {p['id']}: {e}")
    supabase_admin.table("settlement_extra_photos").delete().eq("uploaded_by", user_id).execute()

    # 남의 방 멤버 행: 계산이 시작된 방에서 행을 지우면 남은 사람들의 금액 합이 총액과 안 맞게 된다.
    # 그런 방에서는 금액은 두고 사람 정보(계정 연결·이름)만 지운다. 계산 전인 방에서는 행째 지운다.
    from services.settlement_service import LOCKED_STATUSES, _dedupe_nickname
    memberships = supabase_admin.table("settlement_members") \
        .select("id, settlement_id").eq("user_id", user_id).execute()
    joined_ids = [m["settlement_id"] for m in memberships.data or []]
    locked_ids = set()
    if joined_ids:
        rooms = supabase_admin.table("settlements").select("id, status").in_("id", joined_ids).execute()
        locked_ids = {r["id"] for r in rooms.data or [] if r["status"] in LOCKED_STATUSES}
    for m in memberships.data or []:
        if m["settlement_id"] in locked_ids:
            supabase_admin.table("settlement_members").update({
                "user_id": None,
                "nickname": _dedupe_nickname(m["settlement_id"], WITHDRAWN_NICKNAME, exclude_member_id=m["id"]),
            }).eq("id", m["id"]).execute()
    supabase_admin.table("settlement_members").delete().eq("user_id", user_id).execute()
    supabase_admin.table("history").delete().eq("user_id", user_id).execute()
    supabase_admin.table("refresh_tokens").delete().eq("user_id", user_id).execute()
    supabase_admin.table("consent_logs").delete().eq("user_id", user_id).execute()
    supabase_admin.table("access_logs").delete().eq("user_id", user_id).execute()

    # 3. 유저 삭제
    supabase_admin.table("users").delete().eq("id", user_id).execute()

    invalidate_user_cache(user_id)  # 탈퇴 직후에도 인증 캐시 때문에 요청이 통과하던 것 방지
    logger.info(f"ACCOUNT_DELETED user={user_id[:8]}*** - 개인정보 즉시 파기 완료")


async def get_history(user_id: str, request=None) -> list:
    await log_access(user_id, "READ", "history", None,
                     request.client.host if request else None)
    result = supabase_admin.table("history") \
        .select("*, settlements(id, title, total_amount, status, created_at, settlement_members(count))") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True, foreign_table="settlements") \
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

    # receipt_items는 settlement_id가 아니라 receipt_id로 receipts를 참조함
    receipt_ids = [r["id"] for r in supabase_admin.table("receipts")
                   .select("id").eq("settlement_id", settlement_id).execute().data]
    items = supabase_admin.table("receipt_items") \
        .select("*").in_("receipt_id", receipt_ids).execute() if receipt_ids else None

    return {
        **settlement.data,
        "members": members.data,
        "items": items.data if items else []
    }
