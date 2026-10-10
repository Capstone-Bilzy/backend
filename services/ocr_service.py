import asyncio
from google import genai
from google.genai import types
from fastapi import HTTPException, UploadFile
from core.database import supabase_admin
from core.config import settings
from core import gemini
from core.storage import signed_receipt_url, remove_receipt_file
from core.image_validation import read_upload, SANITIZED_MIME
import uuid, json
import logging

logger = logging.getLogger(__name__)

MAX_EXTRA_PHOTOS = 30  # 정산방당 순수 첨부 사진 개수 상한(스토리지 남용 방지)

# Gemini 클라이언트

OCR_PROMPT = """
이 영수증 이미지에서 메뉴명과 가격을 추출해줘. 한국어 영수증이야.

규칙:
- 메뉴명과 가격만 추출 (날짜, 사업자번호, 주소 등 제외)
- 수량이 명시된 경우 quantity에 반영
- 가격은 숫자만 (원 기호, 쉼표 제외)
- 인식 불가한 항목은 포함하지 마
- 금액이 0원인 줄(이벤트·사은품·서비스·"단품" 같은 옵션 줄)은 포함하지 마
- 상품명 아래에 따로 찍힌 상품코드(숫자만 있는 줄)는 메뉴가 아니니 무시해

반드시 아래 JSON 형식으로만 응답해. 다른 텍스트 절대 포함하지 마.
{
  "items": [
    {"name": "메뉴명", "price": 숫자, "quantity": 숫자}
  ],
  "total": 숫자
}
"""


async def scan_with_gemini(image_bytes: bytes, mime_type: str) -> dict:
    """Gemini Vision으로 영수증 OCR + 파싱 한 번에"""
    try:
        # 동기 SDK 호출을 스레드로 넘겨, OCR이 도는 동안에도 서버가 다른 요청을 받게 한다.
        response = await asyncio.to_thread(
            gemini.generate,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                OCR_PROMPT,
            ],
            # temperature 0: 같은 사진이면 같은 결과가 나오게 한다. 기본값에서는 화질이 애매한 영수증의
            # 한글 품목명이 호출할 때마다 달라졌다(리뷰이벤트 → 고리빅이벤트/앙버터이벤트 등).
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        )
        raw = response.text.strip()

        # ```json ... ``` 펜스 제거
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())

        # 기본값 보정
        for item in result.get("items", []):
            item.setdefault("quantity", 1)
            item["price"] = int(item["price"])
            item["quantity"] = int(item["quantity"])

        # 0원인 줄(리뷰이벤트·옵션 등)은 정산에 영향이 없으므로 품목에서 뺀다(프롬프트로도 막지만 한 번 더 거른다).
        result["items"] = [
            i for i in result.get("items", []) if i["price"] > 0 and i["quantity"] > 0
        ]
        _fix_amount_read_as_unit_price(result)

        return result

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="영수증 파싱 실패 - 이미지를 다시 촬영해주세요")
    except Exception as e:
        logger.error(f"Gemini OCR error: {e}")
        text = str(e)
        if "RESOURCE_EXHAUSTED" in text or "429" in text or "UNAVAILABLE" in text:
            raise HTTPException(status_code=503, detail="AI 사용량 한도를 초과했어요. 잠시 후 다시 시도하거나 직접 입력해주세요")
        raise HTTPException(status_code=500, detail="OCR 처리 중 오류가 발생했습니다")


def _fix_amount_read_as_unit_price(result: dict):
    """모델이 "금액" 열(단가×수량)을 단가로 읽어 온 경우를 영수증 합계로 가려내 바로잡는다.

    단가·수량·금액 열이 다 있는 영수증에서 가벼운 모델이 price에 금액을 넣곤 한다
    (생맥주 3,000×2=6,000 → price 6000, quantity 2 → 12,000으로 두 배 계산).
    단가×수량의 합은 영수증 합계와 다른데 price의 합이 합계와 정확히 같으면 price가 금액이었다는 뜻이므로,
    단가 = 금액÷수량으로 되돌리고 나누어떨어지지 않는 줄은 금액을 line_amount에 그대로 둔다.
    """
    items = result.get("items") or []
    try:
        total = int(result.get("total"))
    except (TypeError, ValueError):
        return
    if total <= 0 or not items:
        return
    if sum(i["price"] * i["quantity"] for i in items) == total:
        return
    if sum(i["price"] for i in items) != total:
        return
    for i in items:
        amount, quantity = i["price"], i["quantity"]
        if quantity > 1:
            i["price"] = amount // quantity
            if amount % quantity:
                i["line_amount"] = amount
    logger.info("OCR_AMOUNT_COLUMN_FIXED 금액 열을 단가로 읽은 결과를 합계 기준으로 보정")


