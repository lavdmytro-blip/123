"""Bot webhook & optional notifications, without third-party bot framework."""
import logging
import httpx
from . import config

log = logging.getLogger(__name__)


async def call(method: str, payload: dict):
    if not config.BOT_TOKEN:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f'https://api.telegram.org/bot{config.BOT_TOKEN}/{method}', json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get('ok'):
            raise ValueError('Telegram: ' + str(data.get('description', 'unknown')))
        return data.get('result')


async def setup():
    if not (config.BOT_TOKEN and config.PUBLIC_BASE_URL and config.WEBHOOK_SECRET):
        log.warning('Telegram webhook skipped: configure BOT_TOKEN, PUBLIC_BASE_URL, WEBHOOK_SECRET')
        return
    try:
        await call('setWebhook', {
            'url': config.PUBLIC_BASE_URL + '/telegram/webhook',
            'secret_token': config.WEBHOOK_SECRET,
            'allowed_updates': ['message'], 'drop_pending_updates': False,
        })
        await call('setChatMenuButton', {
            'menu_button': {'type': 'web_app', 'text': 'Открыть сигналы', 'web_app': {'url': config.PUBLIC_BASE_URL}}
        })
        log.info('Telegram webhook and menu button configured')
    except Exception:
        log.exception('Failed to configure Telegram webhook')


async def send(chat_id: int, text: str):
    if not config.BOT_TOKEN or not chat_id:
        return False
    try:
        await call('sendMessage', {'chat_id': chat_id, 'text': text[:4000], 'disable_web_page_preview': True})
        return True
    except Exception:
        log.exception('Failed Telegram message for user')
        return False


async def welcome(chat_id: int):
    if not config.PUBLIC_BASE_URL:
        await send(chat_id, 'Бот ещё не настроен. Администратор должен указать PUBLIC_BASE_URL в Railway.')
        return
    try:
        await call('sendMessage', {
            'chat_id': chat_id, 'text': '📊 BingX AI Signals\n\nАнализ рынка по реальным данным BingX. Сигналы — технические сценарии, не гарантия результата. Торговых операций нет.',
            'reply_markup': {'inline_keyboard': [[{'text': '📈 Открыть Mini App', 'web_app': {'url': config.PUBLIC_BASE_URL}}]]},
        })
    except Exception:
        log.exception('Welcome message failed')
