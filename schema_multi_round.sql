-- 다차(n차) 정산 마이그레이션: 정산방 1:1 영수증 → 영수증(라운드) 1:N 구조.
-- 기존 Supabase 인스턴스에 적용. 아직 프로덕션 데이터가 없는 개발 단계로 간주하고
-- 기존 컬럼 보존 로직 없이 정리한다 (supabase_schema.sql의 최신 정의와 동일한 결과를 만든다).

create table if not exists receipts (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid references settlements(id) on delete cascade,
  round int not null,
  store_name text,
  receipt_image_url text,
  receipt_text text,
  total_amount int default 0,
  created_at timestamptz default now(),
  unique(settlement_id, round)
);
create index if not exists idx_receipts_settlement_id on receipts(settlement_id);

alter table receipt_items add column if not exists receipt_id uuid references receipts(id) on delete cascade;
alter table receipt_items drop column if exists settlement_id;
create index if not exists idx_receipt_items_receipt_id on receipt_items(receipt_id);

create table if not exists settlement_member_rounds (
  id uuid primary key default gen_random_uuid(),
  settlement_member_id uuid references settlement_members(id) on delete cascade,
  round int not null,
  excluded_item_names jsonb default '[]'::jsonb,
  amount int default 0,
  reason text,
  unique(settlement_member_id, round)
);
create index if not exists idx_settlement_member_rounds_member_id on settlement_member_rounds(settlement_member_id);

alter table settlements drop column if exists receipt_image_url;
alter table settlements drop column if exists receipt_text;

-- 백엔드는 항상 service role key(supabase_admin)로 접근해 RLS를 우회하므로 앱 동작에는 영향 없다.
-- anon/authenticated 키로 이 테이블에 직접 접근하는 경로만 기본 차단한다(정책 없음 = 전체 거부).
alter table receipts enable row level security;
alter table settlement_member_rounds enable row level security;
