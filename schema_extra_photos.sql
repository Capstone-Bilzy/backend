-- 완료된 정산방에도 순수 기록용으로 영수증 사진을 추가 저장하기 위한 테이블.
-- receipts(라운드)와 무관 — 정산 계산/참여자 몫에 전혀 영향을 주지 않는 "그냥 사진".
create table if not exists settlement_extra_photos (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid references settlements(id) on delete cascade,
  image_url text not null,
  uploaded_by uuid references users(id) on delete cascade,
  created_at timestamptz default now()
);

create index if not exists idx_settlement_extra_photos_settlement_id
  on settlement_extra_photos(settlement_id);
