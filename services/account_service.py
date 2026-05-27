from fastapi import HTTPException
from core.database import supabase_admin
from core.privacy import encrypt, decrypt
from core.access_logger import log_access
import logging

logger = logging.getLogger(__name__)


async def get_account(user_id: str, request=None) -> dict:
    result = supabase_admin.table("users") \
        .select("bank_name, account_number, account_holder") \
        .eq("id", user_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다")

    await log_access(user_id, "READ", "account", user_id,
                     request.client.host if request else None)

    data = result.data
    # 계좌번호 복호화 (금융정보 암호화 저장)
    return {
        "bank_name": data.get("bank_name", ""),
        "account_number": decrypt(data.get("account_number", "")),
        "account_holder": data.get("account_holder", "")
    }


async def upsert_account(user_id: str, bank_name: str, account_number: str, account_holder: str, request=None) -> dict:
    # 계좌번호 AES-256 암호화 저장 (금융정보)
    encrypted_account = encrypt(account_number)

    supabase_admin.table("users").update({
        "bank_name": bank_name,
        "account_number": encrypted_account,
        "account_holder": account_holder
    }).eq("id", user_id).execute()

    await log_access(user_id, "UPDATE", "account", user_id,
                     request.client.host if request else None)

    logger.info(f"ACCOUNT_UPDATED user={user_id[:8]}***")

    return {
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder
    }
