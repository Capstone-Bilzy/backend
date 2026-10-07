# Bilzy Backend

더치페이 앱 Bilzy의 FastAPI 백엔드

## 기술 스택

- **FastAPI** - 백엔드 프레임워크
- **Supabase** - PostgreSQL DB / Auth / Storage(영수증 이미지, private 버킷 + signed URL)
- **Google Gemini** - OCR(Vision) + AI 정산 계산(안 먹은 메뉴가 있을 때만, 결과는 서버 규칙 계산과 대조)
- **Render.com** - 배포

## 프로젝트 구조

```
bilzy/
├── main.py                  # FastAPI 앱 진입점
├── requirements.txt
├── supabase_schema.sql      # DB 스키마 (기본)
├── schema_additions.sql     # 계좌 컬럼 등 추가 스키마
├── schema_multi_round.sql   # 다차(n차) 정산: receipts / settlement_member_rounds
├── schema_member_ready.sql  # 참여자 준비완료(ready) 플래그
├── schema_invite_epoch.sql  # 초대 토큰 무효화용 invite_epoch
├── schema_invite_epoch_atomic.sql  # invite_epoch 원자적 증가 함수
├── schema_member_capacity.sql      # 정산방 정원
├── schema_extra_photos.sql         # 완료된 정산방 사진 첨부
├── schema_line_amount.sql          # 품목 줄 금액(수량 보존)
├── .env.example
├── core/
│   ├── config.py            # 환경변수 설정
│   ├── database.py          # Supabase 클라이언트
│   ├── security.py          # JWT 인증
│   ├── security_logger.py   # 보안 이벤트 로깅
│   ├── limiter.py           # Rate limit(slowapi) 설정
│   ├── image_validation.py  # 업로드 이미지 디코딩 검증 + 새 JPEG으로 재인코딩(메타데이터·덧붙인 데이터 제거)
│   ├── body_limit.py        # 요청 본문 크기 제한(업로드 12MB, 그 외 256KB) + 토큰 없는 업로드 차단
│   ├── ids.py               # 경로·본문의 id가 UUID 형식인지 검증
│   ├── gemini.py            # Gemini 호출(모델 여러 개를 순서대로 시도)
│   ├── storage.py           # private 버킷 signed URL 발급, 파일 삭제
│   ├── privacy.py           # 개인정보 암호화/가명처리/IP 해시
│   ├── access_logger.py     # 개인정보 접근 로그
│   └── retention.py         # 1년 미접속 계정 자동 파기
├── models/
│   └── schemas.py           # Pydantic 모델
├── routers/
│   ├── auth.py               # 인증 API
│   ├── ocr.py                # OCR API (라운드별)
│   ├── settlements.py        # 정산방 API (다차 정산, 초대 토큰 포함)
│   ├── users.py               # 유저 API
│   └── account_router.py     # 계좌 정보 API (/users/me/account)
└── services/
    ├── auth_service.py           # 카카오/네이버 소셜 로그인
    ├── ocr_service.py            # 영수증 이미지 처리(Gemini OCR)
    ├── settlement_service.py     # 정산방/라운드/멤버 관리
    ├── ai_service.py             # 정산 계산(규칙 계산 + Gemini, 결과 검증)
    ├── qr_service.py             # QR 코드 생성 + 초대 토큰 발급/검증
    ├── user_service.py           # 유저/내역 관리
    └── account_service.py        # 계좌 정보(AES-256-GCM 암호화)
```

## 로컬 실행

```bash
cp .env.example .env
# .env 파일에 키 입력 (SUPABASE_URL/KEY, JWT_SECRET, GEMINI_API_KEY,
# KAKAO_CLIENT_ID, NAVER_CLIENT_ID/SECRET, ENCRYPTION_KEY 등)
# 선택: GEMINI_MODELS(쉼표로 구분한 모델 순서), KAKAO_APP_ID(카카오 콘솔의 숫자 앱 ID, 0이면 발급 앱 확인 생략)

pip install -r requirements.txt
uvicorn main:app --reload
```

Swagger UI: http://localhost:8000/docs (DEBUG=true 일 때만 — 운영은 DEBUG=false, `/docs`·`/openapi.json` 비공개)

