"""
개인정보 보관기간 자동 파기 실행 스크립트.
Render Cron Job의 Start Command로 이 파일을 직접 실행한다: python scripts/run_retention.py
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.retention import purge_inactive_users, purge_old_receipts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    inactive_count = await purge_inactive_users()
    receipt_count = await purge_old_receipts()
    logger.info(f"RETENTION_RUN_COMPLETE inactive_users={inactive_count} old_receipts={receipt_count}")


if __name__ == "__main__":
    asyncio.run(main())
