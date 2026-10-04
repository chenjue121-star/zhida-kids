from __future__ import annotations

import inspect
import logging
import httpx
from app.v2.core.errors import DomainError, fail

logger = logging.getLogger(__name__)


async def exchange_code(code, settings, exchanger=None, transport=None):
    try:
        if exchanger is not None:
            identity = exchanger(code)
            if inspect.isawaitable(identity):
                identity = await identity
        elif settings.dev_wechat_mock:
            identity = {'openid': 'dev:' + code}
        else:
            if not settings.wechat_appid or not settings.wechat_secret.get_secret_value():
                fail(503, 'WECHAT_UNAVAILABLE', '微信登录尚未配置，请联系管理员')
            async with httpx.AsyncClient(timeout=8, transport=transport) as client:
                response = await client.get('https://api.weixin.qq.com/sns/jscode2session', params={
                    'appid': settings.wechat_appid, 'secret': settings.wechat_secret.get_secret_value(),
                    'js_code': code, 'grant_type': 'authorization_code',
                })
                response.raise_for_status()
                identity = response.json()
        provider_code = identity.get('errcode') if isinstance(identity, dict) else None
        if provider_code in (40013, 40125, 40164):
            logger.warning('Wechat configuration rejected: provider_code=%s', provider_code)
            fail(503, 'WECHAT_CONFIGURATION_ERROR', '微信登录配置校验失败，请联系管理员核对配置')
        if provider_code in (-1, 45011):
            fail(503, 'WECHAT_UNAVAILABLE', '微信登录暂时繁忙，请稍后重试')
        if not isinstance(identity, dict) or provider_code or not isinstance(identity.get('openid'), str) or not 0 < len(identity['openid']) <= 128:
            fail(400, 'INVALID_WECHAT_CODE', '微信登录凭证无效，请重新登录')
        return {'openid': identity['openid'], 'nickname': str(identity.get('nickname', ''))}
    except DomainError:
        raise
    except (httpx.HTTPError, TimeoutError):
        fail(503, 'WECHAT_UNAVAILABLE', '微信登录暂时不可用，请稍后重试')
    except (ValueError, TypeError):
        fail(400, 'INVALID_WECHAT_CODE', '微信登录凭证无效，请重新登录')
