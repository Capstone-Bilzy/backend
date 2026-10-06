from pydantic import BaseModel, Field, conint, constr
from typing import Optional, List
from enum import Enum
from core.ids import UUID_PATTERN

# UUID 형식이 아닌 id는 DB까지 가지 않고 422로 거절한다(그대로 넘기면 500이 났다)
UuidStr = constr(pattern=UUID_PATTERN)


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

class OcrConfirmItem(BaseModel):
    # 예전엔 dict를 그대로 받아 서비스에서 조용히 고쳐 저장했다(음수 가격→0, 수량 0→1, 긴 이름 잘림,
    # 문자열 가격은 500). 이제 잘못된 값은 저장하지 않고 422로 돌려준다.
    name: constr(strip_whitespace=True, min_length=1, max_length=50)
    price: int = Field(ge=0, le=10_000_000)  # 0원(서비스 품목)은 허용
    quantity: int = Field(default=1, ge=1, le=100)


class OcrConfirmRequest(BaseModel):
    settlement_id: UuidStr
    round: int = Field(default=1, gt=0, le=100)
    store_name: str = Field(default="", max_length=50)
    items: List[OcrConfirmItem] = Field(min_length=1, max_length=200)

class AddItemRequest(BaseModel):
    settlement_id: UuidStr
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

class SetMemberCapacityRequest(BaseModel):
    member_capacity: conint(gt=0, le=100)

class AddMemberRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    invite_token: Optional[str] = Field(default=None, max_length=1000)

class CalculateRequest(BaseModel):
    ai_note: str = Field(max_length=500, default="")  # "철수 삼겹살 안먹음, 영희 30분 늦게 옴"

class SetMemberRoundsRequest(BaseModel):
    rounds: List[conint(gt=0, le=100)] = Field(default_factory=list, max_length=100)

class SetRoundAdjustmentRequest(BaseModel):
    excluded_item_names: List[constr(max_length=50)] = Field(default_factory=list, max_length=100)


# ===== User =====

class UpdateProfileRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
