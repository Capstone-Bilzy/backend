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

    KAKAO_CLIENT_ID: str
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
