from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from core.security import get_current_user
from services.account_service import get_account, upsert_account

router = APIRouter(prefix="/users", tags=["계좌"])


class AccountRequest(BaseModel):
    bank_name: str = Field(min_length=1, max_length=20)
    account_number: str = Field(min_length=10, max_length=30)
    account_holder: str = Field(min_length=1, max_length=20)


@router.get("/me/account")
async def get_my_account(request: Request, current_user=Depends(get_current_user)):
    return await get_account(current_user["id"], request)


@router.post("/me/account")
async def upsert_my_account(body: AccountRequest, request: Request, current_user=Depends(get_current_user)):
    return await upsert_account(
        current_user["id"],
        body.bank_name,
        body.account_number,
        body.account_holder,
        request
    )
