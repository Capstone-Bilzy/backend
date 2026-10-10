from fastapi import HTTPException
from core.database import supabase_admin
from core.storage import signed_receipt_url, remove_settlement_files, remove_receipt_file
from core.privacy import decrypt
from core.access_logger import log_access
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

    # 참여자 목록 — 입장 순서로 고정(정산 계산 ai_service와 같은 순서여야 앱 미리보기의 1원 배정이 결과와 같다)
    members = supabase_admin.table("settlement_members") \
        .select("*").eq("settlement_id", settlement_id).order("joined_at").order("id").execute()

    # 참여자 프로필 이미지 - users 테이블과 조인 (N+1 방지 위해 in_ 필터로 한 번에 조회)
    # 탈퇴한 사람의 행은 user_id가 비어 있다(계산이 끝난 방에서는 금액을 지키려고 행을 남긴다)
    user_ids = list({m["user_id"] for m in members.data if m["user_id"]})
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

    # 순수 기록용 첨부 사진 — 라운드/정산 계산과 무관(attach-photo로 추가된 것)
    extra_photos_result = supabase_admin.table("settlement_extra_photos") \
        .select("*").eq("settlement_id", settlement_id) \
        .order("created_at", desc=False).execute()
    # name 컬럼은 schema_extra_photo_name.sql 적용 전 DB에는 없을 수 있어 get으로 읽는다
    extra_photos = [
        {
            "id": p["id"],
            "name": p.get("name"),
            "uploaded_by": p.get("uploaded_by"),
            "image_url": signed_receipt_url(p["image_url"]),
            "created_at": p["created_at"],
        }
        for p in extra_photos_result.data
    ]

    return {
        **settlement,
        "receipt_image_url": first_receipt_image,
        "members": members_with_image,
        "items": flat_items,
        "receipts": receipts,
        "extra_photos": extra_photos,
        "payer_account": await _payer_account(settlement, user_id),
    }


async def rename_extra_photo(settlement_id: str, photo_id: str, name: str, user_id: str) -> dict:
    """첨부한 영수증 사진의 이름 변경 — 방장이거나 그 사진을 올린 사람만. 정산 계산과 무관해 완료된 방에서도 된다."""
    settlement = _check_member(settlement_id, user_id)
    # settlement_id까지 같이 걸어 다른 정산방의 사진 id로는 바꿀 수 없게 한다
    photo = supabase_admin.table("settlement_extra_photos") \
        .select("id, uploaded_by").eq("id", photo_id).eq("settlement_id", settlement_id).execute()
    if not photo.data:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")
    if settlement["created_by"] != user_id and photo.data[0].get("uploaded_by") != user_id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    supabase_admin.table("settlement_extra_photos") \
        .update({"name": name}).eq("id", photo_id).eq("settlement_id", settlement_id).execute()
    return {"id": photo_id, "name": name}


async def _payer_account(settlement: dict, requester_id: str) -> dict | None:
    """결제자(방장)의 송금 계좌 — 참여자가 돈을 보낼 곳.

    이 정산방 멤버에게만(get_settlement의 _check_member 통과 후), 그리고 금액이 확정된 뒤
    (calculated/done)에만 내려준다. 그 전에는 보낼 금액이 없으므로 계좌번호를 노출하지 않는다.
    방장이 계좌를 등록하지 않았으면 None.
    """
    if settlement.get("status") not in ("calculated", "done"):
        return None
    owner_id = settlement["created_by"]
    owner = supabase_admin.table("users") \
        .select("bank_name, account_number, account_holder").eq("id", owner_id).execute()
    if not owner.data:
        return None
    row = owner.data[0]
    number = decrypt(row["account_number"]) if row.get("account_number") else ""
    if not number:
        return None
    if requester_id != owner_id:
        await log_access(requester_id, "READ", "account", owner_id)
    return {
        "bank_name": row.get("bank_name") or "",
        "account_number": number,
        "account_holder": row.get("account_holder") or "",
    }


# 계산이 시작된 뒤(calculating/calculated/done)에는 영수증·참여 차수·정원처럼 금액에 영향을 주는 값을 못 바꾼다.
LOCKED_STATUSES = ("calculating", "calculated", "done")


