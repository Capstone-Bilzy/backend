from google import genai
from google.genai import types
from fastapi import HTTPException, UploadFile
from core.database import supabase_admin
from core.config import settings
from core.storage import signed_receipt_url
from core.image_validation import verify_image
import uuid, json
import logging

logger = logging.getLogger(__name__)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Gemini 클라이언트
_client = genai.Client(api_key=settings.GEMINI_API_KEY)

OCR_PROMPT = """
이 영수증 이미지에서 메뉴명과 가격을 추출해줘. 한국어 영수증이야.

규칙:
- 메뉴명과 가격만 추출 (날짜, 사업자번호, 주소 등 제외)
- 수량이 명시된 경우 quantity에 반영
- 가격은 숫자만 (원 기호, 쉼표 제외)
- 인식 불가한 항목은 포함하지 마

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
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                OCR_PROMPT,
            ]
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

        return result

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="영수증 파싱 실패 - 이미지를 다시 촬영해주세요")
    except Exception as e:
        logger.error(f"Gemini OCR error: {e}")
        raise HTTPException(status_code=500, detail="OCR 처리 중 오류가 발생했습니다")


async def scan_only(file: UploadFile) -> dict:
    """정산방과 무관한 독립 OCR. 보관함 저장 전 금액 프리필용으로 items/total만 반환(저장 없음)."""
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="jpg, png, webp만 지원합니다")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")
    verify_image(contents)  # content-type 헤더 위조 방어

    ocr_result = await scan_with_gemini(contents, file.content_type)
    total = ocr_result.get("total", sum(
        i["price"] * i["quantity"] for i in ocr_result.get("items", [])
    ))
    return {"items": ocr_result.get("items", []), "total": total}


def _check_settlement_owner(settlement_id: str, user_id: str) -> dict:
    settlement = supabase_admin.table("settlements") \
        .select("id").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return settlement.data[0]


def _get_or_create_receipt(settlement_id: str, round: int) -> dict:
    """정산방의 특정 라운드 receipts row를 찾거나 없으면 만든다."""
    existing = supabase_admin.table("receipts") \
        .select("*").eq("settlement_id", settlement_id).eq("round", round).execute()
    if existing.data:
        return existing.data[0]
    created = supabase_admin.table("receipts").insert({
        "settlement_id": settlement_id,
        "round": round,
    }).execute()
    return created.data[0]


def _recompute_settlement_total(settlement_id: str):
    """모든 라운드(receipts) 합계를 settlements.total_amount에 반영한다."""
    receipts = supabase_admin.table("receipts") \
        .select("total_amount").eq("settlement_id", settlement_id).execute()
    total = sum(r["total_amount"] or 0 for r in receipts.data)
    supabase_admin.table("settlements").update({"total_amount": total}).eq("id", settlement_id).execute()
    return total


async def upload_and_scan(file: UploadFile, settlement_id: str, round: int, user_id: str) -> dict:
    # 1. 입력 검증
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="jpg, png, webp만 지원합니다")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")
    verify_image(contents)  # content-type 헤더 위조 방어 — 실제 이미지 바이트인지 검증

    # 2. 정산방 소유자 확인 (IDOR 방어)
    _check_settlement_owner(settlement_id, user_id)

    # 3. Gemini Vision으로 OCR
    ocr_result = await scan_with_gemini(contents, file.content_type)

    # 항목을 하나도 못 읽었으면 "인식 성공(빈 결과)"이 아니라 실패로 취급한다 —
    # 그래야 앱이 RecognizingFragment의 재촬영/직접입력 폴백을 보여준다.
    if not ocr_result.get("items"):
        logger.warning(f"OCR_EMPTY settlement={settlement_id} round={round} user={user_id[:8]}***")
        raise HTTPException(status_code=422, detail="영수증에서 항목을 인식하지 못했어요. 다시 촬영해주세요")

    # 4. Supabase Storage(private 버킷)에 저장 — 공개 URL이 아닌 in-bucket 경로만 DB에 보관.
    #    조회 시 settlement_service가 멤버에게만 단기 signed URL을 발급한다.
    file_path = f"receipts/{settlement_id}/{round}/{uuid.uuid4()}.jpg"
    supabase_admin.storage.from_("receipts").upload(
        file_path, contents, {"content-type": file.content_type}
    )

    # 5. 이 라운드의 receipts row에 OCR 결과 반영
    total = ocr_result.get("total", sum(
        i["price"] * i["quantity"] for i in ocr_result.get("items", [])
    ))
    receipt = _get_or_create_receipt(settlement_id, round)
    supabase_admin.table("receipts").update({
        "receipt_image_url": file_path,
        "total_amount": total,
    }).eq("id", receipt["id"]).execute()

    # 6. 이 라운드의 항목만 교체 (다른 라운드는 건드리지 않음)
    supabase_admin.table("receipt_items").delete().eq("receipt_id", receipt["id"]).execute()
    if ocr_result.get("items"):
        supabase_admin.table("receipt_items").insert([
            {
                "receipt_id": receipt["id"],
                "name": item["name"][:50],
                "price": max(0, min(item["price"], 10_000_000)),
                "quantity": max(1, min(item["quantity"], 100)),
            }
            for item in ocr_result["items"]
        ]).execute()

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

    # 정산방 소유자 확인
    _check_settlement_owner(settlement_id, user_id)

    receipt = _get_or_create_receipt(settlement_id, round)

    # 이 라운드 항목만 삭제 후 재삽입
    supabase_admin.table("receipt_items").delete().eq("receipt_id", receipt["id"]).execute()

    # 입력값 검증 후 삽입
    validated_items = []
    total = 0
    for item in items:
        name = str(item.get("name", ""))[:50]
        price = max(0, min(int(item.get("price", 0)), 10_000_000))
        quantity = max(1, min(int(item.get("quantity", 1)), 100))
        validated_items.append({
            "receipt_id": receipt["id"],
            "name": name,
            "price": price,
            "quantity": quantity
        })
        total += price * quantity

    if validated_items:
        supabase_admin.table("receipt_items").insert(validated_items).execute()

    # 이 라운드의 가게명/총액 갱신, 정산방 전체 총액 재계산
    supabase_admin.table("receipts").update({
        "store_name": store_name[:50] if store_name else None,
        "total_amount": total,
    }).eq("id", receipt["id"]).execute()
    settlement_total = _recompute_settlement_total(settlement_id)

    return {"round": round, "total_amount": total, "settlement_total_amount": settlement_total, "items": validated_items}


async def add_item(settlement_id: str, round: int, name: str, price: int, quantity: int, user_id: str) -> dict:
    # 정산방 소유자 확인
    _check_settlement_owner(settlement_id, user_id)
    receipt = _get_or_create_receipt(settlement_id, round)

    result = supabase_admin.table("receipt_items").insert({
        "receipt_id": receipt["id"],
        "name": name,
        "price": price,
        "quantity": quantity
    }).execute()

    # 이 라운드 총액 재계산 후 정산방 합계 갱신
    items = supabase_admin.table("receipt_items") \
        .select("price, quantity").eq("receipt_id", receipt["id"]).execute()
    round_total = sum(i["price"] * i["quantity"] for i in items.data)
    supabase_admin.table("receipts").update({"total_amount": round_total}).eq("id", receipt["id"]).execute()
    _recompute_settlement_total(settlement_id)

    return result.data[0]
