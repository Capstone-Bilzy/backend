"""정산 금액 계산(규칙 계산) 테스트 — 외부 호출 없이 돈다.

실행: python3 -m unittest discover -s tests -v
"""
import os
import unittest

# services 모듈이 설정(.env)과 DB 클라이언트를 임포트하므로, 값이 없는 환경에서도 돌도록 기본값을 채운다.
for key, value in {
    "SUPABASE_URL": "http://localhost", "SUPABASE_ANON_KEY": "x", "SUPABASE_SERVICE_KEY": "x",
    "JWT_SECRET": "x" * 32, "GEMINI_API_KEY": "x",
}.items():
    os.environ.setdefault(key, value)

from services.ai_service import calculate_without_ai  # noqa: E402
from services.ocr_service import item_total  # noqa: E402


def person(name, *excluded):
    return {"nickname": name, "excluded_items": list(excluded)}


def amounts(result, round_no=1):
    block = next(r for r in result["rounds"] if r["round"] == round_no)
    return {r["nickname"]: r["amount"] for r in block["results"]}


class SplitRules(unittest.TestCase):
    def test_even_split(self):
        result = calculate_without_ai([{
            "round": 1, "items": [{"name": "피자", "amount": 20000}],
            "participants": [person("가"), person("나")],
        }])
        self.assertEqual(amounts(result), {"가": 10000, "나": 10000})

    def test_excluded_item_is_paid_by_the_others(self):
        result = calculate_without_ai([{
            "round": 1,
            "items": [{"name": "피자", "amount": 20000}, {"name": "맥주", "amount": 10000}],
            "participants": [person("가", "맥주"), person("나")],
        }])
        self.assertEqual(amounts(result), {"가": 10000, "나": 20000})

    def test_item_everyone_excluded_is_split_by_all(self):
        result = calculate_without_ai([{
            "round": 1, "items": [{"name": "맥주", "amount": 9000}],
            "participants": [person("가", "맥주"), person("나", "맥주"), person("다", "맥주")],
        }])
        self.assertEqual(amounts(result), {"가": 3000, "나": 3000, "다": 3000})

    def test_remainder_keeps_round_total_exact(self):
        result = calculate_without_ai([{
            "round": 1, "items": [{"name": "세트", "amount": 10000}],
            "participants": [person("가"), person("나"), person("다")],
        }])
        got = amounts(result)
        self.assertEqual(sum(got.values()), 10000)
        self.assertEqual(sorted(got.values()), [3333, 3333, 3334])

    def test_only_round_participants_pay(self):
        result = calculate_without_ai([
            {"round": 1, "items": [{"name": "피자", "amount": 20000}],
             "participants": [person("가"), person("나")]},
            {"round": 2, "items": [{"name": "커피", "amount": 9000}],
             "participants": [person("가")]},
        ])
        self.assertEqual(amounts(result, 1), {"가": 10000, "나": 10000})
        self.assertEqual(amounts(result, 2), {"가": 9000})

    def test_every_round_sums_to_its_receipt(self):
        rounds = [
            {"round": 1,
             "items": [{"name": "삼겹살", "amount": 160000}, {"name": "냉면", "amount": 45000},
                       {"name": "소주", "amount": 30000}, {"name": "세트", "amount": 10001}],
             "participants": [person("가", "냉면"), person("나", "소주", "냉면"), person("다"),
                              person("라", "소주"), person("마"), person("바", "세트")]},
            {"round": 2, "items": [{"name": "안주", "amount": 143000}],
             "participants": [person("가"), person("나"), person("다"), person("라"), person("마")]},
        ]
        result = calculate_without_ai(rounds)
        for r in rounds:
            self.assertEqual(sum(amounts(result, r["round"]).values()), sum(i["amount"] for i in r["items"]))

    def test_round_without_participants(self):
        result = calculate_without_ai([{"round": 1, "items": [{"name": "피자", "amount": 20000}], "participants": []}])
        self.assertEqual(result["rounds"][0]["results"], [])


class ItemTotal(unittest.TestCase):
    def test_unit_price_times_quantity(self):
        self.assertEqual(item_total({"price": 3000, "quantity": 3}), 9000)

    def test_line_amount_wins_when_not_divisible(self):
        # 3개 10,000원: 단가 3,333 × 3 = 9,999가 아니라 적어 둔 금액 그대로
        self.assertEqual(item_total({"price": 3333, "quantity": 3, "line_amount": 10000}), 10000)


if __name__ == "__main__":
    unittest.main()
