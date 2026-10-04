from __future__ import annotations

from uuid import uuid4
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class DomainError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def fail(status, code, message):
    raise DomainError(status, code, message)


def install_errors(app):
    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={'error': {
            'code': exc.code, 'message': exc.message,
            'request_id': request.state.request_id,
        }})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={'error': {
            'code': 'VALIDATION_ERROR', 'message': '填写内容有误，请检查后重试',
            'request_id': request.state.request_id,
            'fields': [{'path': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()],
        }})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, headers=exc.headers, content={'error': {
            'code': 'NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR',
            'message': '请求的内容不存在' if exc.status_code == 404 else '无法处理此请求',
            'request_id': request.state.request_id,
        }})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={'error': {
            'code': 'INTERNAL_ERROR', 'message': '服务暂时不可用，请稍后重试',
            'request_id': request.state.request_id,
        }})