def _check_settlement_owner(settlement_id: str, user_id: str) -> dict:
    settlement = supabase_admin.table("settlements") \
        .select("id, status").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return settlement.data[0]


def _check_editable_owner(settlement_id: str, user_id: str) -> dict:
    """소유자 확인 + 계산이 시작된 뒤에는 영수증 내용을 못 바꾸게 막는다."""
    from services.settlement_service import ensure_not_locked
    settlement = _check_settlement_owner(settlement_id, user_id)
    ensure_not_locked(settlement)
    return settlement


def _get_or_create_receipt(settlement_id: str, round: int, create: bool = True) -> dict:
    """정산방의 특정 라운드 receipts row를 찾거나 없으면 만든다.

    새 차수는 지금 있는 마지막 차수 바로 다음 번호로만 만들 수 있다(1·2차만 있는데 5차를 만드는 식의
    건너뛰기 금지). create=False면 없는 차수는 만들지 않고 404.
    """
    existing = supabase_admin.table("receipts") \
        .select("*").eq("settlement_id", settlement_id).eq("round", round).execute()
    if existing.data:
        return existing.data[0]
    if not create:
        raise HTTPException(status_code=404, detail="해당 차수의 영수증이 없습니다")
    rounds = supabase_admin.table("receipts") \
        .select("round").eq("settlement_id", settlement_id).execute()
    last_round = max((r["round"] for r in rounds.data), default=0)
    if round > last_round + 1:
        raise HTTPException(status_code=400, detail="앞 차수 영수증을 먼저 등록해주세요")
    created = supabase_admin.table("receipts").insert({
        "settlement_id": settlement_id,
        "round": round,
    }).execute()
    return created.data[0]


def item_total(item: dict) -> int:
    """품목 한 줄의 금액. line_amount가 있으면 그 값(단가로 나누어떨어지지 않는 줄), 없으면 단가×수량."""
    line_amount = item.get("line_amount")
    return int(line_amount) if line_amount is not None else int(item["price"]) * int(item["quantity"])


def _ensure_round_allowed(settlement_id: str, round: int):
    """이미 있는 차수이거나 마지막 차수 바로 다음 번호일 때만 통과시킨다(_get_or_create_receipt와 같은 규칙)."""
    rounds = supabase_admin.table("receipts") \
        .select("round").eq("settlement_id", settlement_id).execute()
    existing = {r["round"] for r in rounds.data}
    if round not in existing and round > max(existing, default=0) + 1:
        raise HTTPException(status_code=400, detail="앞 차수 영수증을 먼저 등록해주세요")


