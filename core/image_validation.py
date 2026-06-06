"""
업로드 이미지 검증.

content-type 헤더는 클라이언트가 위조할 수 있으므로, 실제 바이트를 디코딩해
진짜 이미지인지(jpg/png/webp) 확인한다. 임의 바이트(폴리글랏/스크립트 등) 저장을 차단.
"""

from io import BytesIO
from fastapi import HTTPException
from PIL import Image

_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def verify_image(contents: bytes) -> None:
    """실제 이미지가 아니거나 허용 포맷이 아니면 400."""
    try:
        img = Image.open(BytesIO(contents))
        fmt = (img.format or "").upper()
        img.verify()  # 손상/위조 검사
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="유효한 이미지 파일이 아닙니다")
    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="jpg, png, webp 이미지만 지원합니다")
