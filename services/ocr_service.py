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


async def upload_and_scan(file: UploadFile, settlement_id: str, user_id: str) -> dict:
    # 1. 입력 검증
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="jpg, png, webp만 지원합니다")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")
    verify_image(contents)  # content-type 헤더 위조 방어 — 실제 이미지 바이트인지 검증

    # 2. 정산방 소유자 확인 (IDOR 방어)
    settlement = supabase_admin.table("settlements") \
        .select("id").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    # 3. Gemini Vision으로 OCR
    ocr_result = await scan_with_gemini(contents, file.content_type)

    # 4. Supabase Storage(private 버킷)에 저장 — 공개 URL이 아닌 in-bucket 경로만 DB에 보관.
    #    조회 시 settlement_service가 멤버에게만 단기 signed URL을 발급한다.
    file_path = f"receipts/{settlement_id}/{uuid.uuid4()}.jpg"
    supabase_admin.storage.from_("receipts").upload(
        file_path, contents, {"content-type": file.content_type}
    )

    # 5. OCR 결과 DB 저장
    total = ocr_result.get("total", sum(
        i["price"] * i["quantity"] for i in ocr_result.get("items", [])
    ))

    supabase_admin.table("settlements").update({
        "receipt_image_url": file_path,
        "total_amount": total,
        "status": "scanning"
    }).eq("id", settlement_id).execute()

    # 6. 영수증 항목 저장
    if ocr_result.get("items"):
        supabase_admin.table("receipt_items").delete().eq("settlement_id", settlement_id).execute()
        supabase_admin.table("receipt_items").insert([
            {
                "settlement_id": settlement_id,
                "name": item["name"][:50],
                "price": max(0, min(item["price"], 10_000_000)),
                "quantity": max(1, min(item["quantity"], 100)),
            }
            for item in ocr_result["items"]
        ]).execute()

    logger.info(f"OCR_SCAN settlement={settlement_id} items={len(ocr_result.get('items',[]))} user={user_id[:8]}***")

    return {
        "settlement_id": settlement_id,
        "image_url": signed_receipt_url(file_path),
        "items": ocr_result.get("items", []),
        "total": total,
        "message": "OCR 결과를 확인하고 수정해주세요"
    }


async def confirm_ocr(settlement_id: str, items: list, user_id: str) -> dict:
    """앱에서 ML Kit OCR 결과 + 수동 수정 후 확정"""

    # 정산방 소유자 확인
    settlement = supabase_admin.table("settlements") \
        .select("id").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    # 기존 항목 삭제 후 재삽입
    supabase_admin.table("receipt_items").delete().eq("settlement_id", settlement_id).execute()

    # 입력값 검증 후 삽입
    validated_items = []
    total = 0
    for item in items:
        name = str(item.get("name", ""))[:50]
        price = max(0, min(int(item.get("price", 0)), 10_000_000))
        quantity = max(1, min(int(item.get("quantity", 1)), 100))
        validated_items.append({
            "settlement_id": settlement_id,
            "name": name,
            "price": price,
            "quantity": quantity
        })
        total += price * quantity

    supabase_admin.table("receipt_items").insert(validated_items).execute()

    # 총액 업데이트
    supabase_admin.table("settlements").update({
        "total_amount": total,
        "status": "waiting"
    }).eq("id", settlement_id).execute()

    return {"total_amount": total, "items": validated_items}


async def add_item(settlement_id: str, name: str, price: int, quantity: int, user_id: str) -> dict:
    # 정산방 소유자 확인
    settlement = supabase_admin.table("settlements") \
        .select("id, total_amount").eq("id", settlement_id).eq("created_by", user_id).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    result = supabase_admin.table("receipt_items").insert({
        "settlement_id": settlement_id,
        "name": name,
        "price": price,
        "quantity": quantity
    }).execute()

    # 총액 재계산
    items = supabase_admin.table("receipt_items") \
        .select("price, quantity").eq("settlement_id", settlement_id).execute()
    total = sum(i["price"] * i["quantity"] for i in items.data)

    supabase_admin.table("settlements").update({"total_amount": total}).eq("id", settlement_id).execute()

    return result.data[0]
