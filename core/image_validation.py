"""
업로드 이미지 검증·정화.

업로드 파일은 전부 신뢰하지 않는다. 받은 바이트를 그대로 저장하지 않고, 실제로 이미지로 디코딩한 뒤
새 JPEG으로 다시 만들어 그 결과만 저장·전달한다. 이렇게 하면:
- 이미지인 척하는 임의 파일(스크립트·실행 파일·HTML)은 디코딩 단계에서 걸러진다.
- 정상 이미지 뒤에 다른 파일을 이어 붙인 폴리글랏(JPEG+ZIP, JPEG+HTML 등)의 덧붙인 부분이 사라진다.
- EXIF 등 메타데이터(촬영 위치 GPS, 기기 정보, 주석에 심은 문자열)가 제거된다.
- 저장되는 형식·content-type이 항상 image/jpeg로 고정돼, 클라이언트가 보낸 헤더와 실제 내용이 어긋나지 않는다.

그 밖에 본문 크기(스트리밍 중 초과 즉시 중단), 픽셀 수(압축 폭탄), 프레임 수를 제한한다.
"""

from io import BytesIO
import logging

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

MAX_FILE_SIZE = 10 * 1024 * 1024   # 업로드 본문 10MB
MAX_PIXELS = 40_000_000            # 디코딩 전 가로×세로 상한(작은 파일이 거대한 비트맵으로 풀리는 압축 폭탄 차단)
MAX_SIDE = 3000                    # 저장본의 긴 변(px) — 영수증 글자 읽기에 충분
SANITIZED_MIME = "image/jpeg"
_READ_CHUNK = 256 * 1024

# Pillow 자체 안전장치도 같은 기준으로 맞춘다(이 값의 2배를 넘으면 Pillow가 예외를 던진다).
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

_INVALID = HTTPException(status_code=400, detail="유효한 이미지 파일이 아닙니다")


async def read_upload(file: UploadFile) -> bytes:
    """업로드 파일을 크기 제한 안에서 읽고, 정화된 JPEG 바이트를 돌려준다(검증 실패 시 400/413)."""
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="jpg, png, webp만 지원합니다")

    # 전체를 한 번에 읽지 않고 조각 단위로 읽다가 한도를 넘는 순간 중단한다(메모리 고갈 방지).
    chunks, size = [], 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="파일 크기는 10MB 이하여야 합니다")
        chunks.append(chunk)
    if size == 0:
        raise _INVALID
    return sanitize_image(b"".join(chunks))


def sanitize_image(contents: bytes) -> bytes:
    """실제 이미지인지 확인하고 메타데이터 없는 새 JPEG으로 다시 인코딩한다. 아니면 400."""
    try:
        # 1) 구조 검사 — verify()는 픽셀을 풀지 않고 파일 구조만 확인하며, 호출 뒤에는 객체를 다시 열어야 한다.
        probe = Image.open(BytesIO(contents))
        fmt = (probe.format or "").upper()
        width, height = probe.size
        frames = getattr(probe, "n_frames", 1)
        probe.verify()
    except HTTPException:
        raise
    except Exception:
        raise _INVALID

    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="jpg, png, webp 이미지만 지원합니다")
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise HTTPException(status_code=400, detail="이미지가 너무 큽니다")
    if frames > 1:
        # 움직이는 이미지(APNG/애니메이션 WebP)는 영수증일 수 없고 프레임 수만큼 디코딩 비용이 든다.
        raise HTTPException(status_code=400, detail="움직이는 이미지는 지원하지 않습니다")

    try:
        # 2) 실제 디코딩 — 여기서 깨진/위조된 픽셀 데이터가 걸러진다.
        img = Image.open(BytesIO(contents))
        if fmt == "JPEG":
            img.draft("RGB", (MAX_SIDE, MAX_SIDE))  # 큰 JPEG은 줄인 크기로 바로 디코딩(메모리 절약)
        img = ImageOps.exif_transpose(img)           # 메타데이터를 지우기 전에 촬영 방향을 픽셀에 반영
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            # 투명 영역은 흰 배경으로 합친다(JPEG은 투명도를 못 담는다)
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
            img = flat
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))

        # 3) 픽셀만 새 이미지로 옮긴 뒤 다시 인코딩한다. Pillow는 저장할 때 원본 객체의 info(JPEG 주석,
        #    ICC 프로파일 등)를 따라 써 주기 때문에, 원본 객체를 그대로 저장하면 주석에 심은 문자열이 남는다.
        clean = Image.new("RGB", img.size)
        clean.paste(img)
        out = BytesIO()
        clean.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"IMAGE_REJECTED format={fmt} size={width}x{height} reason={type(e).__name__}")
        raise _INVALID


def verify_image(contents: bytes) -> None:
    """(하위 호환) 유효한 이미지인지만 확인한다. 저장·전달에는 sanitize_image의 결과를 써야 한다."""
    sanitize_image(contents)
