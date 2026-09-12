from fastapi import HTTPException
from core.database import supabase_admin
from core.storage import signed_receipt_url
from core.privacy import decrypt
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


def _load_receipts_with_items(settlement_id: str) -> list:
    """정산방의 라운드(receipts)별 항목·signed 이미지 URL을 round 순으로 정리해 반환한다."""
    receipts = supabase_admin.table("receipts") \
        .select("*").eq("settlement_id", settlement_id).order("round").execute()
    if not receipts.data:
        return []

    receipt_ids = [r["id"] for r in receipts.data]
    items = supabase_admin.table("receipt_items") \
        .select("*").in_("receipt_id", receipt_ids).execute()
    items_by_receipt: dict = {}
    for item in items.data:
        items_by_receipt.setdefault(item["receipt_id"], []).append(item)

    result = []
    for r in receipts.data:
        raw_path = r.get("receipt_image_url")
        signed = signed_receipt_url(raw_path)
        if raw_path and not signed:
            logger.warning(f"receipt signed url 생성 실패: receipt={r['id']} raw_path={raw_path!r}")
        result.append({
            **r,
            "receipt_image_url": signed,
            "items": items_by_receipt.get(r["id"], []),
        })
    return result


def _load_member_rounds(member_ids: list) -> dict:
    """멤버 id → 라운드별 참여/조정/금액 목록."""
    if not member_ids:
        return {}
    rows = supabase_admin.table("settlement_member_rounds") \
        .select("*").in_("settlement_member_id", member_ids).order("round").execute()
    by_member: dict = {}
    for row in rows.data:
        by_member.setdefault(row["settlement_member_id"], []).append(row)
    return by_member


async def get_settlement(settlement_id: str, user_id: str) -> dict:
    settlement = _check_member(settlement_id, user_id)

    # 참여자 목록
    members = supabase_admin.table("settlement_members") \
        .select("*").eq("settlement_id", settlement_id).execute()

    # 참여자 프로필 이미지 - users 테이블과 조인 (N+1 방지 위해 in_ 필터로 한 번에 조회)
    user_ids = list({m["user_id"] for m in members.data})
    users_result = supabase_admin.table("users") \
        .select("id, profile_image_url").in_("id", user_ids).execute() if user_ids else None
    image_by_user = {
        u["id"]: decrypt(u["profile_image_url"]) if u.get("profile_image_url") else None
        for u in (users_result.data if users_result else [])
    }
    rounds_by_member = _load_member_rounds([m["id"] for m in members.data])
    members_with_image = [
        {
            **m,
            "profile_image_url": image_by_user.get(m["user_id"]),
            "rounds": rounds_by_member.get(m["id"], []),
        }
        for m in members.data
    ]

    # 라운드(영수증)별 상세 — 다차 정산의 실제 데이터
    receipts = _load_receipts_with_items(settlement_id)

    # 하위 호환: 아직 라운드 개념을 안 쓰는 화면(History 등)을 위해 전체 라운드를 합친
    # 평면 items와 첫 라운드 이미지를 계속 내려준다.
    flat_items = [item for r in receipts for item in r["items"]]
    first_receipt_image = receipts[0]["receipt_image_url"] if receipts else None

    return {
        **settlement,
        "receipt_image_url": first_receipt_image,
        "members": members_with_image,
        "items": flat_items,
        "receipts": receipts,
    }


async def update_status(settlement_id: str, status: str, user_id: str) -> dict:
    _check_owner(settlement_id, user_id)

    result = supabase_admin.table("settlements") \
        .update({"status": status}).eq("id", settlement_id).execute()
    return result.data[0]


async def update_settlement(settlement_id: str, title: str, user_id: str) -> dict:
    _check_owner(settlement_id, user_id)

    result = supabase_admin.table("settlements") \
        .update({"title": title}).eq("id", settlement_id).execute()
    return result.data[0]


async def delete_settlement(settlement_id: str, user_id: str):
    _check_owner(settlement_id, user_id)

    # 연관 데이터 cascade 삭제 (Supabase FK cascade 설정 권장)
    receipt_ids = [r["id"] for r in supabase_admin.table("receipts")
                   .select("id").eq("settlement_id", settlement_id).execute().data]
    if receipt_ids:
        supabase_admin.table("receipt_items").delete().in_("receipt_id", receipt_ids).execute()
    supabase_admin.table("receipts").delete().eq("settlement_id", settlement_id).execute()

    member_ids = [m["id"] for m in supabase_admin.table("settlement_members")
                  .select("id").eq("settlement_id", settlement_id).execute().data]
    if member_ids:
        supabase_admin.table("settlement_member_rounds").delete().in_("settlement_member_id", member_ids).execute()
    supabase_admin.table("settlement_members").delete().eq("settlement_id", settlement_id).execute()
    supabase_admin.table("settlements").delete().eq("id", settlement_id).execute()

    logger.info(f"SETTLEMENT_DELETED id={settlement_id} user={user_id[:8]}***")


