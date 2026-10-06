-- 품목 한 줄의 금액(단가×수량으로 표현할 수 없는 경우만 채움).
-- 예: 3개 10,000원 → price=3333, quantity=3, line_amount=10000.
-- 비어 있으면(null) 지금까지처럼 price*quantity가 그 줄의 금액이다.
alter table receipt_items add column if not exists line_amount integer;
