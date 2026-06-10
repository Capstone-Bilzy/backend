"""
개인정보 접근 로그
- 누가(user_id) 언제 어떤 데이터(resource)를 어떤 행위(action)로 접근했는지 기록
- 개인정보보호법 제29조: 접근 통제 및 접근 기록 보관 의무
"""

import asyncio
from datetime import datetime
from core.database import supabase_admin
from core.privacy import hash_ip
import logging

logger = logging.getLogger(__name__)

# fire-and-forget 태스크가 GC되지 않도록 참조 유지
_pending_logs: set = set()


def _write_log(record: dict):
    """동기 Supabase INSERT (스레드에서 실행). best-effort라 실패해도 무시."""
    try:
        supabase_admin.table("access_logs").insert(record).execute()
    except Exception as e:
        logger.error(f"Access log failed: {e}")


async def log_access(
    user_id: str,
    action: str,        # READ | CREATE | UPDATE | DELETE
    resource: str,      # users | settlements | receipt_items 등
    resource_id: str = None,
    ip: str = None,
):
    """
    접근 로그 기록. 감사 로그는 best-effort이므로 응답 경로를 막지 않도록
    백그라운드 스레드로 던지고 즉시 반환한다(동기 supabase 클라이언트가
    이벤트 루프를 막지 않게 to_thread 사용).
    """
    record = {
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "ip_hash": hash_ip(ip) if ip else None,  # IP는 해시처리
        "created_at": datetime.utcnow().isoformat(),
    }
    task = asyncio.create_task(asyncio.to_thread(_write_log, record))
    _pending_logs.add(task)
    task.add_done_callback(_pending_logs.discard)
