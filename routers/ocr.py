from fastapi import APIRouter, UploadFile, File, Depends
from models.schemas import OcrConfirmRequest, AddItemRequest
from services import ocr_service
from core.security import get_current_user

router = APIRouter(prefix="/ocr", tags=["OCR"])


@router.post("/scan")
async def scan_receipt(
    settlement_id: str,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    return await ocr_service.upload_and_scan(file, settlement_id, current_user["id"])


@router.post("/confirm")
async def confirm_ocr(body: OcrConfirmRequest, current_user=Depends(get_current_user)):
    return await ocr_service.confirm_ocr(body.settlement_id, body.items, current_user["id"])


@router.post("/add-item")
async def add_item(body: AddItemRequest, current_user=Depends(get_current_user)):
    return await ocr_service.add_item(
        body.settlement_id, body.name, body.price, body.quantity, current_user["id"]
    )
