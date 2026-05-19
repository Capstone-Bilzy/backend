from fastapi import APIRouter, Depends, Request
from models.schemas import UpdateProfileRequest
from services import user_service
from core.security import get_current_user

router = APIRouter(prefix="/users", tags=["유저"])


@router.get("/me")
async def get_me(request: Request, current_user=Depends(get_current_user)):
    return await user_service.get_profile(current_user["id"], request)


@router.patch("/me")
async def update_me(body: UpdateProfileRequest, request: Request, current_user=Depends(get_current_user)):
    return await user_service.update_profile(current_user["id"], body.nickname, request)


@router.delete("/me")
async def delete_me(current_user=Depends(get_current_user)):
    await user_service.delete_account(current_user["id"])
    return {"message": "회원탈퇴 완료. 개인정보가 즉시 파기되었습니다."}


@router.get("/me/history")
async def get_history(request: Request, current_user=Depends(get_current_user)):
    return await user_service.get_history(current_user["id"], request)


@router.get("/me/history/{settlement_id}")
async def get_history_detail(settlement_id: str, request: Request, current_user=Depends(get_current_user)):
    return await user_service.get_history_detail(settlement_id, current_user["id"], request)
