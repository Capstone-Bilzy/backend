from fastapi import APIRouter, Depends, Response, Request
from models.schemas import CreateSettlementRequest, UpdateSettlementRequest, UpdateStatusRequest, AddMemberRequest, CalculateRequest
from services import settlement_service, ai_service, qr_service
from core.security import get_current_user
from core.limiter import limiter

router = APIRouter(prefix="/settlements", tags=["정산방"])


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


@router.delete("/{settlement_id}")
async def delete(settlement_id: str, current_user=Depends(get_current_user)):
    await settlement_service.delete_settlement(settlement_id, current_user["id"])
    return {"message": "삭제 완료"}


@router.delete("/{settlement_id}/receipt")
async def delete_receipt(settlement_id: str, current_user=Depends(get_current_user)):
    """정산건의 영수증 이미지 삭제 — 앱에서 '저장 안 함'/'다시 찍기' 선택 시."""
    await settlement_service.delete_receipt_image(settlement_id, current_user["id"])
    return {"message": "영수증 이미지 삭제 완료"}


# 참여자
@router.post("/{settlement_id}/members")
async def add_member(settlement_id: str, body: AddMemberRequest, current_user=Depends(get_current_user)):
    return await settlement_service.add_member(
        settlement_id, current_user["id"], body.nickname, current_user["id"]
    )


@router.delete("/{settlement_id}/members/{member_user_id}")
async def remove_member(settlement_id: str, member_user_id: str, current_user=Depends(get_current_user)):
    await settlement_service.remove_member(settlement_id, member_user_id, current_user["id"])
    return {"message": "제거 완료"}


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


# QR
@router.get("/{settlement_id}/qr")
async def get_qr(settlement_id: str, current_user=Depends(get_current_user)):
    png = await qr_service.generate_qr(settlement_id, current_user["id"])
    return Response(content=png, media_type="image/png")


@router.post("/{settlement_id}/join")
async def join(settlement_id: str, body: AddMemberRequest, current_user=Depends(get_current_user)):
    return await qr_service.join_by_qr(settlement_id, body.nickname, current_user["id"])


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
        .select("id").eq("id", settlement_id).eq("created_by", current_user["id"]).execute()
    if not settlement.data:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    result = supabase_admin.table("settlement_members").update({
        "amount": body.amount
    }).eq("id", member_id).eq("settlement_id", settlement_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="참여자를 찾을 수 없습니다")

    return result.data[0]

