"""Відсіювання чужих товарів дешевою моделлю: один виклик, помилка = без фільтра."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Sequence

import openai

from marko.core.config import get_settings

log = logging.getLogger(__name__)

# Має покривати всі можливі пропозиції (_AVTOPRO_MAX_OFFERS + _PROM_MAX_OFFERS
# + _GOOGLE_MAX_OFFERS): кандидат поза лімітом не отримує вердикту і проходив
# у видачу без перевірки.
MAX_CANDIDATES = 120

_SYSTEM = (
    "Ти підбираєш конкурентні пропозиції для автозапчастини на українському ринку.\n"
    "Для кожного кандидата з нумерованого списку постав категорію:\n"
    "  same   — та сама деталь: той самий вузол, та сама сторона й позиція,\n"
    "           та сама машина або той самий каталожний номер;\n"
    "  analog — інший виробник чи артикул, але деталь взаємозамінна з нашою;\n"
    "  no     — інший вузол, інша сторона, інша машина, інший розмір,\n"
    "           комплект замість однієї деталі, вживана деталь замість нової,\n"
    "           аксесуар до деталі (кріплення, прокладка), зовсім інший товар\n"
    "           або взагалі не автозапчастина (одяг, взуття, сумки, побут).\n"
    "Сумніваєшся — став no: краще менше пропозицій, ніж чужі в порівнянні цін.\n"
    'Відповідь — лише JSON: {"verdicts": [{"index": 0, "verdict": "same"}, ...]},'
    " по одному запису на кожного кандидата, без пояснень."
)


def is_enabled() -> bool:
    return bool(get_settings().openai_api_key)


@lru_cache
def _openai() -> openai.AsyncOpenAI:
    """Клієнт OpenAI або сумісний провайдер (наприклад, DeepSeek або проксі)."""
    settings = get_settings()
    return openai.AsyncOpenAI(
        api_key=settings.openai_api_key,
        # Явний дефолт: з base_url=None бібліотека читає env OPENAI_BASE_URL,
        # а compose завжди прокидає його — хай і порожнім рядком.
        base_url=settings.openai_base_url or "https://api.openai.com/v1",
    )


def _prompt(
    name: str, brand: str | None, oem_numbers: Sequence[str], titles: Sequence[str]
) -> str:
    seed = [f"Наша деталь: {name}"]
    if brand:
        seed.append(f"Виробник: {brand}")
    if oem_numbers:
        seed.append(f"Каталожні номери: {', '.join(oem_numbers)}")
    candidates = "\n".join(f"{index}. {title}" for index, title in enumerate(titles))
    return "\n".join([*seed, "", "Кандидати:", candidates])


async def classify(
    *,
    name: str,
    brand: str | None,
    oem_numbers: Sequence[str],
    titles: Sequence[str],
) -> dict[int, str]:
    """index -> "same" | "analog" | "no"; порожньо, якщо модель недоступна."""
    if not titles or not is_enabled():
        return {}
    prompt = _prompt(name, brand, oem_numbers, titles[:MAX_CANDIDATES])
    try:
        verdicts = json.loads(await _ask_openai(prompt))["verdicts"]
    except Exception as exc:  # фільтр не критичний — краще без нього, ніж без цін
        log.warning("LLM-фільтр пропозицій не спрацював: %s", exc)
        return {}
    result = {
        item["index"]: item["verdict"]
        for item in verdicts
        if isinstance(item.get("index"), int) and 0 <= item["index"] < len(titles)
    }
    if not result:
        return {}
    # Модель мала оцінити кожного посланого кандидата: пропущений нею index
    # раніше проходив у видачу без перевірки — тепер він «не підтверджений».
    return {
        index: result.get(index, "no")
        for index in range(min(len(titles), MAX_CANDIDATES))
    }


async def _ask_openai(prompt: str) -> str:
    # json_object, а не json_schema: його розуміють усі сумісні провайдери,
    # а форму відповіді все одно перевіряє classify().
    settings = get_settings()
    # Заміряно на 58 кандидатах (gpt-5-nano): default 12.4 c, low 7.0 c з тим
    # самим результатом, minimal 4.0 c — і 10 чужих позицій у видачі.
    # Чужий base_url може не знати цього параметра, тож лише для самого OpenAI.
    extra = {} if settings.openai_base_url else {"reasoning_effort": "low"}
    response = await _openai().chat.completions.create(
        model=settings.competitor_filter_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        **extra,
    )
    return response.choices[0].message.content or ""

