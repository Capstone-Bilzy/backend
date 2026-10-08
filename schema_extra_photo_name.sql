-- 첨부한 영수증 사진에 방장이 붙이는 이름(정산내역 상세의 ⋯ → 이름 변경). 비어 있으면 앱이 "영수증 사진"으로 표시.
alter table settlement_extra_photos add column if not exists name text;