async def delete_receipt_image(settlement_id: str, round: int, user_id: str):
    """정산건의 특정 라운드에 붙은 영수증 이미지 삭제 (앱에서 '저장 안 함'/'다시 찍기' 선택 시).

    Storage 객체를 제거하고 해당 라운드 receipts.receipt_image_url을 null로 비운다. 소유자만 가능.
    이미지가 없으면(또는 라운드가 아직 없으면) 멱등하게 통과한다.
    """
    _check_owner(settlement_id, user_id)

    receipt = supabase_admin.table("receipts") \
        .select("*").eq("settlement_id", settlement_id).eq("round", round).execute()
    if not receipt.data:
        return
    path = receipt.data[0].get("receipt_image_url")
    if path:
        try:
            # receipt_image_url은 버킷 내 경로(receipts/{id}/{round}/{uuid}.jpg). split은 풀 URL 형태도 방어.
            key = path.split("/receipts/")[-1]
            supabase_admin.storage.from_("receipts").remove([f"receipts/{key}"])
        except Exception as e:
            logger.error(f"Receipt image remove failed for {settlement_id} round={round}: {e}")

        supabase_admin.table("receipts") \
            .update({"receipt_image_url": None}).eq("id", receipt.data[0]["id"]).execute()

    logger.info(f"RECEIPT_IMAGE_DELETED settlement={settlement_id} round={round} user={user_id[:8]}***")


async def set_member_rounds(settlement_id: str, user_id: str, rounds: list) -> dict:
    """참여자 본인이 참여한 라운드 집합을 지정한다(RoundPick 화면). 없으면 insert, 빠지면 delete."""
    _check_member(settlement_id, user_id)

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="이 정산방의 참여자가 아닙니다")
    member_id = member.data[0]["id"]

    wanted = {int(r) for r in rounds}
    existing = supabase_admin.table("settlement_member_rounds") \
        .select("round").eq("settlement_member_id", member_id).execute()
    have = {row["round"] for row in existing.data}

    to_add = wanted - have
    to_remove = have - wanted

    if to_add:
        supabase_admin.table("settlement_member_rounds").insert([
            {"settlement_member_id": member_id, "round": r} for r in to_add
        ]).execute()
    for r in to_remove:
        supabase_admin.table("settlement_member_rounds") \
            .delete().eq("settlement_member_id", member_id).eq("round", r).execute()

    result = supabase_admin.table("settlement_member_rounds") \
        .select("*").eq("settlement_member_id", member_id).order("round").execute()
    return {"member_id": member_id, "rounds": result.data}


async def set_member_round_adjustment(settlement_id: str, user_id: str, round: int, excluded_item_names: list) -> dict:
    """참여자 본인이 특정 라운드에서 안 먹은 항목을 지정한다(AmountAdjust 화면)."""
    _check_member(settlement_id, user_id)

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="이 정산방의 참여자가 아닙니다")
    member_id = member.data[0]["id"]

    names = [str(n)[:50] for n in excluded_item_names][:100]

    existing = supabase_admin.table("settlement_member_rounds") \
        .select("id").eq("settlement_member_id", member_id).eq("round", round).execute()
    if existing.data:
        result = supabase_admin.table("settlement_member_rounds") \
            .update({"excluded_item_names": names}).eq("id", existing.data[0]["id"]).execute()
    else:
        result = supabase_admin.table("settlement_member_rounds").insert({
            "settlement_member_id": member_id,
            "round": round,
            "excluded_item_names": names,
        }).execute()
    return result.data[0]


async def set_member_ready(settlement_id: str, user_id: str) -> dict:
    """참여자 본인이 라운드 조정을 다 마치고 "정산 시작하기"를 눌렀음을 표시한다(CalculatingFragment 실시간 표시용)."""
    _check_member(settlement_id, user_id)

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="이 정산방의 참여자가 아닙니다")

    result = supabase_admin.table("settlement_members") \
        .update({"ready": True}).eq("id", member.data[0]["id"]).execute()
    return result.data[0]


def _dedupe_nickname(settlement_id: str, nickname: str) -> str:
    """같은 정산방 안에서 닉네임이 겹치면 AI 정산이 닉네임으로 사람을 구분하지 못해
    한 명의 몫이 다른 동명이인에게 덮어써질 수 있다(계산 무결성 문제) — 겹치면 자동으로 구분자를 붙인다."""
    base = nickname.strip() or "참여자"
    existing = supabase_admin.table("settlement_members") \
        .select("nickname").eq("settlement_id", settlement_id).execute()
    taken = {m["nickname"].strip().casefold() for m in existing.data}
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base}({n})".casefold() in taken:
        n += 1
    return f"{base}({n})"


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
        "nickname": _dedupe_nickname(settlement_id, nickname),
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

    if not result.data:
        raise HTTPException(status_code=500, detail="정산 완료 처리에 실패했습니다")

    settlement = result.data[0]

    # 정산 내역에 기록 — 멤버 + 방장을 중복 없이 upsert
    members = supabase_admin.table("settlement_members") \
        .select("user_id").eq("settlement_id", settlement_id).execute()

    seen = set()
    history_rows = []
    for m in members.data:
        uid = m["user_id"]
        if uid not in seen:
            seen.add(uid)
            history_rows.append({"settlement_id": settlement_id, "user_id": uid})

    # 방장이 settlement_members에 없는 경우를 대비해 명시적으로 추가
    if user_id not in seen:
        history_rows.append({"settlement_id": settlement_id, "user_id": user_id})

    if history_rows:
        supabase_admin.table("history").upsert(history_rows, on_conflict="settlement_id,user_id").execute()

    return settlement
