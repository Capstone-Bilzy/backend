"""
개인정보 접근 로그
- 누가(user_id) 언제 어떤 데이터(resource)를 어떤 행위(action)로 접근했는지 기록
- 개인정보보호법 제29조: 접근 통제 및 접근 기록 보관 의무
"""

from datetime import datetime
from core.database import supabase_admin
from core.privacy import hash_ip
import logging

logger = logging.getLogger(__name__)


async def log_access(
    user_id: str,
    action: str,        # READ | CREATE | UPDATE | DELETE
    resource: str,      # users | settlements | receipt_items 등
    resource_id: str = None,
    ip: str = None,
):
    try:
        supabase_admin.table("access_logs").insert({
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "ip_hash": hash_ip(ip) if ip else None,  # IP는 해시처리
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Access log failed: {e}")
