from datetime import datetime
from core.database import supabase_admin
from core.privacy import hash_ip
import logging

logger = logging.getLogger(__name__)


async def log_security_event(
    event: str,
    ip: str,
    user_id: str = None,
    detail: str = None
):
    """보안 이벤트 기록 - IP는 해시처리 (개인정보보호법)"""
    try:
        supabase_admin.table("security_logs").insert({
            "event": event,
            "ip_hash": hash_ip(ip) if ip else None,  # 평문 IP 저장 안 함
            "user_id": user_id,
            "detail": detail,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Security log failed: {e}")
