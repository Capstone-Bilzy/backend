from fastapi import APIRouter, Depends, UploadFile, File
from core.security import get_current_user
from services.receipt_store_service import save_receipt, get_receipts, get_receipt, delete_receipt

router = APIRouter(prefix="/receipts", tags=["영수증 저장"])


@router.post("")
async def save(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    return await save_receipt(file, current_user["id"])


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
