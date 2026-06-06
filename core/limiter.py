"""
요청 속도 제한기(공유 인스턴스).

main.py와 각 router가 동일한 Limiter를 쓰도록 별도 모듈로 분리(순환 import 방지).
키는 클라이언트 IP. 비용 발생/인증 엔드포인트에 @limiter.limit 데코레이터로 적용한다.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
