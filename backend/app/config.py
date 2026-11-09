import os

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./signals.db').strip()
REDIS_URL = os.getenv('REDIS_URL', '').strip()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
BINGX_BASE_URL = os.getenv('BINGX_BASE_URL', 'https://open-api.bingx.com').rstrip('/')
BINGX_FALLBACK_URL = os.getenv('BINGX_FALLBACK_URL', 'https://open-api.bingx.pro').rstrip('/')
ENABLE_WORKER = os.getenv('ENABLE_WORKER', 'true').lower() == 'true'
MAX_SCAN_WATCHES = max(1, min(int(os.getenv('MAX_SCAN_WATCHES', '20')), 100))
INTERVALS = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400}
