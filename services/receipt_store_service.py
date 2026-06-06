from fastapi import HTTPException, UploadFile
from core.database import supabase_admin
from core.storage import signed_receipt_url
from core.image_validation import verify_image
import uuid
import logging

logger = logging.getLogger(__name__)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


async def save_receipt(file: UploadFile, user_id: str) -> dict:
    """영수증 임시 저장 (정산 연결 전)"""
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="jpg, png, webp만 지원합니다")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")
    verify_image(contents)  # content-type 헤더 위조 방어 — 실제 이미지 바이트인지 검증

    # private 버킷 — 공개 URL을 저장하지 않고 in-bucket 경로(file_path)만 보관, 조회 시 서명.
    file_path = f"saved_receipts/{user_id}/{uuid.uuid4()}.jpg"
    supabase_admin.storage.from_("receipts").upload(
        file_path, contents, {"content-type": file.content_type}
    )

    result = supabase_admin.table("saved_receipts").insert({
        "user_id": user_id,
        "image_url": file_path,   # 레거시 컬럼 — 경로 보관(공개 URL 아님)
        "file_path": file_path,
    }).execute()

    logger.info(f"RECEIPT_SAVED user={user_id[:8]}***")
    return _with_signed_url(result.data[0])


def _with_signed_url(row: dict) -> dict:
    """saved_receipts 행의 image_url을 단기 signed URL로 교체."""
    row["image_url"] = signed_receipt_url(row.get("file_path") or row.get("image_url"))
    return row


async def get_receipts(user_id: str) -> list:
    """저장된 영수증 목록 조회"""
    result = supabase_admin.table("saved_receipts") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()
    return [_with_signed_url(r) for r in (result.data or [])]


async def get_receipt(receipt_id: str, user_id: str) -> dict:
    """영수증 단건 조회 (IDOR 방어)"""
    result = supabase_admin.table("saved_receipts") \
        .select("*") \
        .eq("id", receipt_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return _with_signed_url(result.data[0])


async def delete_receipt(receipt_id: str, user_id: str):
    """영수증 삭제"""
    receipt = await get_receipt(receipt_id, user_id)

    # Storage에서 이미지 삭제
    try:
        supabase_admin.storage.from_("receipts").remove([receipt["file_path"]])
    except Exception:
        pass

    supabase_admin.table("saved_receipts") \
        .delete().eq("id", receipt_id).execute()
