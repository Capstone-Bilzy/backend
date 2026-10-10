"""
개인정보 보관기간 자동 파기
- 개인정보보호법 제21조: 개인정보 파기 의무
- 1년 미접속 계정 자동 파기 (서비스 미이용자 통보 후 파기)
- Render cron job 또는 수동 실행
"""

from datetime import datetime, timedelta
from core.database import supabase_admin
from core.storage import remove_receipt_file
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

    # receipt_image_url은 settlements가 아니라 다차 정산 재설계 이후 라운드별 receipts 테이블에 있음
    done_settlements = supabase_admin.table("settlements") \
        .select("id") \
        .eq("status", "done") \
        .lt("created_at", cutoff) \
        .execute()
    settlement_ids = [s["id"] for s in done_settlements.data or []]
    if not settlement_ids:
        logger.info("RETENTION: 파기 대상 없음")
        return 0

    old = supabase_admin.table("receipts") \
        .select("id, receipt_image_url") \
        .in_("settlement_id", settlement_ids) \
        .not_.is_("receipt_image_url", "null") \
        .execute()

    count = 0
    for r in old.data or []:
        try:
            remove_receipt_file(r["receipt_image_url"])
            supabase_admin.table("receipts").update(
                {"receipt_image_url": None}
            ).eq("id", r["id"]).execute()
            count += 1
        except Exception as e:
            logger.error(f"Receipt purge failed for {r['id']}: {e}")

    # 추가로 첨부한 사진도 같은 기준으로 지운다(예전엔 차수별 영수증만 대상이라 첨부 사진은 계속 남았다).
    extras = supabase_admin.table("settlement_extra_photos") \
        .select("id, image_url").in_("settlement_id", settlement_ids).execute()
    for p in extras.data or []:
        try:
            remove_receipt_file(p["image_url"])
            supabase_admin.table("settlement_extra_photos").delete().eq("id", p["id"]).execute()
            count += 1
        except Exception as e:
            logger.error(f"Extra photo purge failed for {p['id']}: {e}")

    logger.info(f"RETENTION: 영수증 이미지 {count}건 파기 완료")
    return count
