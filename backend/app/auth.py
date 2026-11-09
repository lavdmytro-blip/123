"""Telegram WebApp initData validation following Telegram's HMAC specification."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from fastapi import Header, HTTPException
from . import config


def parse_init_data(raw: str) -> dict:
    if not config.BOT_TOKEN:
        raise ValueError('Telegram bot is not configured')
    pairs = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    received = pairs.pop('hash', '')
    auth_date = int(pairs.get('auth_date', '0'))
    if not received or not auth_date or abs(time.time() - auth_date) > 86400:
        raise ValueError('Invalid or expired Telegram authorization')
    data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise ValueError('Telegram authorization signature mismatch')
    user = json.loads(pairs.get('user', '{}'))
    if not isinstance(user.get('id'), int) or user['id'] <= 0:
        raise ValueError('Missing Telegram user ID')
    return user


def require_user(x_telegram_init_data: str = Header(default='')) -> int:
    try:
        return int(parse_init_data(x_telegram_init_data)['id'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail='Откройте приложение через Telegram-бота.') from exc


def optional_user(x_telegram_init_data: str = Header(default='')) -> int | None:
    if not x_telegram_init_data:
        return None
    return require_user(x_telegram_init_data)
