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
  total_amount int default 0,
  receipt_image_url text,
  receipt_text text,
  ai_note text,
  created_at timestamptz default now()
);

-- 영수증 항목 (OCR 결과)
create table receipt_items (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid references settlements(id) on delete cascade,
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
  amount int default 0,
  reason text,
  joined_at timestamptz default now(),
  unique(settlement_id, user_id)
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
create index on receipt_items(settlement_id);
create index on history(user_id);
create index on security_logs(created_at);
create index on access_logs(user_id);
create index on access_logs(created_at);
create index on users(last_login_at);  -- 보관기간 파기 쿼리용
