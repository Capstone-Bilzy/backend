from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GEMINI_API_KEY: str
    # 쓸 모델을 앞에서부터 차례로 시도한다(쉼표로 구분, 환경변수 GEMINI_MODELS로 바꿀 수 있음).
    # - 새로 만든 Google 계정의 키로는 gemini-2.5-flash를 쓸 수 없다(404 "no longer available to new users").
    # - 한 모델이 과부하(503)거나 한도 초과(429)여도 다음 모델로 넘어가 인식·계산이 멈추지 않게 한다.
    # 순서는 2026-10-07 같은 영수증으로 재 본 결과: 3-flash-preview가 4번 모두 5~8초에 정확히 읽었고,
    # 3.5/3.6/3.8-flash는 정확하지만 그날 과부하(503)가 잦았다. lite 계열은 빠르지만 품목을 빠뜨리거나
    # 금액 열을 단가로 읽어서 뺐다 — 틀린 결과를 주느니 실패해서 "직접 입력"으로 가는 편이 낫다.
    GEMINI_MODELS: str = "gemini-3-flash-preview,gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash"

    KAKAO_CLIENT_ID: str
    # 카카오 개발자 콘솔의 숫자 앱 ID(비밀 값 아님). 로그인에 쓰인 카카오 토큰이 이 앱에서 발급된 것인지 확인한다.
    # 0으로 두면 확인을 건너뛴다(문제가 생겼을 때 환경변수 KAKAO_APP_ID=0 으로 바로 끌 수 있게).
    KAKAO_APP_ID: int = 1468714
    # 한 사람이 하루(한국 시간)에 영수증 인식(Gemini)을 부를 수 있는 횟수. 무료 한도를 한 명이 다 쓰는 걸 막는다.
    # 0이면 제한 없음. 넘으면 429 — 앱은 인식 실패 화면에서 직접 입력으로 이어갈 수 있다.
    OCR_DAILY_LIMIT_PER_USER: int = 10
    # 한 사람이 하루(한국 시간)에 정산 계산에서 AI(Gemini)를 부를 수 있는 횟수. 넘으면 오류 없이 규칙 계산으로 끝낸다
    # (AI 결과는 어차피 규칙 계산과 같아야 통과한다). 0이면 제한 없음.
    AI_CALC_DAILY_LIMIT_PER_USER: int = 20
    NAVER_CLIENT_ID: str
    NAVER_CLIENT_SECRET: str

    # 개인정보 암호화 키 (32바이트 hex = AES-256)
    # 생성: python -c "import os; print(os.urandom(32).hex())"
    ENCRYPTION_KEY: str

    # 가명처리 시크릿 (HMAC-SHA256용)
    # 생성: python -c "import os; print(os.urandom(32).hex())"
    PSEUDONYM_SECRET: str

    # IP 해시 솔트
    # 생성: python -c "import os; print(os.urandom(16).hex())"
    IP_HASH_SALT: str

    DEBUG: bool = False

    class Config:
        env_file = ".env"

settings = Settings()
