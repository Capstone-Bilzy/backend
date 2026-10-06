import uuid
from fastapi import HTTPException, Request

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


async def require_uuid_path_params(request: Request):
    """경로의 *_id 값이 UUID 형식이 아니면 DB까지 가지 않고 404로 끝낸다.

    형식이 틀린 id를 그대로 Supabase에 넘기면 uuid 파싱 오류가 500으로 새어 나왔다
    (예: GET /settlements/not-a-uuid).
    """
    for name, value in request.path_params.items():
        if name.endswith("_id") and not is_uuid(str(value)):
            raise HTTPException(status_code=404, detail="찾을 수 없습니다")
