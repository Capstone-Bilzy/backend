from fastapi import APIRouter, Depends, Response, Request, Query, Path
from models.schemas import (
    CreateSettlementRequest, UpdateSettlementRequest, UpdateStatusRequest, AddMemberRequest,
    CalculateRequest, SetMemberRoundsRequest, SetRoundAdjustmentRequest, SetMemberCapacityRequest,
    RenameExtraPhotoRequest
)
from services import settlement_service, ai_service, qr_service
from core.security import get_current_user
from core.ids import require_uuid_path_params
from core.limiter import limiter

router = APIRouter(prefix="/settlements", tags=["정산방"], dependencies=[Depends(require_uuid_path_params)])


@router.post("")
async def create(body: CreateSettlementRequest, current_user=Depends(get_current_user)):
    return await settlement_service.create_settlement(body.title, current_user["id"])


@router.get("/{settlement_id}")
async def get(settlement_id: str, current_user=Depends(get_current_user)):
    return await settlement_service.get_settlement(settlement_id, current_user["id"])


@router.patch("/{settlement_id}/status")
async def update_status(settlement_id: str, body: UpdateStatusRequest, current_user=Depends(get_current_user)):
    return await settlement_service.update_status(settlement_id, body.status, current_user["id"])


@router.patch("/{settlement_id}")
async def update(settlement_id: str, body: UpdateSettlementRequest, current_user=Depends(get_current_user)):
    return await settlement_service.update_settlement(settlement_id, body.title, current_user["id"])


@router.patch("/{settlement_id}/capacity")
@limiter.limit("30/minute")
async def set_capacity(
    request: Request, settlement_id: str, body: SetMemberCapacityRequest, current_user=Depends(get_current_user)
):
    """PeopleCount 화면에서 방장이 정한 정원 저장 — 이후 join이 이 값을 넘지 못하게 막는다."""
    return await settlement_service.set_member_capacity(settlement_id, body.member_capacity, current_user["id"])


@router.patch("/{settlement_id}/extra-photos/{photo_id}")
@limiter.limit("30/minute")
async def rename_extra_photo(
    request: Request, settlement_id: str, photo_id: str, body: RenameExtraPhotoRequest,
    current_user=Depends(get_current_user)
):
    """첨부한 영수증 사진 이름 변경 — 방장 전용(정산내역 상세의 ⋯ 메뉴)."""
    return await settlement_service.rename_extra_photo(settlement_id, photo_id, body.name, current_user["id"])


@router.delete("/{settlement_id}")
async def delete(settlement_id: str, current_user=Depends(get_current_user)):
    await settlement_service.delete_settlement(settlement_id, current_user["id"])
    return {"message": "삭제 완료"}


@router.delete("/{settlement_id}/receipt")
async def delete_receipt(
    settlement_id: str, round: int = Query(default=1, gt=0, le=100), current_user=Depends(get_current_user)
):
    """정산건의 특정 라운드 영수증 이미지 삭제 — 앱에서 '저장 안 함'/'다시 찍기' 선택 시."""
    await settlement_service.delete_receipt_image(settlement_id, round, current_user["id"])
    return {"message": "영수증 이미지 삭제 완료"}


@router.delete("/{settlement_id}/rounds/{round}")
@limiter.limit("30/minute")
async def delete_round(
    request: Request, settlement_id: str, round: int = Path(gt=0, le=100), current_user=Depends(get_current_user)
):
    """정산방의 특정 차수(영수증+항목)를 삭제하고 뒤 차수 번호를 당긴다 — 방장 전용(영수증 목록 화면 ✕)."""
    return await settlement_service.delete_round(settlement_id, round, current_user["id"])


# 참여자
@router.post("/{settlement_id}/members")
@limiter.limit("20/minute")
async def add_member(request: Request, settlement_id: str, body: AddMemberRequest, current_user=Depends(get_current_user)):
    return await settlement_service.add_member(
        settlement_id, current_user["id"], body.nickname, current_user["id"], body.invite_token
    )


@router.delete("/{settlement_id}/members/{member_user_id}")
async def remove_member(settlement_id: str, member_user_id: str, current_user=Depends(get_current_user)):
    await settlement_service.remove_member(settlement_id, member_user_id, current_user["id"])
    return {"message": "제거 완료"}


