"""Відсіювання чужих товарів дешевою моделлю: один виклик, помилка = без фільтра."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

import openai

from marko.core.config import get_settings

log = logging.getLogger(__name__)

# Має покривати всі можливі пропозиції (_AVTOPRO_MAX_OFFERS + _PROM_MAX_OFFERS
# + _GOOGLE_MAX_OFFERS): кандидат поза лімітом не отримує вердикту і проходив
# у видачу без перевірки.
MAX_CANDIDATES = 120

# Латентність моделі росте з кількістю вердиктів у відповіді (заміряно:
# 48 кандидатів одним викликом — 15 с). Паралельні шматки повертаються
# за час найбільшого — вдвічі-втричі швидше на великих списках.
_CHUNK_SIZE = 25

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


# Другий прохід шле впʼятеро довший опис на кандидата, тож шматки менші.
_VERIFY_CHUNK_SIZE = 12

_VERIFY_SYSTEM = (
    "Ти перевіряєш пропозиції автозапчастин, за якими рахується ринкова ціна.\n"
    "Для кожного кандидата дано назву, ціну, продавця, наявність і стан,\n"
    "а також медіану ринку для цієї самої деталі. Постав категорію:\n"
    "  ok     — та сама (або взаємозамінна) НОВА деталь і справжня ціна:\n"
    "           продавець просто дешевший за ринок;\n"
    "  drop   — вживана, відновлена, з розборки; ціна за запитом чи договірна;\n"
    "           ціна за кріплення, прокладку, доставку чи одну штуку з набору;\n"
    "           ціна «від»; інша деталь, інший розмір або взагалі інший товар;\n"
    "  unsure — з наданого не видно, чи це та сама нова деталь за реальною ціною.\n"
    "Стан «невідомо» сумнівом не є: оголошення з позначками «б/у», «з розборки»,\n"
    "«відновлено» відсіяні детермінованим фільтром ще до тебе, тож деталь без\n"
    "позначки стану вважай новою й суди лише за деталлю та ціною.\n"
    "Ціна, менша за ринкову в кілька разів, майже завжди означає інший товар.\n"
    "Сумніваєшся — став unsure: пропозиція лишиться у списку, але не\n"
    "формуватиме рекомендовану ціну.\n"
    'Відповідь — лише JSON: {"verdicts": [{"index": 0, "verdict": "ok"}, ...]},'
    " по одному запису на кожного кандидата, без пояснень."
)


# Фото-перевірка: продавці вживаного часто мовчать про стан у тексті,
# і єдиним свідком лишається фотографія.
_PHOTO_SYSTEM = (
    "Ти дивишся на фото товару з оголошення про автозапчастину.\n"
    "Продавці нових деталей часто ставлять стокові чи каталожні фото, тож\n"
    "чисте «нове» фото НЕ доводить, що деталь нова. А от вживану деталь\n"
    "видають сліди ЕКСПЛУАТАЦІЇ НА АВТО. Постав категорію:\n"
    "  used     — деталь стояла на машині: бруд чи масляний наліт у\n"
    "             порожнинах, іржа, сліди прокладок або герметика на\n"
    "             фланцях, обжаті чи зношені кріпильні отвори, написи\n"
    "             маркером на корпусі (так розборки позначають, з якої\n"
    "             машини знято);\n"
    "  not_used — слідів роботи на авто не видно (це НЕ гарантія нової\n"
    "             деталі — лише відсутність доказів протилежного);\n"
    "  unsure   — фото не відкрилось, нечітке, або на ньому не деталь.\n"
    "НЕ докази вживаності: фон (в Україні й нові деталі знімають на\n"
    "картоні, верстаку чи підлозі складу), виробничі й транспортні сліди\n"
    "(потертості ребер радіатора, подряпини литва, захисне мастило, пил),\n"
    "матовий чи сірий метал.\n"
    "Сумніваєшся між used і not_used — став unsure.\n"
    "Відповідь — лише JSON: спершу доказ, потім вердикт:\n"
    '{"evidence": "що саме видно на деталі", "verdict": "used"}.'
)

_PHOTO_VERDICTS = frozenset({"used", "not_used", "unsure"})


@dataclass(frozen=True)
class OfferFacts:
    """Готові рядки про пропозицію: гроші форматує той, хто володіє звітом."""

    title: str
    price: str
    seller: str | None = None
    availability: str | None = None
    condition: str | None = None


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
    """index -> "same" | "analog" | "no"; порожньо, якщо модель недоступна.

    Кандидат зі шматка, що не відповів, лишається без вердикту — джерело
    покаже його неперевіреним, а не втратить.
    """
    if not titles or not is_enabled():
        return {}
    capped = list(titles[:MAX_CANDIDATES])
    chunks = [
        (start, capped[start : start + _CHUNK_SIZE])
        for start in range(0, len(capped), _CHUNK_SIZE)
    ]
    batches = await asyncio.gather(
        *(_classify_chunk(name, brand, oem_numbers, chunk) for _, chunk in chunks)
    )
    result: dict[int, str] = {}
    for (start, chunk), verdicts in zip(chunks, batches):
        if verdicts is None:
            continue
        # Модель мала оцінити кожного посланого кандидата: пропущений нею index
        # раніше проходив у видачу без перевірки — тепер він «не підтверджений».
        for index in range(len(chunk)):
            result[start + index] = verdicts.get(index, "no")
    return result


async def verify_offers(
    *,
    name: str,
    brand: str | None,
    oem_numbers: Sequence[str],
    market_summary: str,
    offers: Sequence[OfferFacts],
) -> dict[int, str]:
    """index -> "ok" | "drop" | "unsure"; порожньо, якщо модель недоступна.

    Другий прохід бачить те, чого не бачить перший: ціну, продавця, наявність
    і стан — та ще й медіану ринку, яка існує лише коли всі джерела вже
    відповіли. Пропущений вердикт — "unsure", а не "drop": тут неперевірена
    пропозиція знижується в довірі, а не зникає.
    """
    if not offers or not is_enabled():
        return {}
    chunks = [
        (start, offers[start : start + _VERIFY_CHUNK_SIZE])
        for start in range(0, len(offers), _VERIFY_CHUNK_SIZE)
    ]
    batches = await asyncio.gather(
        *(
            _verify_chunk(name, brand, oem_numbers, market_summary, chunk)
            for _, chunk in chunks
        )
    )
    result: dict[int, str] = {}
    for (start, chunk), verdicts in zip(chunks, batches):
        if verdicts is None:
            continue
        for index in range(len(chunk)):
            result[start + index] = verdicts.get(index, "unsure")
    return result


async def photo_condition(*, title: str, image_url: str) -> str | None:
    """"used" | "not_used" | "unsure"; None — виклик не вдався.

    None ≠ "unsure": збій vision-виклику (провайдер без зору, бите фото)
    не має понижувати пропозицію — на відміну від текстової перевірки,
    де пропущений вердикт стає "unsure".
    """
    if not is_enabled():
        return None
    try:
        raw = await _ask_openai(
            f"Оголошення: {title}",
            _PHOTO_SYSTEM,
            image_url=image_url,
            model=get_settings().competitor_photo_model or None,
        )
        verdict = json.loads(raw)["verdict"]
    except Exception as exc:  # перевірка не критична — краще без неї, ніж без цін
        log.warning("Фото-перевірка %r не спрацювала: %s", image_url, exc)
        return None
    return verdict if verdict in _PHOTO_VERDICTS else None


async def _verify_chunk(
    name: str,
    brand: str | None,
    oem_numbers: Sequence[str],
    market_summary: str,
    offers: Sequence[OfferFacts],
) -> dict[int, str] | None:
    prompt = _verify_prompt(name, brand, oem_numbers, market_summary, offers)
    try:
        verdicts = json.loads(await _ask_openai(prompt, _VERIFY_SYSTEM))["verdicts"]
    except Exception as exc:  # перевірка не критична — краще без неї, ніж без цін
        log.warning("Перевірка підозрілих пропозицій не спрацювала: %s", exc)
        return None
    result = {
        item["index"]: item["verdict"]
        for item in verdicts
        if isinstance(item.get("index"), int) and 0 <= item["index"] < len(offers)
    }
    return result or None


def _verify_prompt(
    name: str,
    brand: str | None,
    oem_numbers: Sequence[str],
    market_summary: str,
    offers: Sequence[OfferFacts],
) -> str:
    seed = [f"Наша деталь: {name}"]
    if brand:
        seed.append(f"Виробник: {brand}")
    if oem_numbers:
        seed.append(f"Каталожні номери: {', '.join(oem_numbers)}")
    seed.append(market_summary)
    lines: list[str] = []
    for index, offer in enumerate(offers):
        lines.append(f"{index}. {offer.title}")
        lines.append(f"   ціна: {offer.price}")
        if offer.seller:
            lines.append(f"   продавець: {offer.seller}")
        if offer.availability:
            lines.append(f"   наявність: {offer.availability}")
        lines.append(f"   стан: {offer.condition or 'невідомо'}")
    return "\n".join([*seed, "", "Кандидати:", *lines])


async def _classify_chunk(
    name: str,
    brand: str | None,
    oem_numbers: Sequence[str],
    titles: Sequence[str],
) -> dict[int, str] | None:
    prompt = _prompt(name, brand, oem_numbers, titles)
    try:
        verdicts = json.loads(await _ask_openai(prompt, _SYSTEM))["verdicts"]
    except Exception as exc:  # фільтр не критичний — краще без нього, ніж без цін
        log.warning("LLM-фільтр пропозицій не спрацював: %s", exc)
        return None
    result = {
        item["index"]: item["verdict"]
        for item in verdicts
        if isinstance(item.get("index"), int) and 0 <= item["index"] < len(titles)
    }
    return result or None


async def _ask_openai(
    prompt: str,
    system: str = _SYSTEM,
    *,
    image_url: str | None = None,
    model: str | None = None,
) -> str:
    # json_object, а не json_schema: його розуміють усі сумісні провайдери,
    # а форму відповіді все одно перевіряє classify().
    settings = get_settings()
    # Заміряно на 58 кандидатах (gpt-5-nano): default 12.4 c, low 7.0 c з тим
    # самим результатом, minimal 4.0 c — і 10 чужих позицій у видачі.
    # Чужий base_url може не знати цього параметра, тож лише для самого OpenAI.
    extra = {} if settings.openai_base_url else {"reasoning_effort": "low"}
    content: str | list[dict[str, Any]] = prompt
    if image_url is not None:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    response = await _openai().chat.completions.create(
        model=model or settings.competitor_filter_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        **extra,
    )
    return response.choices[0].message.content or ""

