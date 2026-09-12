-- Bilzy Supabase Schema
-- Supabase SQL Editor에서 실행

-- 유저 (개인정보 암호화 적용)
create table users (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  provider_id text not null,          -- HMAC-SHA256 가명처리된 값
  nickname text not null,             -- AES-256-GCM 암호화된 값
  profile_image_url text,             -- AES-256-GCM 암호화된 값
  last_login_at timestamptz default now(),  -- 보관기간 파기 기준
  created_at timestamptz default now(),
  unique(provider, provider_id)
);

-- Refresh Token 저장 (탈취 시 무효화용)
create table refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  token text not null,
  created_at timestamptz default now(),
  unique(user_id)
);

-- 정산방
create table settlements (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  created_by uuid references users(id) on delete cascade,
  status text default 'scanning',
  total_amount int default 0,  -- 모든 라운드(receipts) 합계
  ai_note text,                -- 마지막 계산 시 넘어온 특이사항(표시용)
  created_at timestamptz default now()
);

-- 영수증(라운드) — 정산방 1개가 여러 라운드(1차, 2차...)를 가질 수 있다
create table receipts (
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

-- 영수증 항목 (OCR 결과) — 라운드(receipts)에 속한다
create table receipt_items (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid references receipts(id) on delete cascade,
  name text not null,
  price int not null,
  quantity int default 1,
  created_at timestamptz default now()
);

-- 정산방 참여자
create table settlement_members (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid references settlements(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  nickname text not null,
  amount int default 0,   -- 전체 라운드 합산 금액
  reason text,
  ready boolean default false,  -- 본인 라운드 조정을 다 마치고 "정산 시작하기"를 눌렀는지
  joined_at timestamptz default now(),
  unique(settlement_id, user_id)
);

-- 참여자별 라운드 참여/조정/금액 — "이 사람이 몇 차에 참여했고, 뭘 안 먹었고, 그 차수에서 얼마 냈는지"
create table settlement_member_rounds (
  id uuid primary key default gen_random_uuid(),
  settlement_member_id uuid references settlement_members(id) on delete cascade,
  round int not null,
  excluded_item_names jsonb default '[]'::jsonb,
  amount int default 0,
  reason text,
  unique(settlement_member_id, round)
);

-- 정산 내역
create table history (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid references settlements(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  created_at timestamptz default now(),
  unique(settlement_id, user_id)
);

-- 보안 이벤트 로그 (IP는 해시처리)
create table security_logs (
  id uuid primary key default gen_random_uuid(),
  event text not null,
  ip_hash text,                       -- 평문 IP 저장 안 함 (SHA-256 해시)
  user_id uuid,
  detail text,
  created_at timestamptz default now()
);

-- 개인정보 접근 로그 (개인정보보호법 제29조)
create table access_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  action text not null,               -- READ | CREATE | UPDATE | DELETE
  resource text not null,             -- 테이블명
  resource_id text,
  ip_hash text,                       -- 해시처리된 IP
  created_at timestamptz default now()
);

-- 동의 이력 (개인정보보호법 제22조)
create table consent_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  consent_type text not null,         -- privacy_policy | marketing 등
  agreed boolean not null,
  agreed_at timestamptz not null,
  version text not null,              -- 처리방침 버전
  unique(user_id, consent_type)
);

-- 인덱스
create index on settlements(created_by);
create index on settlement_members(settlement_id);
create index on settlement_members(user_id);
create index on receipts(settlement_id);
create index on receipt_items(receipt_id);
create index on settlement_member_rounds(settlement_member_id);
create index on history(user_id);
create index on security_logs(created_at);
create index on access_logs(user_id);
create index on access_logs(created_at);
create index on users(last_login_at);  -- 보관기간 파기 쿼리용

-- 백엔드는 항상 service role key(supabase_admin)로 접근해 RLS를 우회하므로 앱 동작에는 영향 없다.
-- anon/authenticated 키로 직접 접근하는 경로만 기본 차단한다(정책 없음 = 전체 거부).
alter table receipts enable row level security;
alter table settlement_member_rounds enable row level security;
