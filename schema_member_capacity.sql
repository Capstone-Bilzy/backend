-- 정산방 정원(member_capacity) 컬럼.
-- 호스트가 PeopleCountFragment에서 정한 "총 몇 명과 나눌지"를 서버에 저장해,
-- join 시 정원을 초과하면 실제로 막을 수 있게 한다. NULL이면 정원 제한 없음(하위호환:
-- 이 기능 도입 이전에 만들어진 정산방은 전부 NULL로 남아 기존처럼 무제한 join 유지).
alter table settlements add column if not exists member_capacity integer;