def ensure_not_locked(settlement: dict):
    if settlement.get("status") in LOCKED_STATUSES:
        raise HTTPException(status_code=400, detail="정산 계산이 시작된 뒤에는 수정할 수 없습니다")


async def update_status(settlement_id: str, status: str, user_id: str) -> dict:
    settlement = _check_owner(settlement_id, user_id)

    # 이 엔드포인트로는 스캔 단계(scanning ↔ waiting)만 오갈 수 있다. calculating/calculated는 계산(/calculate)이,
    # done은 /done이 정한다 — 예전엔 아무 상태로나 바꿀 수 있어 계산 없이 완료하거나 완료된 방을 되돌릴 수 있었다.
    status = getattr(status, "value", status)
    if status not in ("scanning", "waiting") or settlement.get("status") not in ("scanning", "waiting"):
        raise HTTPException(status_code=400, detail="변경할 수 없는 정산 상태입니다")

    result = supabase_admin.table("settlements") \
        .update({"status": status}).eq("id", settlement_id).execute()
    return result.data[0]


async def update_settlement(settlement_id: str, title: str, user_id: str) -> dict:
    _check_owner(settlement_id, user_id)

    result = supabase_admin.table("settlements") \
        .update({"title": title}).eq("id", settlement_id).execute()
    return result.data[0]


async def set_member_capacity(settlement_id: str, member_capacity: int, user_id: str) -> dict:
    """방장이 정원(총 인원)을 설정 — 이후 join이 이 값을 초과하지 못하게 막는다(add_member)."""
    ensure_not_locked(_check_owner(settlement_id, user_id))

    # 이미 들어와 있는 인원보다 적게는 못 줄인다(정원 2명인 방에 3명이 있는 상태가 생기지 않게).
    # 방장은 초대 화면에서 입장하기 전까지 멤버가 아니므로, 아직 안 들어왔으면 방장 자리 1개를 더 센다
    # (안 그러면 참여자 2명 + 정원 2로 줄인 뒤 방장이 들어와 3명이 된다).
    joined = supabase_admin.table("settlement_members") \
        .select("user_id").eq("settlement_id", settlement_id).execute().data
    taken = len(joined) + (0 if any(m["user_id"] == user_id for m in joined) else 1)
    if taken > member_capacity:
        raise HTTPException(status_code=400, detail=f"이미 {taken}명이 참여 중이에요")

    result = supabase_admin.table("settlements") \
        .update({"member_capacity": member_capacity}).eq("id", settlement_id).execute()
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
    supabase_admin.table("settlement_extra_photos").delete().eq("settlement_id", settlement_id).execute()
    supabase_admin.table("settlements").delete().eq("id", settlement_id).execute()

    # 스토리지에 올라간 영수증 이미지도 함께 지운다(예전엔 DB 행만 지워 이미지가 버킷에 남았다).
    removed = 0
    try:
        removed = remove_settlement_files(settlement_id)
    except Exception as e:
        logger.error(f"Settlement files remove failed for {settlement_id}: {e}")

    logger.info(f"SETTLEMENT_DELETED id={settlement_id} files={removed} user={user_id[:8]}***")


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
            remove_receipt_file(path)
        except Exception as e:
            logger.error(f"Receipt image remove failed for {settlement_id} round={round}: {e}")

        supabase_admin.table("receipts") \
            .update({"receipt_image_url": None}).eq("id", receipt.data[0]["id"]).execute()

    logger.info(f"RECEIPT_IMAGE_DELETED settlement={settlement_id} round={round} user={user_id[:8]}***")


