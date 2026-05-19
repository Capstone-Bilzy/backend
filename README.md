# Bilzy Backend

더치페이 앱 Bilzy의 FastAPI 백엔드

## 기술 스택

- **FastAPI** - 백엔드 프레임워크
- **Supabase** - PostgreSQL DB / Auth / Storage
- **Google Gemini** - AI 정산 계산
- **Render.com** - 배포

## 프로젝트 구조

```
bilzy/
├── main.py                  # FastAPI 앱 진입점
├── requirements.txt
├── supabase_schema.sql      # DB 스키마
├── .env.example
├── core/
│   ├── config.py            # 환경변수 설정
│   ├── database.py          # Supabase 클라이언트
│   ├── security.py          # JWT 인증
│   └── security_logger.py   # 보안 이벤트 로깅
├── models/
│   └── schemas.py           # Pydantic 모델
├── routers/
│   ├── auth.py              # 인증 API
│   ├── ocr.py               # OCR API
│   ├── settlements.py       # 정산방 API
│   └── users.py             # 유저 API
└── services/
    ├── auth_service.py      # 카카오/네이버 소셜 로그인
    ├── ocr_service.py       # 영수증 이미지 처리
    ├── settlement_service.py
    ├── ai_service.py        # Gemini 정산 계산
    ├── qr_service.py        # QR 코드 생성
    └── user_service.py      # 유저/내역 관리
```

## 로컬 실행

```bash
cp .env.example .env
# .env 파일에 키 입력

pip install -r requirements.txt
uvicorn main:app --reload
```

Swagger UI: http://localhost:8000/docs (DEBUG=true 일 때만)

## API 요약

| Method | Path | 설명 |
|--------|------|------|
| POST | /auth/social | 카카오/네이버 로그인 |
| POST | /auth/refresh | 토큰 갱신 |
| DELETE | /auth/logout | 로그아웃 |
| POST | /ocr/scan | 영수증 이미지 업로드 |
| POST | /ocr/confirm | OCR 결과 확정 |
| POST | /ocr/add-item | 항목 수동 추가 |
| POST | /settlements | 정산방 생성 |
| GET | /settlements/{id} | 정산방 조회 |
| POST | /settlements/{id}/calculate | AI 정산 계산 |
| GET | /settlements/{id}/result | 정산 결과 조회 |
| GET | /settlements/{id}/qr | QR 코드 이미지 |
| POST | /settlements/{id}/join | QR 입장 |
| POST | /settlements/{id}/done | 정산 완료 |
| GET | /users/me | 내 프로필 |
| DELETE | /users/me | 회원탈퇴 (즉시 파기) |
| GET | /users/me/history | 정산 내역 목록 |

## 보안 설계

- **OWASP Top 10 대응**: IDOR 방지, Parameterized Query, Rate Limiting
- **JWT**: Access(30분) + Refresh(7일) Token, DB 저장으로 탈취 시 무효화
- **개인정보보호법**: 회원탈퇴 시 전체 데이터 즉시 파기, 로그 마스킹
- **AI 기본법**: 모든 AI 계산 결과에 고지 문구 포함
- **운영 환경**: Swagger 비노출, CORS 앱 스킴만 허용

## Render 배포

1. GitHub에 푸시
2. Render.com → New Web Service → GitHub 연결
3. 환경변수 입력 (.env.example 참고)
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
