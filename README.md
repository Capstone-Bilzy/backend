# Bilzy Backend

더치페이 앱 Bilzy의 FastAPI 백엔드

## 기술 스택

- **FastAPI** - 백엔드 프레임워크
- **Supabase** - PostgreSQL DB / Auth / Storage(영수증 이미지, private 버킷 + signed URL)
- **Google Gemini** - OCR(Vision) + AI 정산 계산
- **Render.com** - 배포

## 프로젝트 구조

```
bilzy/
├── main.py                  # FastAPI 앱 진입점
├── requirements.txt
├── supabase_schema.sql      # DB 스키마 (기본)
├── schema_additions.sql     # 계좌/영수증 보관함 등 추가 스키마
├── schema_multi_round.sql   # 다차(n차) 정산: receipts / settlement_member_rounds
├── schema_member_ready.sql  # 참여자 준비완료(ready) 플래그
├── schema_invite_epoch.sql  # 초대 토큰 무효화용 invite_epoch
├── .env.example
├── core/
│   ├── config.py            # 환경변수 설정
│   ├── database.py          # Supabase 클라이언트
│   ├── security.py          # JWT 인증
│   ├── security_logger.py   # 보안 이벤트 로깅
│   ├── limiter.py           # Rate limit(slowapi) 설정
│   ├── image_validation.py  # 업로드 이미지 실제 디코딩 검증
│   ├── storage.py           # private 버킷 signed URL 발급
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
│   ├── account_router.py     # 계좌 정보 API (/users/me/account)
│   └── receipts_router.py    # 영수증 저장 보관함 API (/receipts, 정산방과 무관한 별도 기능)
└── services/
    ├── auth_service.py           # 카카오/네이버 소셜 로그인
    ├── ocr_service.py            # 영수증 이미지 처리(Gemini OCR)
    ├── settlement_service.py     # 정산방/라운드/멤버 관리
    ├── ai_service.py             # Gemini 정산 계산
    ├── qr_service.py             # QR 코드 생성 + 초대 토큰 발급/검증
    ├── user_service.py           # 유저/내역 관리
    ├── account_service.py        # 계좌 정보(AES-256-GCM 암호화)
    └── receipt_store_service.py  # 영수증 보관함(정산방과 별개)
```

## 로컬 실행

```bash
cp .env.example .env
# .env 파일에 키 입력 (SUPABASE_URL/KEY, JWT_SECRET, GEMINI_API_KEY,
# KAKAO_CLIENT_ID, NAVER_CLIENT_ID/SECRET, ENCRYPTION_KEY 등)

pip install -r requirements.txt
uvicorn main:app --reload
```

Swagger UI: http://localhost:8000/docs (DEBUG=true 일 때만)

## API 요약

| Method | Path | 설명 |
|--------|------|------|
| POST | /auth/social | 카카오/네이버 로그인 (10/min) |
| POST | /auth/refresh | 토큰 갱신 (20/min) |
| DELETE | /auth/logout | 로그아웃 |
| POST | /ocr/scan | 영수증 이미지 업로드·OCR (라운드별, 10/min) |
| POST | /ocr/confirm | OCR 결과 확정 (해당 라운드만 갱신, 30/min) |
| POST | /ocr/add-item | 항목 수동 추가 |
| POST | /settlements | 정산방 생성 |
| GET | /settlements/{id} | 정산방 조회 (멤버만) |
| PATCH | /settlements/{id} | 제목 등 수정 (방장) |
| PATCH | /settlements/{id}/status | 상태 변경 |
| DELETE | /settlements/{id} | 정산방 삭제 |
| DELETE | /settlements/{id}/receipt | 특정 라운드 영수증 이미지 삭제 |
| POST | /settlements/{id}/members | 참여자 추가 (20/min) |
| DELETE | /settlements/{id}/members/{user_id} | 참여자 제거 |
| PATCH | /settlements/{id}/members/me/rounds | 내가 참여할 라운드 선택 (RoundPick, 30/min) |
| PATCH | /settlements/{id}/members/me/rounds/{round} | 라운드별 제외 항목 조정 (AmountAdjust, 30/min) |
| PATCH | /settlements/{id}/members/me/ready | 정산 준비 완료 표시 (30/min) |
| PATCH | /settlements/{id}/capacity | 정원(총 인원) 설정 (방장, PeopleCount, join 시 초과 차단, 30/min) |
| PATCH | /settlements/{id}/members/{member_id}/amount | 참여자 금액 수동 조정 (방장) |
| POST | /settlements/{id}/calculate | AI 정산 계산 (10/min) |
| GET | /settlements/{id}/result | 정산 결과 조회 (멤버만) |
| POST | /settlements/{id}/done | 정산 완료 |
| GET | /settlements/{id}/qr | QR 코드 이미지 (방장, 죽은 엔드포인트 — 클라이언트는 QR 로컬 생성) |
| POST | /settlements/{id}/join | QR/딥링크 입장 (초대 토큰 검증, 20/min) |
| POST | /settlements/{id}/invite-token | 서명·24시간 만료 초대 토큰 발급 (방장, `regenerate=true`로 기존 토큰 전부 무효화, 30/min) |
| GET | /users/me | 내 프로필 |
| PATCH | /users/me | 닉네임 수정 |
| DELETE | /users/me | 회원탈퇴 (즉시 파기) |
| GET | /users/me/history | 정산 내역 목록 |
| GET | /users/me/history/{id} | 정산 내역 상세 |
| GET/POST | /users/me/account | 계좌 정보 조회/저장 (AES-256-GCM 암호화) |
| POST | /receipts/scan | 보관함 저장 전 독립 OCR (금액 프리필용, 저장 없음) |
| POST | /receipts | 영수증 보관함 저장 |
| GET | /receipts, /receipts/{id} | 보관함 목록/단건 조회 |
| DELETE | /receipts/{id} | 보관함 삭제 |

