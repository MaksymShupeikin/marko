"""Domain data models and the raw-to-Product mapping."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_SELLER_LANGUAGE = "ua"
_PRICE_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _is_positive(value: object) -> bool:
    """Чи є в рядку сума більша за нуль — порожнє й "0" за ціну не рахуємо."""
    if value is None:
        return False
    match = _PRICE_NUMBER_RE.search(str(value).replace(" ", "").replace(" ", ""))
    if match is None:
        return False
    try:
        return float(match.group().replace(",", ".")) > 0
    except ValueError:
        return False


_PROM_HOSTS = frozenset({"prom.ua", "www.prom.ua"})
_SELLER_PATH_RE = re.compile(
    r"^/(?:(?P<lang>[a-z]{2})/)?c(?P<company_id>\d+)-(?P<slug>[\w-]+)\.html/?$",
    re.I,
)

# Single source of truth: Product field name mapped to its JSON path.
_FIELDS_PATH_MAP = {
    "id": "id",
    "name": "name",
    "sku": "sku",
    "price": "price",
    "price_original": "priceOriginal",
    "discounted_price": "discountedPrice",
    "has_discount": "hasDiscount",
    "currency": "priceCurrency",
    "price_usd": "priceUSD",
    "presence": "presence.presence",
    "is_available": "presence.isAvailable",
    "measure_unit": "measureUnit",
    "category_id": "categoryId",
    "brand": "manufacturerInfo.name",
    "model_id": "model.id",          # cross-seller model identity (may be absent)
    "seller_id": "company.id",       # present in search results
    "seller_name": "company.name",
    "seller_slug": "company.slug",
    "opinions_count": "productOpinionCounters.count",
    "opinions_rating": "productOpinionCounters.rating",
    "image": "imageAlt",
    "url_text": "urlText",
}

# Raw keys tried in order when the primary nested path is absent.
_FALLBACK_KEYS = {
    "model_id": ("newModelId",),
    "seller_id": ("company_id",),
    # Картка товару не має imageAlt — головне фото лежить в image (700x500).
    # Без цього оновлення за посиланням стирало зображення.
    "image": ("image", "image400x400", "imageGallery"),
}


def get_nested(data: dict, path: str) -> Any:
    """Get a nested value from a dict by dot path, e.g. ``company.name``."""
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


@dataclass(frozen=True)
class Product:
    """Normalized product. Field order defines CSV column order."""
    id: int | None
    name: str | None
    sku: str | None
    price: str | None
    price_original: str | None
    discounted_price: str | None
    has_discount: bool | None
    currency: str | None
    price_usd: str | None
    presence: str | None
    is_available: bool | None
    measure_unit: str | None
    category_id: int | None
    brand: str | None
    model_id: str | None
    seller_id: int | None
    seller_name: str | None
    seller_slug: str | None
    opinions_count: int | None
    opinions_rating: float | None
    image: str | None
    url_text: str | None
    url: str | None  # calculated, not from map
    # Part numbers to look up on avto.pro, best first. Only file imports carry
    # more than one; scraped products get whatever `sku` holds.
    oem_numbers: tuple[str, ...] = ()

    @classmethod
    def from_raw(cls, raw: dict, lang: str = "ua") -> Product:
        """Create a Product from a raw product object in the Apollo cache."""
        values = {name: get_nested(raw, path) for name, path in _FIELDS_PATH_MAP.items()}
        for name, raw_keys in _FALLBACK_KEYS.items():
            if values[name] is None:
                values[name] = next(
                    (raw[key] for key in raw_keys if raw.get(key)), None
                )
        values["url"] = cls._build_url(values["id"], values["url_text"], lang)
        return cls(**values)

    @staticmethod
    def _build_url(product_id: Any, url_text: Any, lang: str) -> str | None:
        if not product_id or not url_text:
            return None
        return f"https://prom.ua/{lang}/p{product_id}-{url_text}.html"

    @property
    def effective_price(self) -> str | None:
        """Ціна, яку платить покупець.

        У ``price`` лежить закреслена ціна до знижки — саме її показував
        каталог, поки на сторінці стояла інша. Prom рендерить
        ``discountedPrice``, коли ``hasDiscount``; робимо так само.

        Нуль — не ціна: Prom кладе "0" у ``price`` для товарів, де сума
        живе в іншому полі, і картка показувала 0 грн там, де на сайті
        стояло 200. Тому перебираємо поля, доки не трапиться додатне.
        """
        candidates = (
            self.discounted_price if self.has_discount else None,
            self.price,
            self.price_original,
        )
        return next((value for value in candidates if _is_positive(value)), None)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def field_names(cls) -> list[str]:
        """Column names in stable order for the CSV header."""
        return list(cls.__dataclass_fields__.keys())


@dataclass(frozen=True)
class Seller:
    """Seller info parsed from a seller URL."""
    company_id: str
    slug: str
    lang: str

    @property
    def listing_url(self) -> str:
        return f"https://prom.ua/{self.lang}/c{self.company_id}-{self.slug}.html"

    @classmethod
    def from_url(cls, url: str) -> Seller:
        parsed_url = urlsplit(url)
        match = _SELLER_PATH_RE.fullmatch(parsed_url.path)
        if (
            parsed_url.scheme.lower() not in {"http", "https"}
            or parsed_url.hostname not in _PROM_HOSTS
            or match is None
        ):
            raise ValueError(
                f"Не схоже на URL продавця prom.ua: {url!r}\n"
                "Очікую https://prom.ua/c2847093-kemp.html або "
                "https://prom.ua/ua/c2847093-kemp.html"
            )
        return cls(
            company_id=match.group("company_id"),
            slug=match.group("slug"),
            lang=(match.group("lang") or _DEFAULT_SELLER_LANGUAGE).lower(),
        )


@dataclass(frozen=True)
class ListingPage:
    """Result of parsing one listing page."""
    products: list[Product]
    total: int | None
    lang: str

    @property
    def is_empty(self) -> bool:
        return not self.products


@dataclass(frozen=True)
class SeedInfo:
    """The reference product to compare, plus prom.ua's own buyBox summary."""
    product: Product
    seller_count: int | None  # how many sellers offer this exact model (buyBox)
    min_price: float | None
    max_price: float | None