async def delete_round(settlement_id: str, round: int, user_id: str) -> dict:
    """정산방의 특정 차수(라운드)를 통째로 삭제하고 뒤 차수 번호를 한 칸씩 당긴다(1·2·3차 중 2차 삭제 → 1·2차).

    소유자만 가능. 계산이 시작된 뒤(calculating/calculated/done)에는 금액이 이미 확정돼 있어 거부한다.
    영수증 항목(receipt_items)은 receipts FK cascade로 함께 지워지고, 참여자별 라운드 기록
    (settlement_member_rounds)은 삭제된 차수는 지우고 뒤 차수는 번호를 당긴다.
    Supabase 클라이언트로는 트랜잭션을 못 묶으므로, unique(settlement_id, round)/(member, round)에 걸리지 않게
    낮은 번호부터 차례로 당긴다.
    """
    settlement = _check_owner(settlement_id, user_id)
    if settlement.get("status") in ("calculating", "calculated", "done"):
        raise HTTPException(status_code=400, detail="정산 계산이 시작된 뒤에는 영수증을 삭제할 수 없습니다")

    receipts = supabase_admin.table("receipts") \
        .select("id, round, receipt_image_url").eq("settlement_id", settlement_id).execute().data
    target = next((r for r in receipts if r["round"] == round), None)
    if not target:
        raise HTTPException(status_code=404, detail="해당 차수의 영수증이 없습니다")

    path = target.get("receipt_image_url")
    if path:
        try:
            remove_receipt_file(path)
        except Exception as e:
            logger.error(f"Receipt image remove failed for {settlement_id} round={round}: {e}")

    supabase_admin.table("receipt_items").delete().eq("receipt_id", target["id"]).execute()
    supabase_admin.table("receipts").delete().eq("id", target["id"]).execute()

    member_ids = [m["id"] for m in supabase_admin.table("settlement_members")
                  .select("id").eq("settlement_id", settlement_id).execute().data]
    if member_ids:
        supabase_admin.table("settlement_member_rounds").delete() \
            .in_("settlement_member_id", member_ids).eq("round", round).execute()

    later_rounds = sorted(r["round"] for r in receipts if r["round"] > round)
    for r in later_rounds:
        supabase_admin.table("receipts").update({"round": r - 1}) \
            .eq("settlement_id", settlement_id).eq("round", r).execute()
        if member_ids:
            supabase_admin.table("settlement_member_rounds").update({"round": r - 1}) \
                .in_("settlement_member_id", member_ids).eq("round", r).execute()

    remaining = supabase_admin.table("receipts") \
        .select("total_amount").eq("settlement_id", settlement_id).execute().data
    total = sum(r["total_amount"] or 0 for r in remaining)
    supabase_admin.table("settlements").update({"total_amount": total}).eq("id", settlement_id).execute()

    logger.info(f"ROUND_DELETED settlement={settlement_id} round={round} user={user_id[:8]}***")
    return {"message": "영수증 삭제 완료", "total_amount": total, "round_count": len(remaining)}


def _existing_rounds(settlement_id: str) -> set:
    """이 정산방에 실제로 등록된 차수 번호들."""
    rows = supabase_admin.table("receipts").select("round").eq("settlement_id", settlement_id).execute()
    return {r["round"] for r in rows.data}


async def set_member_rounds(settlement_id: str, user_id: str, rounds: list) -> dict:
    """참여자 본인이 참여한 라운드 집합을 지정한다(RoundPick 화면). 없으면 insert, 빠지면 delete."""
    ensure_not_locked(_check_member(settlement_id, user_id))

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="이 정산방의 참여자가 아닙니다")
    member_id = member.data[0]["id"]

    wanted = {int(r) for r in rounds}
    missing = wanted - _existing_rounds(settlement_id)
    if missing:
        raise HTTPException(status_code=400, detail="없는 차수가 포함되어 있습니다")
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
    ensure_not_locked(_check_member(settlement_id, user_id))

    member = supabase_admin.table("settlement_members") \
        .select("id").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="이 정산방의 참여자가 아닙니다")
    member_id = member.data[0]["id"]

    if round not in _existing_rounds(settlement_id):
        raise HTTPException(status_code=404, detail="해당 차수의 영수증이 없습니다")

    # 그 차수 영수증에 실제로 있는 품목 이름만 받는다. 아무 문자열이나 저장되게 두면 AI 프롬프트에
    # 그대로 들어가 지시문을 심는 통로가 된다(앱은 화면에 보이는 품목 중에서만 고른다).
    receipt_rows = supabase_admin.table("receipts") \
        .select("id").eq("settlement_id", settlement_id).eq("round", round).execute()
    item_rows = supabase_admin.table("receipt_items") \
        .select("name").eq("receipt_id", receipt_rows.data[0]["id"]).execute() if receipt_rows.data else None
    real_names = {i["name"] for i in (item_rows.data if item_rows else [])}
    names = [n for n in dict.fromkeys(str(x) for x in excluded_item_names) if n in real_names][:100]

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


