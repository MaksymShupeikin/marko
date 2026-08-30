"""Фото-перевірка вживаності: кеш вердиктів по URL і vision-виклик моделі."""
import json

from marko.services import llm_filter, photo_check


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex


class _DeadRedis:
    async def get(self, key):
        raise ConnectionError("redis лежить")

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis лежить")


def _candidate(n: int = 1) -> photo_check.PhotoCandidate:
    return photo_check.PhotoCandidate(
        url=f"https://prom.ua/p{n}",
        title=f"Насос {n}",
        image_url=f"https://images.prom.ua/{n}.jpg",
    )


async def test_cached_photo_verdict_skips_the_llm_call(monkeypatch):
    """Той самий лістинг у звітах різних товарів платить за модель один раз."""
    redis = _FakeRedis()
    monkeypatch.setattr(photo_check, "_redis", lambda: redis)
    calls: list[str] = []

    async def fake_condition(*, title, image_url):
        calls.append(image_url)
        return "used"

    monkeypatch.setattr(llm_filter, "photo_condition", fake_condition)

    first = await photo_check.condition_verdicts([_candidate()])
    assert first == {"https://prom.ua/p1": "used"}
    assert len(calls) == 1

    second = await photo_check.condition_verdicts([_candidate()])
    assert second == first
    assert len(calls) == 1  # вердикт прийшов із кешу

    key = photo_check._cache_key("https://prom.ua/p1")
    assert redis.ttls[key] == photo_check._CACHE_TTL


async def test_unsure_verdict_is_cached_for_a_shorter_time(monkeypatch):
    """Сумнів не заморожуємо на тиждень: фото могли замінити."""
    redis = _FakeRedis()
    monkeypatch.setattr(photo_check, "_redis", lambda: redis)

    async def fake_condition(*, title, image_url):
        return "unsure"

    monkeypatch.setattr(llm_filter, "photo_condition", fake_condition)

    await photo_check.condition_verdicts([_candidate()])
    key = photo_check._cache_key("https://prom.ua/p1")
    assert redis.ttls[key] == photo_check._UNSURE_TTL


async def test_failed_call_is_neither_returned_nor_cached(monkeypatch):
    """Збій виклику — не вердикт: наступний звіт спробує ще раз."""
    redis = _FakeRedis()
    monkeypatch.setattr(photo_check, "_redis", lambda: redis)

    async def fake_condition(*, title, image_url):
        return None

    monkeypatch.setattr(llm_filter, "photo_condition", fake_condition)

    verdicts = await photo_check.condition_verdicts([_candidate()])
    assert verdicts == {}
    assert redis.store == {}


async def test_dead_redis_degrades_to_direct_llm_calls(monkeypatch):
    """Мертвий Redis — не привід лишати звіт без фото-перевірки."""
    monkeypatch.setattr(photo_check, "_redis", lambda: _DeadRedis())

    async def fake_condition(*, title, image_url):
        return "used"

    monkeypatch.setattr(llm_filter, "photo_condition", fake_condition)

    verdicts = await photo_check.condition_verdicts([_candidate()])
    assert verdicts == {"https://prom.ua/p1": "used"}


async def test_photo_condition_sends_image_as_content_part(monkeypatch):
    """Фото їде окремою частиною повідомлення, а не текстом у промпті."""
    monkeypatch.setattr(llm_filter, "is_enabled", lambda: True)
    seen: dict = {}

    async def fake_ask(prompt, system=llm_filter._SYSTEM, *, image_url=None, model=None):
        seen["prompt"] = prompt
        seen["system"] = system
        seen["image_url"] = image_url
        seen["model"] = model
        return json.dumps({"verdict": "used"})

    monkeypatch.setattr(llm_filter, "_ask_openai", fake_ask)

    verdict = await llm_filter.photo_condition(
        title="Вакуумний насос", image_url="https://images.prom.ua/pump.jpg"
    )
    assert verdict == "used"
    assert seen["image_url"] == "https://images.prom.ua/pump.jpg"
    assert seen["system"] == llm_filter._PHOTO_SYSTEM
    assert "Вакуумний насос" in seen["prompt"]


async def test_invalid_or_failed_photo_verdict_becomes_none(monkeypatch):
    """Чужий вердикт чи збій виклику — None, а не «сумнів»."""
    monkeypatch.setattr(llm_filter, "is_enabled", lambda: True)

    async def weird_ask(prompt, system=llm_filter._SYSTEM, **_kwargs):
        return '{"verdict": "maybe"}'

    monkeypatch.setattr(llm_filter, "_ask_openai", weird_ask)
    assert (
        await llm_filter.photo_condition(title="Насос", image_url="https://i/1.jpg")
        is None
    )

    async def broken_ask(prompt, system=llm_filter._SYSTEM, **_kwargs):
        raise RuntimeError("провайдер без зору")

    monkeypatch.setattr(llm_filter, "_ask_openai", broken_ask)
    assert (
        await llm_filter.photo_condition(title="Насос", image_url="https://i/1.jpg")
        is None
    )