# 참여자 본인의 라운드 참여/조정 (RoundPick, AmountAdjust 화면)
@router.patch("/{settlement_id}/members/me/rounds")
@limiter.limit("30/minute")
async def set_my_rounds(
    request: Request, settlement_id: str, body: SetMemberRoundsRequest, current_user=Depends(get_current_user)
):
    return await settlement_service.set_member_rounds(settlement_id, current_user["id"], body.rounds)


@router.patch("/{settlement_id}/members/me/rounds/{round}")
@limiter.limit("30/minute")
async def set_my_round_adjustment(
    request: Request,
    settlement_id: str,
    round: int = Path(gt=0, le=100),
    body: SetRoundAdjustmentRequest = ...,
    current_user=Depends(get_current_user),
):
    return await settlement_service.set_member_round_adjustment(
        settlement_id, current_user["id"], round, body.excluded_item_names
    )


@router.patch("/{settlement_id}/members/me/ready")
@limiter.limit("30/minute")
async def set_my_ready(request: Request, settlement_id: str, current_user=Depends(get_current_user)):
    """AmountAdjust 화면에서 "정산 시작하기"를 누르면 호출 — 다른 멤버들이 CalculatingFragment에서
    이 사람의 준비 완료 여부를 실시간으로 볼 수 있게 한다."""
    return await settlement_service.set_member_ready(settlement_id, current_user["id"])


# AI 정산
@router.post("/{settlement_id}/calculate")
@limiter.limit("10/minute")  # Gemini 텍스트 호출 — 비용 발생, 남용 차단
async def calculate(request: Request, settlement_id: str, body: CalculateRequest, current_user=Depends(get_current_user)):
    return await ai_service.calculate_split(settlement_id, body.ai_note, current_user["id"])


@router.get("/{settlement_id}/result")
async def get_result(settlement_id: str, current_user=Depends(get_current_user)):
    return await ai_service.get_result(settlement_id, current_user["id"])


@router.post("/{settlement_id}/done")
async def done(settlement_id: str, current_user=Depends(get_current_user)):
    return await settlement_service.mark_done(settlement_id, current_user["id"])


# QR — 클라이언트는 QR을 로컬(ZXing)에서 직접 생성해 이 엔드포인트를 쓰지 않는다(죽은 엔드포인트).
# 그래도 외부에서 호출 가능한 채로 남아있어 다른 인증된 엔드포인트와 동일하게 rate limit을 건다.
@router.get("/{settlement_id}/qr")
@limiter.limit("30/minute")
async def get_qr(request: Request, settlement_id: str, current_user=Depends(get_current_user)):
    png = await qr_service.generate_qr(settlement_id, current_user["id"])
    return Response(content=png, media_type="image/png")


@router.post("/{settlement_id}/join")
@limiter.limit("20/minute")
async def join(request: Request, settlement_id: str, body: AddMemberRequest, current_user=Depends(get_current_user)):
    return await qr_service.join_by_qr(settlement_id, body.nickname, current_user["id"], body.invite_token)


@router.post("/{settlement_id}/invite-token")
@limiter.limit("30/minute")
async def issue_invite_token(
    request: Request, settlement_id: str, regenerate: bool = False, current_user=Depends(get_current_user)
):
    """서명+24시간 만료 초대 토큰 발급 (방장만 가능).

    regenerate=True면 invite_epoch를 올려 기존에 뿌려진 토큰을 전부 무효화한 뒤 새로 발급한다.
    """
    return await qr_service.create_invite_token(settlement_id, current_user["id"], regenerate)


from pydantic import BaseModel, Field

class AdjustAmountRequest(BaseModel):
    amount: int = Field(gt=0, lt=10_000_000)


# 참여자별 금액 수동 조정 (amountAdjust1/2 화면)
@router.patch("/{settlement_id}/members/{member_id}/amount")
async def adjust_amount(
    settlement_id: str,
    member_id: str,
    body: AdjustAmountRequest,
    current_user=Depends(get_current_user)
):
    from core.database import supabase_admin
    from fastapi import HTTPException

    # 방장만 조정 가능
    settlement = supabase_admin.table("settlements") \
        .select("id, status").eq("id", settlement_id).eq("created_by", current_user["id"]).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    # 계산이 시작된 뒤에는 금액을 손으로 바꿀 수 없다(차수별 금액과 어긋나고, 완료된 정산이 바뀐다).
    settlement_service.ensure_not_locked(settlement.data[0])

    result = supabase_admin.table("settlement_members").update({
        "amount": body.amount
    }).eq("id", member_id).eq("settlement_id", settlement_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="참여자를 찾을 수 없습니다")

    return result.data[0]