배포 확인: `GET /health`가 `gemini_models`와 `ai_calc`를 돌려주면 최신 코드입니다.

## API 요약

| Method | Path | 설명 |
|--------|------|------|
| POST | /auth/social | 카카오/네이버 로그인 (10/min, 카카오는 토큰 발급 앱 확인) |
| POST | /auth/social/check | 가입 여부만 확인 (계정 생성·로그인 없음, 10/min) |
| POST | /auth/refresh | 토큰 갱신 (20/min) |
| DELETE | /auth/logout | 로그아웃 |
| POST | /ocr/scan | 영수증 이미지 업로드·OCR (라운드별, 10/min, 0원 품목 제외) |
| POST | /ocr/confirm | OCR 결과 확정 (해당 라운드만 갱신, 30/min) |
| POST | /ocr/add-item | 항목 수동 추가 |
| POST | /ocr/attach-photo | 완료된 정산방에도 사진만 순수 첨부(OCR·금액 계산 없음, 20/min) |
| POST | /settlements | 정산방 생성 |
| GET | /settlements/{id} | 정산방 조회 (멤버만) |
| PATCH | /settlements/{id} | 제목 등 수정 (방장) |
| PATCH | /settlements/{id}/status | 상태 변경 (scanning ↔ waiting만) |
| DELETE | /settlements/{id} | 정산방 삭제 (저장된 사진도 함께 삭제) |
| DELETE | /settlements/{id}/receipt | 특정 라운드 영수증 이미지 삭제 |
| DELETE | /settlements/{id}/rounds/{round} | 차수 삭제 (방장, 뒤 차수 번호를 당김, 계산 시작 후 불가) |
| POST | /settlements/{id}/members | 참여자 추가 (20/min) |
| DELETE | /settlements/{id}/members/{user_id} | 참여자 제거 |
| PATCH | /settlements/{id}/members/me/rounds | 내가 참여할 라운드 선택 (RoundPick, 30/min) |
| PATCH | /settlements/{id}/members/me/rounds/{round} | 라운드별 제외 항목 조정 (AmountAdjust, 30/min) |
| PATCH | /settlements/{id}/members/me/ready | 정산 준비 완료 표시 (30/min) |
| PATCH | /settlements/{id}/capacity | 정원(총 인원) 설정 (방장, PeopleCount, join 시 초과 차단, 30/min) |
| PATCH | /settlements/{id}/members/{member_id}/amount | 참여자 금액 수동 조정 (방장) |
| POST | /settlements/{id}/calculate | 정산 계산 (10/min, 안 먹은 메뉴가 없으면 규칙 계산·있으면 AI) |
| GET | /settlements/{id}/result | 정산 결과 조회 (멤버만) |
| POST | /settlements/{id}/done | 정산 완료 (계산이 끝난 방만) |
| GET | /settlements/{id}/qr | QR 코드 이미지 (방장, 죽은 엔드포인트 — 클라이언트는 QR 로컬 생성) |
| POST | /settlements/{id}/join | QR/딥링크 입장 (초대 토큰 검증, 20/min) |
| POST | /settlements/{id}/invite-token | 서명·24시간 만료 초대 토큰 발급 (방장, `regenerate=true`로 기존 토큰 전부 무효화, 30/min) |
| GET | /users/me | 내 프로필 |
| PATCH | /users/me | 닉네임 수정 |
| DELETE | /users/me | 회원탈퇴 (즉시 파기) |
| GET | /users/me/history | 정산 내역 목록 |
| GET | /users/me/history/{id} | 정산 내역 상세 |
| GET/POST | /users/me/account | 계좌 정보 조회/저장 (AES-256-GCM 암호화) |

> 예전의 영수증 보관함 API(`/receipts/*`)와 `saved_receipts` 테이블은 2026-10-07에 삭제했습니다.

## 다차(n차) 정산

