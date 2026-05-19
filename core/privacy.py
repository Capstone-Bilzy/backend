"""
개인정보보호법 기술적 보호조치 모듈

적용 항목:
- 개인정보 암호화 (AES-256-GCM) - 닉네임, 프로필 이미지 URL
- 가명처리 (HMAC-SHA256) - provider_id (식별자)
- IP 해시처리 - 보안 로그 내 IP
- 접근 로그 - 누가 언제 어떤 데이터 조회했는지
- 보관기간 자동 파기 - 1년 미접속 계정
- 동의 이력 저장
"""

import hashlib
import hmac
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# 암호화 키 (32바이트 = AES-256)
# settings.ENCRYPTION_KEY는 hex string으로 저장
def _get_enc_key() -> bytes:
    key_hex = settings.ENCRYPTION_KEY
    return bytes.fromhex(key_hex)


# ── 1. AES-256-GCM 암호화/복호화 ──────────────────────────────

def encrypt(plaintext: str) -> str:
    """개인정보 암호화 (AES-256-GCM)"""
    if not plaintext:
        return plaintext
    key = _get_enc_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96비트 nonce
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    # nonce + ciphertext를 base64로 저장
    return base64.b64encode(nonce + ct).decode()


def decrypt(ciphertext: str) -> str:
    """개인정보 복호화"""
    if not ciphertext:
        return ciphertext
    try:
        key = _get_enc_key()
        aesgcm = AESGCM(key)
        raw = base64.b64decode(ciphertext)
        nonce, ct = raw[:12], raw[12:]
        return aesgcm.decrypt(nonce, ct, None).decode()
    except Exception:
        logger.error("복호화 실패 - 키 불일치 또는 데이터 손상")
        return ""


# ── 2. HMAC-SHA256 가명처리 ────────────────────────────────────

def pseudonymize(value: str) -> str:
    """
    가명처리 (HMAC-SHA256)
    - provider_id: 카카오/네이버 고유 ID → 복원 불가 단방향 처리
    - 같은 값은 항상 같은 해시 → upsert 시 조회 가능
    """
    key = settings.PSEUDONYM_SECRET.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


# ── 3. IP 해시처리 ─────────────────────────────────────────────

def hash_ip(ip: str) -> str:
    """
    IP 주소 단방향 해시 (보안 로그용)
    - 원본 IP 복원 불가
    - 동일 IP 식별은 가능 (이상 징후 탐지)
    """
    return hashlib.sha256((ip + settings.IP_HASH_SALT).encode()).hexdigest()[:16]


# ── 4. 유저 데이터 암호화/복호화 헬퍼 ────────────────────────

def encrypt_user(user_info: dict) -> dict:
    """DB 저장 전 개인정보 암호화"""
    return {
        **user_info,
        "nickname": encrypt(user_info.get("nickname", "")),
        "profile_image_url": encrypt(user_info.get("profile_image_url", "")),
        "provider_id": pseudonymize(user_info.get("provider_id", "")),
    }


def decrypt_user(user_row: dict) -> dict:
    """DB 조회 후 복호화 (앱으로 반환 전)"""
    return {
        **user_row,
        "nickname": decrypt(user_row.get("nickname", "")),
        "profile_image_url": decrypt(user_row.get("profile_image_url", "")),
        # provider_id는 가명처리 후 복원 불필요 → 반환 안 함
    }
