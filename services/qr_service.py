import qrcode
from io import BytesIO
from fastapi import HTTPException
from core.database import supabase_admin

try:
    from qrcode.image.styledimage import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    STYLED_QR = True
except ImportError:
    STYLED_QR = False


async def generate_qr(settlement_id: str, user_id: str) -> bytes:
    # 초대 QR은 방장만 발급할 수 있게 제한(IDOR 방어).
    from services.settlement_service import _check_owner
    _check_owner(settlement_id, user_id)

    deep_link = f"bilzy://join/{settlement_id}"

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2
    )
    qr.add_data(deep_link)
    qr.make(fit=True)

    if STYLED_QR:
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer()
        )
    else:
        img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def join_by_qr(settlement_id: str, nickname: str, user_id: str) -> dict:
    from services.settlement_service import add_member
    return await add_member(settlement_id, user_id, nickname, user_id)