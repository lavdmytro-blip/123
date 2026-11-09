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
        await call('setMyCommands', {'commands': [
            {'command': 'start', 'description': 'Открыть приложение'},
            {'command': 'pump_on', 'description': 'Включить PUMP/DUMP'},
            {'command': 'pump_off', 'description': 'Отключить PUMP/DUMP'},
            {'command': 'signals_on', 'description': 'Включить AI сигналы'},
            {'command': 'signals_off', 'description': 'Отключить AI сигналы'},
            {'command': 'status', 'description': 'Статус подписок'},
        ]})
        log.info('Telegram webhook, menu and commands configured')
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


async def send_market(chat_id: int, text: str, symbol: str):
    """Private-chat notification with a direct Telegram Mini App chart button."""
    if not config.BOT_TOKEN or not chat_id:
        return False
    data = {'chat_id': chat_id, 'text': text[:4000], 'disable_web_page_preview': True}
    if config.PUBLIC_BASE_URL and symbol.endswith('-USDT') and symbol.replace('-', '').isalnum():
        from urllib.parse import quote
        data['reply_markup'] = {'inline_keyboard': [[{
            'text': '📈 Открыть график в Mini App',
            'web_app': {'url': config.PUBLIC_BASE_URL + '/?symbol=' + quote(symbol)},
        }]]}
    try:
        await call('sendMessage', data)
        return True
    except Exception:
        log.exception('Telegram market alert failed')
        return False


async def welcome(chat_id: int):
    if not config.PUBLIC_BASE_URL:
        await send(chat_id, 'Бот ещё не настроен. Администратор должен указать PUBLIC_BASE_URL в Railway.')
        return
    try:
        await call('sendMessage', {
            'chat_id': chat_id, 'text': '📊 BingX AI Signals\n\nАнализ рынка по данным BingX. Для сообщений о резких движениях отправь /pump_on, для обычных сценариев — /signals_on. Отключение: /pump_off и /signals_off.\n\nЭто наблюдения рынка, не гарантия будущих движений. Торговых операций нет.',
            'reply_markup': {'inline_keyboard': [[{'text': '📈 Открыть Mini App', 'web_app': {'url': config.PUBLIC_BASE_URL}}]]},
        })
    except Exception:
        log.exception('Welcome message failed')
