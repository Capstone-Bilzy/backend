-- 초대 토큰 epoch 원자적 증가.
-- 기존 qr_service.create_invite_token()의 "읽고 +1 해서 쓰기"는 동시에 두 번
-- regenerate가 호출되면(예: 방장이 QR 다시 만들기를 빠르게 두 번 누름) 경쟁 상태로
-- 증가분 하나가 유실될 수 있었다. DB에서 단일 UPDATE...RETURNING으로 원자적으로 처리.
-- 소유자가 아니거나 정산방이 없으면 매칭되는 행이 없어 NULL을 반환한다(서비스 코드가 403 처리).
create or replace function increment_invite_epoch(p_settlement_id uuid, p_owner_id uuid)
returns int
language sql
as $$
  update settlements
  set invite_epoch = coalesce(invite_epoch, 1) + 1
  where id = p_settlement_id and created_by = p_owner_id
  returning invite_epoch;
$$;
