from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from typing import Optional
from core.security import get_current_user
from core.limiter import limiter
from services.receipt_store_service import save_receipt, get_receipts, get_receipt, delete_receipt
from services import ocr_service

router = APIRouter(prefix="/receipts", tags=["영수증 저장"])


@router.post("/scan")
@limiter.limit("10/minute")  # Gemini Vision 호출 — 비용 발생, 남용 차단
async def scan(request: Request, file: UploadFile = File(...), current_user=Depends(get_current_user)):
    """보관함 저장 전 독립 OCR — 금액 프리필용 items/total만 반환(저장 없음)."""
    return await ocr_service.scan_only(file)


@router.post("")
async def save(
    file: UploadFile = File(...),
    store_name: Optional[str] = Form(None),
    total_amount: Optional[int] = Form(None),
    current_user=Depends(get_current_user),
):
    return await save_receipt(file, current_user["id"], store_name, total_amount)


@router.get("")
async def list_receipts(current_user=Depends(get_current_user)):
    return await get_receipts(current_user["id"])


@router.get("/{receipt_id}")
async def get_one(receipt_id: str, current_user=Depends(get_current_user)):
    return await get_receipt(receipt_id, current_user["id"])


@router.delete("/{receipt_id}")
async def delete_one(receipt_id: str, current_user=Depends(get_current_user)):
    await delete_receipt(receipt_id, current_user["id"])
    return {"message": "삭제 완료"}
