"""
영수증 이미지 보안 접근 모듈

receipts 버킷은 private이며, DB에는 공개 URL이 아닌 in-bucket 경로(file_path)를 저장한다.
조회 시점에 단기 만료 signed URL을 발급해 인증된 요청자에게만 임시 접근을 허용한다.
(개인정보보호법 기술적 보호조치 — 영수증은 상호/결제내역 등 개인정보 포함)
"""

from core.database import supabase_admin
import logging

logger = logging.getLogger(__name__)

BUCKET = "receipts"
SIGNED_TTL = 3600  # 1시간


def _to_inbucket_path(stored: str | None) -> str | None:
    """저장값(in-bucket 경로 또는 레거시 public/sign URL)에서 버킷 내부 경로만 추출."""
    if not stored:
        return None
    for marker in ("/object/public/receipts/", "/object/sign/receipts/"):
        if marker in stored:
            return stored.split(marker, 1)[1].split("?", 1)[0]
    if stored.startswith("http"):
        return None  # 알 수 없는 외부 URL
    return stored  # 이미 in-bucket 경로


def signed_receipt_url(stored: str | None, expires_in: int = SIGNED_TTL) -> str | None:
    """저장된 경로/URL을 단기 signed URL로 변환. 실패 시 None."""
    if not stored:
        return None
    path = _to_inbucket_path(stored)
    if not path:
        logger.warning(f"receipt_image_url 경로 파싱 실패: {stored!r}")
        return None
    try:
        res = supabase_admin.storage.from_(BUCKET).create_signed_url(path, expires_in)
        url = res.get("signedURL") or res.get("signedUrl")
        if not url:
            logger.warning(f"signed URL이 빈 값: path={path!r}, res={res}")
        return url
    except Exception as e:
        logger.error(f"receipt signed url 발급 실패: path={path!r}, error={e}")