def _dedupe_nickname(settlement_id: str, nickname: str, exclude_member_id: str | None = None) -> str:
    """같은 정산방 안에서 닉네임이 겹치면 AI 정산이 닉네임으로 사람을 구분하지 못해
    한 명의 몫이 다른 동명이인에게 덮어써질 수 있다(계산 무결성 문제) — 겹치면 자동으로 구분자를 붙인다."""
    base = nickname.strip() or "참여자"
    existing = supabase_admin.table("settlement_members") \
        .select("id, nickname").eq("settlement_id", settlement_id).execute()
    # 이름을 바꾸는 본인(exclude_member_id)의 현재 이름은 겹침 판정에서 뺀다
    taken = {m["nickname"].strip().casefold() for m in existing.data if m["id"] != exclude_member_id}
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base}({n})".casefold() in taken:
        n += 1
    return f"{base}({n})"


# 앱이 닉네임을 모를 때 넣는 기본값 — 이미 제대로 된 이름이 있는 멤버를 이 값으로 덮어쓰지 않는다.
_PLACEHOLDER_NICKNAMES = {"참여자", "사용자"}


def _rename_member_if_changed(settlement_row: dict, member: dict, nickname: str):
    new_name = nickname.strip()
    if not new_name or new_name in _PLACEHOLDER_NICKNAMES or new_name == member["nickname"]:
        return
    # 계산 결과는 닉네임으로 사람을 구분하므로 계산이 시작된 뒤에는 이름을 바꾸지 않는다.
    if settlement_row.get("status") in LOCKED_STATUSES:
        return
    supabase_admin.table("settlement_members") \
        .update({"nickname": _dedupe_nickname(settlement_row["id"], new_name, exclude_member_id=member["id"])}) \
        .eq("id", member["id"]).execute()


