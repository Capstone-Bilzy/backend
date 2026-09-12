"""
기말 시연용 더미 데이터 시드 스크립트

사용법:
  1. Supabase 대시보드 → Table Editor → users 테이블에서 본인 id(UUID) 복사
  2. 실행:
       cd "Desktop/2026/26-1/디미 캡스톤/bilzy"
       python seed_demo.py <USER_ID>
       예) python seed_demo.py a1b2c3d4-...

생성 내역:
  - 완료된 정산 3건 (홈 화면 "최근 정산 내역" 채우기용)
  - 대기 중 정산 1건 (OCR 실패 시 백업용 — settlement_id 출력됨)
"""

import sys
import os
import asyncio
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.database import supabase_admin


def iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def insert_settlement(title: str, status: str, total: int, days_ago: int, created_by: str) -> str:
    result = supabase_admin.table("settlements").insert({
        "title": title,
        "created_by": created_by,
        "status": status,
        "total_amount": total,
        "created_at": iso(days_ago),
    }).execute()
    return result.data[0]["id"]


def insert_items(settlement_id: str, items: list[dict]):
    rows = [{"settlement_id": settlement_id, **item} for item in items]
    supabase_admin.table("receipt_items").insert(rows).execute()


def insert_member(settlement_id: str, user_id: str, nickname: str, amount: int, reason: str | None = None):
    try:
        supabase_admin.table("settlement_members").insert({
            "settlement_id": settlement_id,
            "user_id": user_id,
            "nickname": nickname,
            "amount": amount,
            "reason": reason,
        }).execute()
    except Exception:
        pass  # 중복 무시


def insert_history(settlement_id: str, user_id: str):
    try:
        supabase_admin.table("history").upsert(
            {"settlement_id": settlement_id, "user_id": user_id},
            on_conflict="settlement_id,user_id"
        ).execute()
    except Exception:
        pass


def seed(user_id: str):
    print(f"\n[시드 시작] user_id={user_id[:8]}***\n")

    # ── 1. 완료된 정산 3건 (홈 화면 히스토리) ──────────────────────────────

    # 1-1) 치킨 배달
    sid1 = insert_settlement("치킨 시켜먹기", "done", 43000, days_ago=5, created_by=user_id)
    insert_items(sid1, [
        {"name": "황금올리브 1마리", "price": 20000, "quantity": 1},
        {"name": "레드윙 1마리", "price": 20000, "quantity": 1},
        {"name": "콜라 1.25L", "price": 3000, "quantity": 1},
    ])
    insert_member(sid1, user_id, "나", 14334, "배달비 추가 부담")
    insert_history(sid1, user_id)
    print(f"  ✓ 치킨 시켜먹기 (43,000원, done) → {sid1}")

    # 1-2) 카페 스터디
    sid2 = insert_settlement("카페 스터디 정산", "done", 27500, days_ago=3, created_by=user_id)
    insert_items(sid2, [
        {"name": "아메리카노", "price": 4500, "quantity": 2},
        {"name": "카페라떼", "price": 5500, "quantity": 2},
        {"name": "케이크", "price": 7000, "quantity": 1},
        {"name": "쿠키", "price": 1500, "quantity": 2},
    ])
    insert_member(sid2, user_id, "나", 6875)
    insert_history(sid2, user_id)
    print(f"  ✓ 카페 스터디 정산 (27,500원, done) → {sid2}")

    # 1-3) 삼겹살 회식
    sid3 = insert_settlement("삼겹살 회식", "done", 156000, days_ago=10, created_by=user_id)
    insert_items(sid3, [
        {"name": "삼겹살 400g", "price": 18000, "quantity": 4},
        {"name": "목살 200g", "price": 12000, "quantity": 2},
        {"name": "소주", "price": 5000, "quantity": 4},
        {"name": "공기밥", "price": 1000, "quantity": 4},
    ])
    insert_member(sid3, user_id, "나", 31200)
    insert_history(sid3, user_id)
    print(f"  ✓ 삼겹살 회식 (156,000원, done) → {sid3}")

    # ── 2. 대기 중 정산 1건 (OCR 실패 시 시연 백업용) ──────────────────────

    sid_demo = insert_settlement("기말 뒷풀이", "waiting", 89000, days_ago=0, created_by=user_id)
    insert_items(sid_demo, [
        {"name": "마라탕", "price": 13000, "quantity": 3},
        {"name": "탕수육", "price": 18000, "quantity": 1},
        {"name": "볶음밥", "price": 9000, "quantity": 2},
        {"name": "음료", "price": 3000, "quantity": 3},
    ])
    insert_member(sid_demo, user_id, "나", 0)
    print(f"\n  ★ [백업용] 기말 뒷풀이 (89,000원, waiting)")
    print(f"    settlement_id = {sid_demo}")
    print(f"    → OCR 실패 시 이 ID로 정산방 바로 진행 가능\n")

    print("[ 완료 ] Supabase에 더미 데이터 삽입 완료!")
    print("\n시연 체크리스트:")
    print("  □ 홈 화면 새로고침 → 정산 내역 3건 확인")
    print("  □ 시연용 영수증 이미지 준비 (아래 권장 조건 참고)")
    print("  □ 게스트 역할 폰/계정 준비 (카카오 로그인 완료 상태)")
    print("  □ 백업용 settlement_id 메모해두기")
    print(f"\n  백업 ID: {sid_demo}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    seed(sys.argv[1])
