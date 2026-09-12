-- 참여자별 "라운드 조정 완료" 플래그 추가.
-- CalculatingFragment가 방장 외 멤버들의 실시간 준비 상태를 보여주려면 필요하다.
alter table settlement_members add column if not exists ready boolean default false;
