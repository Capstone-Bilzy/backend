from pydantic import BaseModel, Field, conint, constr
from typing import Optional, List
from enum import Enum


# ===== Auth =====

class SocialProvider(str, Enum):
    kakao = "kakao"
    naver = "naver"

class SocialLoginRequest(BaseModel):
    provider: SocialProvider
    access_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: dict

class RefreshRequest(BaseModel):
    refresh_token: str


# ===== OCR =====

class OcrConfirmRequest(BaseModel):
    settlement_id: str
    round: int = Field(default=1, gt=0, le=100)
    store_name: str = Field(default="", max_length=50)
    items: List[dict]  # [{ name, price, quantity }]

class AddItemRequest(BaseModel):
    settlement_id: str
    round: int = Field(default=1, gt=0, le=100)
    name: str = Field(min_length=1, max_length=50)
    price: int = Field(gt=0, lt=10_000_000)
    quantity: int = Field(gt=0, lt=100)


# ===== Settlement =====

class SettlementStatus(str, Enum):
    scanning = "scanning"
    waiting = "waiting"
    calculating = "calculating"
    calculated = "calculated"
    done = "done"

class CreateSettlementRequest(BaseModel):
    title: str = Field(min_length=1, max_length=50)

class UpdateSettlementRequest(BaseModel):
    title: str = Field(min_length=1, max_length=50)

class UpdateStatusRequest(BaseModel):
    status: SettlementStatus

class AddMemberRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)

class CalculateRequest(BaseModel):
    ai_note: str = Field(max_length=500, default="")  # "철수 삼겹살 안먹음, 영희 30분 늦게 옴"

class SetMemberRoundsRequest(BaseModel):
    rounds: List[conint(gt=0, le=100)] = Field(default_factory=list, max_length=100)

class SetRoundAdjustmentRequest(BaseModel):
    excluded_item_names: List[constr(max_length=50)] = Field(default_factory=list, max_length=100)


# ===== User =====

class UpdateProfileRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
