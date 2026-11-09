"""Optional, tightly scoped natural-language summary from OpenAI Responses API.

Disabled without OPENAI_API_KEY. The LLM never calculates or changes signal/levels.
"""
import json
import logging
import re
import httpx
from . import config

log = logging.getLogger(__name__)


async def ai_comment(result: dict) -> str | None:
    if not config.OPENAI_API_KEY:
        return None
    facts = {
        'side': result['side'], 'summary': result['summary'],
        'confirmedReasons': [x['text'] for x in result['reasons']],
        'risks': result['risks'],
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post('https://api.openai.com/v1/responses',
                headers={'Authorization': 'Bearer '+config.OPENAI_API_KEY}, json={
                    'model': config.OPENAI_MODEL,
                    'instructions': ('Ты объясняешь результат технического анализа на русском. '
                         'Ровно 2 коротких предложения, без чисел, котировок, рекомендаций открыть позицию, '
                         'обещаний успеха и новых фактов. Используй только переданные аргументы и риски.'),
                    'input': json.dumps(facts, ensure_ascii=False), 'max_output_tokens': 125,
                })
            response.raise_for_status()
            payload = response.json()
            content = [c.get('text', '') for out in payload.get('output', []) for c in out.get('content', []) if c.get('type') == 'output_text']
            message = ' '.join(content).strip()[:700]
            if not message or re.search(r'\d', message):
                return None
            return message
    except Exception as exc:
        log.warning('Optional AI commentary unavailable: %s', type(exc).__name__)
        return None