한 정산방(`settlements`)에 여러 영수증을 라운드 단위로 누적할 수 있습니다.
- `receipts` 테이블: `settlement_id` + `round` unique. `/ocr/confirm`은 해당 라운드만 갱신(정산방 전체를 덮어쓰지 않음).
- `settlement_member_rounds` 테이블: 참여자별로 어떤 라운드에 참여했는지, 라운드별 제외 항목이 무엇인지 저장.
- 새 라운드는 마지막 라운드 바로 다음 번호로만 만들 수 있습니다(건너뛰기 불가).
- 품목 금액이 단가×수량으로 나누어떨어지지 않으면(3개 10,000원) `receipt_items.line_amount`에 금액을 그대로 둡니다.

## 정산 계산

- 아무도 "안 먹은 메뉴"를 고르지 않았으면 서버가 규칙대로 직접 계산합니다(라운드별 참여자끼리 균등, 1원 나머지는 한 사람에게).
- 안 먹은 메뉴가 있으면 Gemini가 계산하고, 서버가 라운드별 합계와 사람별 금액을 규칙 계산과 대조합니다. 1원 넘게 다르거나 Gemini가 실패하면 규칙 계산 결과를 씁니다.
- 화면에 보이는 사유 문구는 AI가 쓴 글이 아니라 서버가 만든 것만 저장합니다.
- 계산이 시작된 뒤(calculating/calculated/done)에는 영수증·참여 라운드·제외 항목·정원·멤버 삭제·금액 수동 변경이 잠깁니다.
- 계산이 끝난 방의 멤버에게는 결제자(방장) 계좌를 `payer_account`로 내려줍니다.

## 초대 링크 보안

QR/딥링크(`bilzy://join/{id}?token=...`)의 토큰은 JWT로 서명되고 24시간 만료됩니다.
- 신규 참여자만 토큰 검증 대상(방장·기존 멤버는 면제).
- 토큰 검증 실패는 `401`이 아닌 **`403`**으로 응답 — 401은 클라이언트의 `TokenAuthenticator`가 무조건 refresh+재시도를 시도해 오작동하기 때문.
- `settlements.invite_epoch` 컬럼으로 무효화 지원: `POST .../invite-token?regenerate=true`가 epoch을 올려 기존에 공유된 토큰을 전부 즉시 무효화.

## 보안 설계

- **OWASP Top 10 대응**: IDOR 방지(멤버 전용 조회), Parameterized Query, Rate Limiting(slowapi)
- **JWT**: Access(30분) + Refresh(7일) Token, DB 저장으로 탈취 시 무효화, alg 고정
- **업로드 검증**: 받은 파일을 그대로 저장하지 않고 실제로 디코딩한 뒤 새 JPEG으로 다시 만들어 저장(`core/image_validation.py`) — 위장 파일·덧붙인 데이터·EXIF 위치정보 제거, 1,600만 화소·10MB 제한, 움직이는 이미지 거절. 토큰 없는 업로드는 본문을 받기 전에 401(`core/body_limit.py`)
- **영수증 이미지**: private 버킷(10MB·jpg/png/webp 제한) + signed URL(1시간 만료)로만 응답, DB엔 경로만 저장. 방 삭제·차수 삭제·회원탈퇴·보관 기간 경과 시 파일도 삭제
- **AI 프롬프트 인젝션 방어**: 사용자 입력(ai_note)을 구획화해 전달, 제외 항목은 실제 품목명만 허용, AI 금액은 규칙 계산과 대조, AI가 쓴 문구는 저장하지 않음
- **소셜 로그인**: 카카오 토큰이 이 앱(`KAKAO_APP_ID`)에서 발급된 것인지 확인. 로그아웃 시 리프레시 토큰 삭제
- **개인정보보호법**: 닉네임/프로필 이미지 AES-256-GCM 암호화, provider_id HMAC-SHA256 가명처리, 보안 로그 IP 해시, 접근 로그(`core/access_logger.py`), 1년 미접속 계정 자동 파기(`core/retention.py`), 회원탈퇴 시 즉시 파기
- **AI 기본법**: 모든 AI 계산 결과에 고지 문구 포함
- **운영 환경**: Swagger·OpenAPI 명세 비노출, CORS `allow_credentials=False`(모바일은 Bearer라 쿠키 불필요)

## Render 배포

1. GitHub에 푸시
2. Render.com → New Web Service → GitHub 연결
3. 환경변수 입력 (.env.example 참고)
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
