"""Фото-перевірка вживаності: вердикти моделі з кешем по URL оголошення.

Продавці вживаних деталей часто мовчать про стан у тексті — словниковий
відсів і текстова перевірка тоді сліпі, а фото видає деталь з розборки
одразу. Вердикт живе довго, бо лістинги міняють фото рідко; той самий
лістинг трапляється у звітах різних товарів — кеш по URL оголошення
платить за виклик моделі один раз.

Мертвий Redis деградує до прямих викликів моделі, а не валить звіт —
той самий підхід, що в exchange_rates.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Sequence

from redis.asyncio import Redis

from marko.core.config import get_settings
from marko.services import llm_filter

log = logging.getLogger(__name__)

_CACHE_TTL = 7 * 24 * 60 * 60  # фото лістинга міняють рідко
_UNSURE_TTL = 24 * 60 * 60  # сумнів не заморожуємо на тиждень

_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().competitor_price_cache_url, decode_responses=True
        )
    return _client


def _cache_key(offer_url: str) -> str:
    return f"photo-used:v1:{hashlib.sha1(offer_url.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class PhotoCandidate:
    url: str  # URL пропозиції — ключ кешу
    title: str
    image_url: str


async def condition_verdicts(
    candidates: Sequence[PhotoCandidate],
) -> dict[str, str]:
    """offer_url -> "used" | "not_used" | "unsure"; збої відсутні в словнику.

    Відсутній ключ означає «вердикту немає» і пропозицію не чіпають —
    збій виклику не має понижувати чесні ціни.
    """
    verdicts: dict[str, str] = {}
    misses: list[PhotoCandidate] = []
    for candidate in candidates:
        cached = None
        try:
            cached = await _redis().get(_cache_key(candidate.url))
        except Exception as exc:  # Redis лежить — ідемо напряму до моделі
            log.warning("Фото-перевірка: кеш недоступний: %s", exc)
        if cached:
            verdicts[candidate.url] = cached
        else:
            misses.append(candidate)

    fresh = await asyncio.gather(
        *(
            llm_filter.photo_condition(
                title=candidate.title, image_url=candidate.image_url
            )
            for candidate in misses
        )
    )
    for candidate, verdict in zip(misses, fresh):
        if verdict is None:
            continue
        verdicts[candidate.url] = verdict
        ttl = _UNSURE_TTL if verdict == "unsure" else _CACHE_TTL
        try:
            await _redis().set(_cache_key(candidate.url), verdict, ex=ttl)
        except Exception as exc:
            log.warning("Фото-перевірка: не вдалося закешувати: %s", exc)
    return verdicts
