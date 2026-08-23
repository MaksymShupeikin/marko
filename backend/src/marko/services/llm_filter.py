"""Відсіювання чужих товарів дешевою моделлю: один виклик, помилка = без фільтра."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Sequence

import anthropic
import openai

from marko.core.config import get_settings

log = logging.getLogger(__name__)

# Більше кандидатів в одному запиті не дає користі: далі йде вже сміття,
# яке евристика й так поставила в кінець.
MAX_CANDIDATES = 80

_SYSTEM = (
    "Ти підбираєш конкурентні пропозиції для автозапчастини на українському ринку.\n"
    "Для кожного кандидата з нумерованого списку постав категорію:\n"
    "  same   — та сама деталь: той самий вузол, та сама сторона й позиція,\n"
    "           та сама машина або той самий каталожний номер;\n"
    "  analog — інший виробник чи артикул, але деталь взаємозамінна з нашою;\n"
    "  no     — інший вузол, інша сторона, інша машина, інший розмір,\n"
    "           комплект замість однієї деталі, вживана деталь замість нової,\n"
    "           аксесуар до деталі (кріплення, прокладка) або зовсім інший товар.\n"
    "Сумніваєшся — став no: краще менше пропозицій, ніж чужі в порівнянні цін.\n"
    'Відповідь — лише JSON: {"verdicts": [{"index": 0, "verdict": "same"}, ...]},'
    " по одному запису на кожного кандидата, без пояснень."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["same", "analog", "no"]},
                },
                "required": ["index", "verdict"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def _is_claude() -> bool:
    return get_settings().competitor_filter_model.startswith("claude")


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.anthropic_api_key if _is_claude() else settings.openai_api_key)


@lru_cache
def _anthropic() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)


@lru_cache
def _openai() -> openai.AsyncOpenAI:
    """Один клієнт на всі OpenAI-сумісні API — DeepSeek відрізняє лише base_url."""
    settings = get_settings()
    return openai.AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
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
        ask = _ask_claude if _is_claude() else _ask_openai
        verdicts = json.loads(await ask(prompt))["verdicts"]
    except Exception as exc:  # фільтр не критичний — краще без нього, ніж без цін
        log.warning("LLM-фільтр пропозицій не спрацював: %s", exc)
        return {}
    return {
        item["index"]: item["verdict"]
        for item in verdicts
        if isinstance(item.get("index"), int) and 0 <= item["index"] < len(titles)
    }


async def _ask_claude(prompt: str) -> str:
    response = await _anthropic().messages.create(
        model=get_settings().competitor_filter_model,
        max_tokens=4000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    return next(block.text for block in response.content if block.type == "text")


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
