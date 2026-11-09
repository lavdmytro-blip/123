import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from app import auth, config
from app.bingx import normalize_ticker


def test_init_data_validates_signature(monkeypatch):
    monkeypatch.setattr(config, 'BOT_TOKEN', 'TEST:token')
    fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':123456789,'first_name':'Test'})}
    data='\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
    secret=hmac.new(b'WebAppData', b'TEST:token', hashlib.sha256).digest()
    signature=hmac.new(secret,data.encode(),hashlib.sha256).hexdigest()
    assert auth.parse_init_data(urlencode({**fields,'hash':signature}))['id']==123456789
    try:auth.parse_init_data(urlencode({**fields,'hash':'0'*64}))
    except ValueError:pass
    else:assert False, 'Forged initData must be rejected'


def test_ticker_normalization():
    tick=normalize_ticker({'symbol':'BTC-USDT','lastPrice':'105.4','priceChangePercent':'2.1','quoteVolume':'100000'})
    assert tick['lastPrice']==105.4
    assert tick['volume24h']==100000
