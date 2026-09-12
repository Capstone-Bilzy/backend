from fastapi import APIRouter, UploadFile, File, Depends, Request, Query
from models.schemas import OcrConfirmRequest, AddItemRequest
from services import ocr_service
from core.security import get_current_user
from core.limiter import limiter

router = APIRouter(prefix="/ocr", tags=["OCR"])


@router.post("/scan")
@limiter.limit("10/minute")  # Gemini Vision 호출 — 비용 발생, 남용 차단
async def scan_receipt(
    request: Request,
    settlement_id: str,
    round: int = Query(default=1, gt=0, le=100),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    return await ocr_service.upload_and_scan(file, settlement_id, round, current_user["id"])


@router.post("/confirm")
@limiter.limit("30/minute")  # DB 쓰기 증폭 방지(항목 delete+insert)
async def confirm_ocr(request: Request, body: OcrConfirmRequest, current_user=Depends(get_current_user)):
    return await ocr_service.confirm_ocr(
        body.settlement_id, body.round, body.store_name, body.items, current_user["id"]
    )


@router.post("/add-item")
@limiter.limit("30/minute")
async def add_item(request: Request, body: AddItemRequest, current_user=Depends(get_current_user)):
    return await ocr_service.add_item(
        body.settlement_id, body.round, body.name, body.price, body.quantity, current_user["id"]
    )
