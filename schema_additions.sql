-- ① users 테이블에 계좌 정보 컬럼 추가
alter table users
  add column if not exists bank_name text,
  add column if not exists account_number text,   -- AES-256 암호화 저장
  add column if not exists account_holder text;

-- ② 영수증 저장 테이블 추가
create table if not exists saved_receipts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  image_url text not null,
  file_path text not null,
  created_at timestamptz default now()
);

create index if not exists on saved_receipts(user_id);

-- ③ consent_logs - 약관 항목 세분화
-- (기존 테이블 그대로 사용, consent_type 값만 추가)
-- privacy_policy   : 개인정보처리방침 (필수)
-- terms_of_service : 서비스 이용약관 (필수)
-- marketing        : 마케팅 수신 동의 (선택)

-- 기존 unique 제약 확인 후 이미 있으면 스킵
-- consent_logs 테이블은 기존 schema에 있으므로 그대로 사용
