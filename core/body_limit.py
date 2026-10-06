"""
요청 본문 크기 제한(ASGI 미들웨어).

FastAPI는 multipart 업로드를 핸들러가 실행되기 전에 통째로 받아 임시 파일에 쌓는다. 그래서 핸들러 안의
크기 검사만으로는 거대한 업로드가 서버 디스크·메모리를 먼저 채우는 걸 막지 못한다. 여기서는
- Content-Length가 한도를 넘으면 본문을 받기 전에 413으로 끊고,
- 길이를 안 밝힌(chunked) 요청은 받는 도중 한도를 넘는 순간 413으로 끊는다.
"""

import json

MAX_BODY_BYTES = 12 * 1024 * 1024  # 이미지 10MB + multipart 여유분


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(send)
                return

        received = 0
        rejected = False
        response_started = False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    # 앱에는 연결이 끊긴 것으로 알려 더 읽지 않게 한다
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal response_started
            if rejected:
                return  # 한도 초과 뒤 앱이 보내려는 응답은 버리고 아래에서 413을 보낸다
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:
                raise
        if rejected and not response_started:
            await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = json.dumps({"detail": "요청이 너무 큽니다"}, ensure_ascii=False).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
