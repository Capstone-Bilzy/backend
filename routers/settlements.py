from fastapi import APIRouter, Depends, Response
from models.schemas import CreateSettlementRequest, UpdateStatusRequest, AddMemberRequest, CalculateRequest
from services import settlement_service, ai_service, qr_service
from core.security import get_current_user

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


@router.delete("/{settlement_id}")
async def delete(settlement_id: str, current_user=Depends(get_current_user)):
    await settlement_service.delete_settlement(settlement_id, current_user["id"])
    return {"message": "삭제 완료"}


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
async def calculate(settlement_id: str, body: CalculateRequest, current_user=Depends(get_current_user)):
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
