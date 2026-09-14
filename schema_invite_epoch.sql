-- 초대 QR/링크 무효화(revocation)를 위한 epoch 컬럼.
-- 방장이 "QR 다시 만들기"를 누르면 이 값을 +1 해서 이전 epoch로 서명된 초대 토큰을 전부 무효화한다.
alter table settlements add column if not exists invite_epoch integer not null default 1;
