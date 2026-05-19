"""
개인정보 보관기간 자동 파기
- 개인정보보호법 제21조: 개인정보 파기 의무
- 1년 미접속 계정 자동 파기 (서비스 미이용자 통보 후 파기)
- Render cron job 또는 수동 실행
"""

from datetime import datetime, timedelta
from core.database import supabase_admin
import logging

logger = logging.getLogger(__name__)

INACTIVE_DAYS = 365  # 1년 미접속 시 파기


async def purge_inactive_users():
    """1년 미접속 계정 파기"""
    cutoff = (datetime.utcnow() - timedelta(days=INACTIVE_DAYS)).isoformat()

    # 마지막 로그인이 1년 이전인 유저 조회
    result = supabase_admin.table("users") \
        .select("id").lt("last_login_at", cutoff).execute()

    inactive_ids = [u["id"] for u in result.data or []]
    if not inactive_ids:
        logger.info("RETENTION: 파기 대상 없음")
        return 0

    # 연관 데이터 파기
    for user_id in inactive_ids:
        from services.user_service import delete_account
        await delete_account(user_id)

    logger.info(f"RETENTION: {len(inactive_ids)}명 계정 자동 파기 완료")
    return len(inactive_ids)


async def purge_old_receipts():
    """정산 완료 후 90일 지난 영수증 이미지 파기"""
    cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()

    old = supabase_admin.table("settlements") \
        .select("id, receipt_image_url") \
        .eq("status", "done") \
        .lt("created_at", cutoff) \
        .not_.is_("receipt_image_url", "null") \
        .execute()

    count = 0
    for s in old.data or []:
        try:
            path = s["receipt_image_url"].split("/receipts/")[-1]
            supabase_admin.storage.from_("receipts").remove([f"receipts/{path}"])
            supabase_admin.table("settlements").update(
                {"receipt_image_url": None}
            ).eq("id", s["id"]).execute()
            count += 1
        except Exception as e:
            logger.error(f"Receipt purge failed for {s['id']}: {e}")

    logger.info(f"RETENTION: 영수증 이미지 {count}건 파기 완료")
    return count