def _check_daily_scan_quota(user_id: str):
    """하루 인식 횟수 제한. 오늘(한국 시간) 이 사용자의 인식 기록을 access_logs에서 세고, 통과하면 이번 것을 기록한다.

    세는 것과 기록 사이가 원자적이지 않아 동시에 여러 장을 올리면 한두 번 더 통과할 수 있다(무료 한도 보호용이라 충분).
    기록·조회가 실패하면 인식을 막지 않는다.
    """
    limit = settings.OCR_DAILY_LIMIT_PER_USER
    if limit <= 0:
        return
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    day_start = datetime.now(kst).replace(hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).replace(tzinfo=None)
    try:
        used = supabase_admin.table("access_logs").select("id", count="exact") \
            .eq("user_id", user_id).eq("resource", "ocr_scan") \
            .gte("created_at", day_start.isoformat()).execute().count or 0
    except Exception as e:
        logger.error(f"OCR quota check failed: {e}")
        return
    if used >= limit:
        logger.info(f"OCR_DAILY_LIMIT user={user_id[:8]}*** used={used}")
        raise HTTPException(
            status_code=429,
            detail=f"오늘 영수증 인식은 {limit}번까지 할 수 있어요. 직접 입력을 이용해주세요"
        )
    try:
        supabase_admin.table("access_logs").insert({
            "user_id": user_id, "action": "CREATE", "resource": "ocr_scan",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"OCR quota log failed: {e}")


def _recompute_settlement_total(settlement_id: str):
    """모든 라운드(receipts) 합계를 settlements.total_amount에 반영한다."""
    receipts = supabase_admin.table("receipts") \
        .select("total_amount").eq("settlement_id", settlement_id).execute()
    total = sum(r["total_amount"] or 0 for r in receipts.data)
    supabase_admin.table("settlements").update({"total_amount": total}).eq("id", settlement_id).execute()
    return total


async def upload_and_scan(file: UploadFile, settlement_id: str, round: int, user_id: str) -> dict:
    # 1. 정산방 소유자 확인 (IDOR 방어) — 권한 없는 요청은 이미지를 디코딩하기 전에 끊는다
    _check_editable_owner(settlement_id, user_id)
    # 만들 수 없는 차수(건너뛴 번호)는 AI를 부르기 전에 거절한다 — 예전엔 인식·업로드를 다 한 뒤에야 400이 나서
    # 실패할 요청이 Gemini 한도를 쓰고 저장소에 주인 없는 사진을 남겼다.
    _ensure_round_allowed(settlement_id, round)
    _check_daily_scan_quota(user_id)

    # 2. 입력 검증
    # 크기 제한 안에서 읽고, 실제 이미지로 디코딩해 메타데이터 없는 새 JPEG으로 다시 만든 바이트만 쓴다
    # (위장 파일·폴리글랏·EXIF 위치정보 차단 — core/image_validation.py).
    contents = await read_upload(file)

    # 3. Gemini Vision으로 OCR
    ocr_result = await scan_with_gemini(contents, SANITIZED_MIME)

    # 항목을 하나도 못 읽었으면 "인식 성공(빈 결과)"이 아니라 실패로 취급한다 —
    # 그래야 앱이 RecognizingFragment의 재촬영/직접입력 폴백을 보여준다.
    if not ocr_result.get("items"):
        logger.warning(f"OCR_EMPTY settlement={settlement_id} round={round} user={user_id[:8]}***")
        raise HTTPException(status_code=422, detail="영수증에서 항목을 인식하지 못했어요. 다시 촬영해주세요")

    # 4. Supabase Storage(private 버킷)에 저장 — 공개 URL이 아닌 in-bucket 경로만 DB에 보관.
    #    조회 시 settlement_service가 멤버에게만 단기 signed URL을 발급한다.
    file_path = f"receipts/{settlement_id}/{round}/{uuid.uuid4()}.jpg"
    supabase_admin.storage.from_("receipts").upload(
        file_path, contents, {"content-type": SANITIZED_MIME}
    )

    # 5. 이 라운드의 receipts row에 OCR 결과 반영
    # 총액은 모델이 준 값이 아니라 품목 합으로 서버가 계산한다(확정 때와 같은 기준, 이상한 값 유입 차단).
    total = sum(item_total(i) for i in ocr_result.get("items", []))
    receipt = _get_or_create_receipt(settlement_id, round)
    # 같은 차수를 다시 찍은 경우 이전 사진은 지운다(안 그러면 아무도 가리키지 않는 사진이 남는다).
    previous_image = receipt.get("receipt_image_url")
    if previous_image and previous_image != file_path:
        try:
            remove_receipt_file(previous_image)
        except Exception as e:
            logger.error(f"Previous receipt image remove failed for {settlement_id} round={round}: {e}")
    supabase_admin.table("receipts").update({
        "receipt_image_url": file_path,
        "total_amount": total,
    }).eq("id", receipt["id"]).execute()

    # 6. 이 라운드의 항목만 교체 (다른 라운드는 건드리지 않음)
    supabase_admin.table("receipt_items").delete().eq("receipt_id", receipt["id"]).execute()
    if ocr_result.get("items"):
        rows = []
        for item in ocr_result["items"]:
            row = {
                "receipt_id": receipt["id"],
                "name": item["name"][:50],
                "price": max(0, min(item["price"], 10_000_000)),
                "quantity": max(1, min(item["quantity"], 100)),
            }
            if item.get("line_amount") is not None:
                row["line_amount"] = max(0, min(int(item["line_amount"]), 1_000_000_000))
            rows.append(row)
        _insert_items(rows)

    _recompute_settlement_total(settlement_id)

    logger.info(f"OCR_SCAN settlement={settlement_id} round={round} items={len(ocr_result.get('items',[]))} user={user_id[:8]}***")

    return {
        "settlement_id": settlement_id,
        "round": round,
        "image_url": signed_receipt_url(file_path),
        "items": ocr_result.get("items", []),
        "total": total,
        "message": "OCR 결과를 확인하고 수정해주세요"
    }


async def confirm_ocr(settlement_id: str, round: int, store_name: str, items: list, user_id: str) -> dict:
    """앱에서 ML Kit OCR 결과 + 수동 수정 후 확정. 이 라운드(receipt)의 항목만 교체한다 —
    다른 라운드의 데이터는 그대로 유지되어 다차 정산이 가능하다."""

    # 정산방 소유자 확인 (계산 시작 후엔 수정 불가)
    _check_editable_owner(settlement_id, user_id)

    receipt = _get_or_create_receipt(settlement_id, round)

    # 이 라운드 항목만 삭제 후 재삽입
    supabase_admin.table("receipt_items").delete().eq("receipt_id", receipt["id"]).execute()

    # 값 범위·형식은 요청 스키마(OcrConfirmItem)에서 이미 검증됨
    validated_items = []
    total = 0
    for item in items:
        row = {
            "receipt_id": receipt["id"],
            "name": item.name,
            "price": item.price,
            "quantity": item.quantity
        }
        # 단가×수량과 같은 값이면 굳이 저장하지 않는다(컬럼은 "표현 못 하는 줄"에만 쓴다).
        if item.line_amount is not None and item.line_amount != item.price * item.quantity:
            row["line_amount"] = item.line_amount
        validated_items.append(row)
        total += item_total(row)

    if validated_items:
        _insert_items(validated_items)

    # 이 라운드의 가게명/총액 갱신, 정산방 전체 총액 재계산
    supabase_admin.table("receipts").update({
        "store_name": store_name[:50] if store_name else None,
        "total_amount": total,
    }).eq("id", receipt["id"]).execute()
    settlement_total = _recompute_settlement_total(settlement_id)

    return {"round": round, "total_amount": total, "settlement_total_amount": settlement_total, "items": validated_items}


def _insert_items(rows: list):
    """receipt_items 삽입. 한 요청 안에서 키 구성이 달라지지 않게 line_amount가 하나라도 있으면 전부에 채운다.

    line_amount 컬럼이 아직 없는 DB(schema_line_amount.sql 미적용)에서는 삽입이 실패하므로,
    그때는 예전 방식(금액 그대로 × 1개)으로 바꿔 저장해 금액만은 틀어지지 않게 한다.
    """
    if not any("line_amount" in r for r in rows):
        supabase_admin.table("receipt_items").insert(rows).execute()
        return
    full = [{**r, "line_amount": r.get("line_amount")} for r in rows]
    try:
        supabase_admin.table("receipt_items").insert(full).execute()
    except Exception as e:
        if "line_amount" not in str(e):
            raise
        logger.warning("receipt_items.line_amount 컬럼이 없어 '금액×1개'로 저장합니다(schema_line_amount.sql 적용 필요)")
        fallback = []
        for r in rows:
            if r.get("line_amount") is not None:
                fallback.append({"receipt_id": r["receipt_id"], "name": r["name"], "price": r["line_amount"], "quantity": 1})
            else:
                fallback.append({k: v for k, v in r.items() if k != "line_amount"})
        rows[:] = fallback
        supabase_admin.table("receipt_items").insert(fallback).execute()


async def add_item(settlement_id: str, round: int, name: str, price: int, quantity: int, user_id: str) -> dict:
    # 정산방 소유자 확인 (계산 시작 후엔 수정 불가)
    _check_editable_owner(settlement_id, user_id)
    receipt = _get_or_create_receipt(settlement_id, round, create=False)

    result = supabase_admin.table("receipt_items").insert({
        "receipt_id": receipt["id"],
        "name": name,
        "price": price,
        "quantity": quantity
    }).execute()

    # 이 라운드 총액 재계산 후 정산방 합계 갱신
    items = supabase_admin.table("receipt_items") \
        .select("*").eq("receipt_id", receipt["id"]).execute()
    round_total = sum(item_total(i) for i in items.data)
    supabase_admin.table("receipts").update({"total_amount": round_total}).eq("id", receipt["id"]).execute()
    _recompute_settlement_total(settlement_id)

    return result.data[0]


async def attach_receipt_photo(settlement_id: str, file: UploadFile, user_id: str) -> dict:
    """정산방에 영수증 사진만 순수 기록용으로 첨부한다(OCR·금액 계산 없음).
    receipts(라운드)와 무관한 별도 테이블에 저장 — 정산 계산·참여자 몫에 전혀 영향을 주지 않는다."""
    # 권한 없는 요청은 이미지를 디코딩하기 전에 끊는다
    _check_settlement_owner(settlement_id, user_id)

    # 크기 제한 안에서 읽고, 실제 이미지로 디코딩해 메타데이터 없는 새 JPEG으로 다시 만든 바이트만 쓴다
    # (위장 파일·폴리글랏·EXIF 위치정보 차단 — core/image_validation.py).
    contents = await read_upload(file)

    existing_count = supabase_admin.table("settlement_extra_photos") \
        .select("id", count="exact").eq("settlement_id", settlement_id).execute()
    if (existing_count.count or 0) >= MAX_EXTRA_PHOTOS:
        raise HTTPException(status_code=400, detail=f"영수증 사진은 최대 {MAX_EXTRA_PHOTOS}장까지 추가할 수 있습니다")

    file_path = f"receipts/{settlement_id}/extra/{uuid.uuid4()}.jpg"
    supabase_admin.storage.from_("receipts").upload(
        file_path, contents, {"content-type": SANITIZED_MIME}
    )

    supabase_admin.table("settlement_extra_photos").insert({
        "settlement_id": settlement_id,
        "image_url": file_path,
        "uploaded_by": user_id,
    }).execute()

    logger.info(f"RECEIPT_PHOTO_ATTACHED settlement={settlement_id} user={user_id[:8]}***")

    return {
        "image_url": signed_receipt_url(file_path),
    }
