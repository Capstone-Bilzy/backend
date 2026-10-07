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


def remove_settlement_files(settlement_id: str) -> int:
    """정산방에 딸린 영수증 이미지(차수별 사진·추가 첨부)를 스토리지에서 모두 지우고 지운 개수를 돌려준다.

    DB 행만 지우면 이미지가 버킷에 남는다 — 영수증에는 상호·결제 내역이 들어 있으므로 방을 지우면 같이 지운다.
    실패해도 방 삭제 자체는 막지 않는다(호출 측에서 예외를 삼킨다).
    """
    bucket = supabase_admin.storage.from_(BUCKET)
    root = f"receipts/{settlement_id}"
    paths = []
    for entry in bucket.list(root, {"limit": 1000}) or []:
        name = entry.get("name")
        if not name:
            continue
        if entry.get("id") is None:  # 폴더(차수 번호, extra)
            for child in bucket.list(f"{root}/{name}", {"limit": 1000}) or []:
                if child.get("name"):
                    paths.append(f"{root}/{name}/{child['name']}")
        else:  # 예전 구조: 방 폴더 바로 아래 파일
            paths.append(f"{root}/{name}")
    if paths:
        bucket.remove(paths)
    return len(paths)


def remove_receipt_file(stored: str | None) -> bool:
    """DB에 저장된 값(in-bucket 경로 또는 예전 URL) 하나에 해당하는 파일을 지운다. 지웠으면 True.

    예전 삭제 코드는 `stored.split("/receipts/")[-1]` 뒤에 `receipts/`를 다시 붙였는데, 저장값이
    `receipts/...`(앞에 `/` 없음)라 split이 아무것도 자르지 못해 `receipts/receipts/...`라는 없는 경로를
    지우려 했다 — 오류 없이 조용히 실패해서 탈퇴·차수 삭제·보관 기간 파기에서 사진이 남았다.
    """
    path = _to_inbucket_path(stored)
    if not path:
        return False
    removed = supabase_admin.storage.from_(BUCKET).remove([path])
    if not removed:
        logger.warning(f"receipt file not removed (already gone?): {path!r}")
    return bool(removed)