async def add_member(
    settlement_id: str, user_id: str, nickname: str, requester_id: str, invite_token: str | None = None
) -> dict:
    """방장이 참여자 추가하거나, 본인이 QR로 입장"""
    settlement = supabase_admin.table("settlements") \
        .select("*").eq("id", settlement_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=404, detail="정산방을 찾을 수 없습니다")
    settlement_row = settlement.data[0]

    # 중복 참여 방지
    existing = supabase_admin.table("settlement_members") \
        .select("id, nickname").eq("settlement_id", settlement_id).eq("user_id", user_id).execute()

    # 방장 본인 입장(RoomViewModel.ensureMyMembershipAndAwait)이나 기존 멤버 재입장은
    # 초대 링크 검증 없이 통과시킨다 — 새로 들어오는 비회원만 토큰을 요구.
    is_owner = settlement_row["created_by"] == user_id
    if not is_owner and not existing.data:
        if settlement_row.get("status") == "done":
            raise HTTPException(
                status_code=409,
                detail={"error_code": "SETTLEMENT_DONE", "message": "이미 완료된 정산방이에요"}
            )
        if not invite_token:
            raise HTTPException(
                status_code=403,
                detail={"error_code": "INVITE_TOKEN_MISSING", "message": "초대 링크가 필요해요"}
            )
        from core.security import decode_invite_token
        payload = decode_invite_token(invite_token)
        if payload.get("sid") != settlement_id:
            raise HTTPException(
                status_code=403,
                detail={"error_code": "INVITE_TOKEN_INVALID", "message": "유효하지 않은 초대 링크예요"}
            )
        # 방장이 QR을 재발급(regenerate)하면 invite_epoch가 올라간다 — 옛 epoch로 서명된
        # 토큰(이미 공유돼 회수 불가능한 QR/링크)은 여기서 무효화된다.
        if payload.get("epoch", 1) != settlement_row.get("invite_epoch", 1):
            raise HTTPException(
                status_code=403,
                detail={"error_code": "INVITE_TOKEN_INVALID", "message": "유효하지 않은 초대 링크예요"}
            )

        capacity = settlement_row.get("member_capacity")
        if capacity is not None:
            current_members = supabase_admin.table("settlement_members") \
                .select("user_id").eq("settlement_id", settlement_id).execute()
            # 방장은 QR 화면에서 자기 이름을 확정하기 전까지 아직 멤버로 등록되지 않는다
            # (참여자 입력 화면에서 이름 확정 후에야 join — 잘못된 OAuth 닉네임 폴백으로
            # 멤버가 먼저 생기는 걸 막기 위한 의도적 순서, QrInviteFragment 참고).
            # 그래서 정원을 게스트 기준으로만 세면 방장 몫이 없어 정원+1까지 들어올 수 있다 —
            # 방장이 아직 안 들어왔으면 정원에서 방장 자리 1개를 미리 빼둔다.
            owner_joined = any(m["user_id"] == settlement_row["created_by"] for m in current_members.data)
            effective_capacity = capacity if owner_joined else capacity - 1
            if len(current_members.data) >= effective_capacity:
                raise HTTPException(
                    status_code=409,
                    detail={"error_code": "SETTLEMENT_FULL", "message": "정원이 다 찼어요"}
                )

    if existing.data:
        # 이미 멤버인 사람이 다른 이름으로 다시 들어오면(참여자 입력 화면에서 이름을 고친 경우) 그 이름을 반영한다.
        # 응답은 예전과 같이 409 — 앱은 409를 "이미 참여 중 = 입장 성공"으로 처리하고 곧바로 정산방을 다시 불러온다.
        _rename_member_if_changed(settlement_row, existing.data[0], nickname)
        raise HTTPException(status_code=409, detail="이미 참여 중입니다")

    result = supabase_admin.table("settlement_members").insert({
        "settlement_id": settlement_id,
        "user_id": user_id,
        "nickname": _dedupe_nickname(settlement_id, nickname),
        "amount": 0
    }).execute()
    member = result.data[0]

    # 정원 확인과 추가 사이에 다른 사람이 동시에 들어오면 둘 다 통과할 수 있다. 넣은 뒤 다시 세어
    # 정원을 넘겼고 내가 넘친 쪽(방장이 아니고, 정원 순번 밖)이면 방금 넣은 행을 되돌린다.
    capacity = settlement_row.get("member_capacity")
    if capacity is not None and not is_owner:
        rows = supabase_admin.table("settlement_members") \
            .select("id, user_id, joined_at").eq("settlement_id", settlement_id) \
            .order("joined_at").order("id").execute().data
        guests = [m for m in rows if m["user_id"] != settlement_row["created_by"]]
        if len(rows) > capacity or len(guests) > capacity - 1:
            allowed = {m["id"] for m in guests[:max(capacity - 1, 0)]}
            if member["id"] not in allowed:
                supabase_admin.table("settlement_members").delete().eq("id", member["id"]).execute()
                raise HTTPException(
                    status_code=409,
                    detail={"error_code": "SETTLEMENT_FULL", "message": "정원이 다 찼어요"}
                )

    return member


async def remove_member(settlement_id: str, member_user_id: str, requester_id: str):
    # 계산이 시작된 뒤 멤버를 빼면 남은 사람들의 금액 합이 총액과 어긋나므로 막는다.
    ensure_not_locked(_check_owner(settlement_id, requester_id))

    supabase_admin.table("settlement_members") \
        .delete().eq("settlement_id", settlement_id).eq("user_id", member_user_id).execute()


async def mark_done(settlement_id: str, user_id: str) -> dict:
    current = _check_owner(settlement_id, user_id)
    # 계산이 끝난 방만 완료할 수 있다(이미 완료된 방을 다시 호출하는 건 그대로 통과).
    if current.get("status") not in ("calculated", "done"):
        raise HTTPException(status_code=400, detail="정산 계산이 끝난 뒤에 완료할 수 있습니다")

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
        if uid and uid not in seen:  # 탈퇴한 사람의 행은 user_id가 비어 있다
            seen.add(uid)
            history_rows.append({"settlement_id": settlement_id, "user_id": uid})

    # 방장이 settlement_members에 없는 경우를 대비해 명시적으로 추가
    if user_id not in seen:
        history_rows.append({"settlement_id": settlement_id, "user_id": user_id})

    if history_rows:
        supabase_admin.table("history").upsert(history_rows, on_conflict="settlement_id,user_id").execute()

    return settlement