> `/receipts/*`는 정산방과 독립적인 별도 영수증 보관함 기능입니다. Android 클라이언트는 "저장 영수증 보관함 없음"이 제품 결정이라 이 API를 사용하지 않습니다.

## 다차(n차) 정산

한 정산방(`settlements`)에 여러 영수증을 라운드 단위로 누적할 수 있습니다.
- `receipts` 테이블: `settlement_id` + `round` unique. `/ocr/confirm`은 해당 라운드만 갱신(정산방 전체를 덮어쓰지 않음).
- `settlement_member_rounds` 테이블: 참여자별로 어떤 라운드에 참여했는지, 라운드별 제외 항목이 무엇인지 저장.
- AI 계산(`/calculate`)은 라운드별 참여자·제외 항목을 구조화해 Gemini 프롬프트에 반영.

## 초대 링크 보안

QR/딥링크(`bilzy://join/{id}?token=...`)의 토큰은 JWT로 서명되고 24시간 만료됩니다.
- 신규 참여자만 토큰 검증 대상(방장·기존 멤버는 면제).
- 토큰 검증 실패는 `401`이 아닌 **`403`**으로 응답 — 401은 클라이언트의 `TokenAuthenticator`가 무조건 refresh+재시도를 시도해 오작동하기 때문.
- `settlements.invite_epoch` 컬럼으로 무효화 지원: `POST .../invite-token?regenerate=true`가 epoch을 올려 기존에 공유된 토큰을 전부 즉시 무효화.

## 보안 설계

- **OWASP Top 10 대응**: IDOR 방지(멤버 전용 조회), Parameterized Query, Rate Limiting(slowapi)
- **JWT**: Access(30분) + Refresh(7일) Token, DB 저장으로 탈취 시 무효화, alg 고정
- **업로드 검증**: content-type 헤더만 신뢰하지 않고 실제 이미지 디코딩 검증(`core/image_validation.py`)
- **영수증 이미지**: private 버킷 + signed URL(1시간 만료)로만 응답, DB엔 경로만 저장
- **AI 프롬프트 인젝션 방어**: 사용자 입력(ai_note)을 구획화해 전달 + AI 출력 서버 검증(금액 클램프, 정체불명 닉네임 무시 등)
- **개인정보보호법**: 닉네임/프로필 이미지 AES-256-GCM 암호화, provider_id HMAC-SHA256 가명처리, 보안 로그 IP 해시, 접근 로그(`core/access_logger.py`), 1년 미접속 계정 자동 파기(`core/retention.py`), 회원탈퇴 시 즉시 파기
- **AI 기본법**: 모든 AI 계산 결과에 고지 문구 포함
- **운영 환경**: Swagger 비노출, CORS `allow_credentials=False`(모바일은 Bearer라 쿠키 불필요)

## Render 배포

1. GitHub에 푸시
2. Render.com → New Web Service → GitHub 연결
3. 환경변수 입력 (.env.example 참고)
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
