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

# Public paper-signal scanner; never submits or recommends real orders.
AUTO_SIGNALS_ENABLED = os.getenv('AUTO_SIGNALS_ENABLED', 'true').lower() == 'true'
AUTO_SIGNALS_INTERVAL = os.getenv('AUTO_SIGNALS_INTERVAL', '15m').strip()
# ALL ignores the older AUTO_SIGNALS_SYMBOLS list so existing Railway deployments expand automatically.
AUTO_SIGNALS_UNIVERSE = os.getenv('AUTO_SIGNALS_UNIVERSE', 'ALL').strip().upper()
AUTO_SIGNALS_SYMBOLS = [s.strip().upper() for s in os.getenv('AUTO_SIGNALS_SYMBOLS',
    'BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,BNB-USDT').split(',') if s.strip()]
AUTO_SCAN_BATCH_SIZE = max(1, min(int(os.getenv('AUTO_SCAN_BATCH_SIZE', '12')), 30))
AUTO_SCAN_PACE_SECONDS = max(0.25, min(float(os.getenv('AUTO_SCAN_PACE_SECONDS', '1.2')), 10.0))
AUTO_SCAN_COOLDOWN_SECONDS = max(5, min(int(os.getenv('AUTO_SCAN_COOLDOWN_SECONDS', '60')), 900))
