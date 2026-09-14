import qrcode
from io import BytesIO
from fastapi import HTTPException
from core.database import supabase_admin
from core.security import create_invite_token as _create_invite_jwt

try:
    from qrcode.image.styledimage import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    STYLED_QR = True
except ImportError:
    STYLED_QR = False


async def create_invite_token(settlement_id: str, user_id: str, regenerate: bool = False) -> dict:
    """서명+만료 초대 토큰 발급. 방장만 가능(IDOR 방어).

    regenerate=False(기본): 화면 진입/회전마다 호출돼도 안전해야 하므로 현재
    invite_epoch를 읽기만 하고 절대 올리지 않는다(이미 공유된 QR이 계속 유효해야 함).
    regenerate=True: 사용자가 명시적으로 "QR 다시 만들기"를 눌렀을 때만 호출되며,
    invite_epoch를 +1 해서 그 이전 epoch로 서명된 모든 토큰을 무효화한다.
    """
    from services.settlement_service import _check_owner
    settlement_row = _check_owner(settlement_id, user_id)

    epoch = settlement_row.get("invite_epoch", 1)
    if regenerate:
        epoch += 1
        supabase_admin.table("settlements") \
            .update({"invite_epoch": epoch}).eq("id", settlement_id).execute()

    token, expires_at = _create_invite_jwt(settlement_id, epoch=epoch)
    return {
        "token": token,
        "deep_link": f"bilzy://join/{settlement_id}?token={token}",
        "expires_at": expires_at,
        "expires_in": 86400,
        "invite_epoch": epoch,
    }


async def generate_qr(settlement_id: str, user_id: str) -> bytes:
    # 초대 QR은 방장만 발급할 수 있게 제한(IDOR 방어).
    invite = await create_invite_token(settlement_id, user_id)
    deep_link = invite["deep_link"]

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


async def join_by_qr(settlement_id: str, nickname: str, user_id: str, invite_token: str | None = None) -> dict:
    from services.settlement_service import add_member
    return await add_member(settlement_id, user_id, nickname, user_id, invite_token)