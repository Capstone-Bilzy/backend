from fastapi import HTTPException
from core.database import supabase_admin
import logging

logger = logging.getLogger(__name__)


def _check_owner(settlement_id: str, user_id: str):
    """정산방 소유자 확인 - IDOR 방어"""
    result = supabase_admin.table("settlements") \
        .select("*").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return result.data[0]


def _check_member(settlement_id: str, user_id: str):
    """정산방 참여자 확인"""
    result = supabase_admin.table("settlements") \
        .select("*").eq("id", settlement_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="정산방을 찾을 수 없습니다")

    settlement = result.data[0]
    # 방장이거나 참여자이면 OK
    if settlement["created_by"] == user_id:
        return settlement

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    return settlement


async def create_settlement(title: str, user_id: str) -> dict:
    result = supabase_admin.table("settlements").insert({
        "title": title,
        "created_by": user_id,
        "status": "scanning",
        "total_amount": 0
    }).execute()

    logger.info(f"SETTLEMENT_CREATED user={user_id[:8]}***")
    return result.data[0]


async def get_settlement(settlement_id: str, user_id: str) -> dict:
    settlement = _check_member(settlement_id, user_id)

    # 참여자 목록
    members = supabase_admin.table("settlement_members") \
        .select("*").eq("settlement_id", settlement_id).execute()

    # 영수증 항목
    items = supabase_admin.table("receipt_items") \
        .select("*").eq("settlement_id", settlement_id).execute()

    return {
        **settlement,
        "members": members.data,
        "items": items.data
    }


async def update_status(settlement_id: str, status: str, user_id: str) -> dict:
    _check_owner(settlement_id, user_id)

    result = supabase_admin.table("settlements") \
        .update({"status": status}).eq("id", settlement_id).execute()
    return result.data[0]


async def delete_settlement(settlement_id: str, user_id: str):
    _check_owner(settlement_id, user_id)

    # 연관 데이터 cascade 삭제 (Supabase FK cascade 설정 권장)
    supabase_admin.table("receipt_items").delete().eq("settlement_id", settlement_id).execute()
    supabase_admin.table("settlement_members").delete().eq("settlement_id", settlement_id).execute()
    supabase_admin.table("settlements").delete().eq("id", settlement_id).execute()

    logger.info(f"SETTLEMENT_DELETED id={settlement_id} user={user_id[:8]}***")


async def add_member(settlement_id: str, user_id: str, nickname: str, requester_id: str) -> dict:
    """방장이 참여자 추가하거나, 본인이 QR로 입장"""
    settlement = supabase_admin.table("settlements") \
        .select("*").eq("id", settlement_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=404, detail="정산방을 찾을 수 없습니다")

    # 중복 참여 방지
    existing = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 참여 중입니다")

    result = supabase_admin.table("settlement_members").insert({
        "settlement_id": settlement_id,
        "user_id": user_id,
        "nickname": nickname,
        "amount": 0
    }).execute()

    return result.data[0]


async def remove_member(settlement_id: str, member_user_id: str, requester_id: str):
    _check_owner(settlement_id, requester_id)

    supabase_admin.table("settlement_members") \
        .delete().eq("settlement_id", settlement_id).eq("user_id", member_user_id).execute()


async def mark_done(settlement_id: str, user_id: str) -> dict:
    _check_owner(settlement_id, user_id)

    result = supabase_admin.table("settlements") \
        .update({"status": "done"}).eq("id", settlement_id).execute()

    # 정산 내역에 기록
    settlement = result.data[0]
    members = supabase_admin.table("settlement_members") \
        .select("user_id").eq("settlement_id", settlement_id).execute()

    history_rows = [
        {"settlement_id": settlement_id, "user_id": m["user_id"]}
        for m in members.data
    ]
    history_rows.append({"settlement_id": settlement_id, "user_id": user_id})
    supabase_admin.table("history").upsert(history_rows, on_conflict="settlement_id,user_id").execute()

    return settlement
