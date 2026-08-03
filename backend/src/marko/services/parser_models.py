"""Domain data models and the raw-to-Product mapping."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_SELLER_URL_RE = re.compile(
    r"prom\.ua/(?P<lang>[a-z]{2})/c(?P<company_id>\d+)-(?P<slug>[\w-]+)\.html", re.I
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
    # Root-to-leaf category ancestry, e.g. [0, 55, 5502, 341529, 341550].
    # Native Prom search field; lets deterministic gates reason about the
    # product domain without fetching the marketplace category taxonomy.
    "category_ids": "categoryIds",
    "brand": "manufacturerInfo.name",
    "model_id": "model.id",  # cross-seller model identity (may be absent)
    "seller_id": "company.id",  # present in search results
    "seller_name": "company.name",
    "seller_slug": "company.slug",
    "opinions_count": "productOpinionCounters.count",
    "opinions_rating": "productOpinionCounters.rating",
    "image": "imageAlt",
    "url_text": "urlText",
    "description": "description",
    # Additive post-parse/enrichment boundary. The frozen network parser may
    # leave every field below absent; UNKNOWN is preserved downstream.
    "oe_raw": "comparisonEvidence.oeRaw",
    "fitment": "comparisonEvidence.fitment",
    "vehicle_generation": "comparisonEvidence.vehicleGeneration",
    "year_from": "comparisonEvidence.yearFrom",
    "year_to": "comparisonEvidence.yearTo",
    "engine": "comparisonEvidence.engine",
    "body_variant": "comparisonEvidence.bodyVariant",
    "side": "comparisonEvidence.side",
    "position": "comparisonEvidence.position",
    "condition": "comparisonEvidence.condition",
    "package_quantity": "comparisonEvidence.packageQuantity",
    "characteristics": "characteristics",
}

# Raw keys used as fallbacks when the primary nested path is absent.
_FALLBACK_KEYS = {
    "model_id": "newModelId",
    "seller_id": "company_id",
    "oe_raw": "oe",
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
    category_ids: list[int] | None
    brand: str | None
    model_id: str | None
    seller_id: int | None
    seller_name: str | None
    seller_slug: str | None
    opinions_count: int | None
    opinions_rating: float | None
    image: str | None
    url_text: str | None
    oe_raw: str | None
    fitment: str | None
    vehicle_generation: str | None
    year_from: int | None
    year_to: int | None
    engine: str | None
    body_variant: str | None
    side: str | None
    position: str | None
    condition: str | None
    package_quantity: int | None
    characteristics: Any
    description: str | None
    url: str | None  # calculated, not from map; kept last for CSV compatibility

    @classmethod
    def from_raw(cls, raw: dict, lang: str = "ua") -> Product:
        """Create a Product from a raw product object in the Apollo cache."""
        values = {
            name: get_nested(raw, path) for name, path in _FIELDS_PATH_MAP.items()
        }
        for name, raw_key in _FALLBACK_KEYS.items():
            if values[name] is None:
                values[name] = raw.get(raw_key)
        # Product-card responses currently expose the description under
        # descriptionPlain/descriptionFull, while listing/search responses may
        # still use description.  Keep the normalized boundary stable and
        # prefer the plain-text representation for deterministic cross parsing.
        if values["description"] is None:
            values["description"] = raw.get("descriptionPlain") or raw.get(
                "descriptionFull"
            )
        values["url"] = cls._build_url(values["id"], values["url_text"], lang)
        return cls(**values)

    @staticmethod
    def _build_url(product_id: Any, url_text: Any, lang: str) -> str | None:
        if not product_id or not url_text:
            return None
        return f"https://prom.ua/{lang}/p{product_id}-{url_text}.html"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_normalized_snapshot(cls, snapshot: dict[str, Any]) -> Product:
        """Restore an additive normalized snapshot without re-parsing Apollo keys.

        Older retained snapshots can lack fields added to ``Product`` later.
        Those fields remain ``None`` so downstream gates fail closed. Unknown
        fields are rejected instead of being silently discarded as schema drift.
        """

        field_names = set(cls.field_names())
        unknown = sorted(set(snapshot) - field_names)
        if unknown:
            raise ValueError(f"Unknown normalized Product fields: {unknown}")
        values = {name: snapshot.get(name) for name in cls.field_names()}
        return cls(**values)

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
        match = _SELLER_URL_RE.search(url)
        if not match:
            raise ValueError(
                f"Не схоже на URL продавця prom.ua: {url!r}\n"
                "Очікую щось на кшталт https://prom.ua/ua/c2847093-kemp.html"
            )
        return cls(
            company_id=match.group("company_id"),
            slug=match.group("slug"),
            lang=match.group("lang").lower(),
        )


@dataclass(frozen=True)
class ListingPage:
    """Result of parsing one listing page."""

    products: list[Product]
    total: int | None
    lang: str
    outcome: str = "RESULTS"

    @property
    def is_empty(self) -> bool:
        return not self.products


@dataclass(frozen=True)
class SeedInfo:
    """The reference product to compare, plus prom.ua's own buyBox summary."""

    product: Product
    seller_count: int | None  # how many sellers offer this exact model (buyBox)
    min_price: Decimal | None
    max_price: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_price", _optional_decimal(self.min_price))
        object.__setattr__(self, "max_price", _optional_decimal(self.max_price))


def _optional_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


@dataclass(frozen=True)
class MotorsVehicle:
    """One vehicle prom.ua's automotive catalogue says the part fits.

    Kept structured rather than flattened to a caption because this is the
    applicability data WP-5 has been missing: ``comparability.yaml`` knows seven
    marques against forty-six observed in the catalogue, and this arrives with
    the engine and the production window already separated.
    """

    manufacturer: str
    model: str
    engine: str | None = None
    horsepower: int | None = None
    fuel_type: str | None = None
    drive_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    @property
    def caption(self) -> str:
        parts = [self.manufacturer, self.model]
        if self.engine:
            parts.append(self.engine)
        if self.date_from or self.date_to:
            parts.append(f"{(self.date_from or '')[:7]}..{(self.date_to or '')[:7]}")
        return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class MotorsContext:
    """What prom.ua's automotive vertical says about one product card.

    This is the marketplace's own answer to the question three work packages
    tried to reconstruct from the customer's spreadsheets: which normalized part
    code this is, which OE numbers supersede it, and what it fits.  The listing
    behind ``oe_page_url`` is the cross-seller market for that code.
    """

    normalized_part_code: str | None
    part_group_id: int | None
    oe_page_id: int | None
    oe_page_alias: str | None
    #: The number whose listing was taken.  Equal to ``normalized_part_code``
    #: normally; different when our own code has no listing and one from its
    #: supersession chain was used instead, which is a widening and must be
    #: visible to whatever grades the offers.
    via_oe_number: str | None = None
    #: Supersession chain, normalized, our own code first when present.
    compatible_oe_numbers: tuple[str, ...] = ()
    compatible_vehicles: tuple[MotorsVehicle, ...] = ()
    images: tuple[str, ...] = ()

    @property
    def is_widened(self) -> bool:
        """Whether the listing belongs to a related number rather than ours."""

        return bool(
            self.via_oe_number
            and self.normalized_part_code
            and self.via_oe_number != self.normalized_part_code
        )

    @property
    def has_oe_page(self) -> bool:
        return self.oe_page_id is not None and bool(self.oe_page_alias)

    def oe_page_url(self, lang: str = "ua") -> str | None:
        """Where the cross-seller offers for this code live, or nothing.

        Measured 2026-07-31: 28 of 40 catalogue positions have such a page, so
        the absence is ordinary and the caller must have another route.
        """

        if not self.has_oe_page:
            return None
        return f"https://prom.ua/{lang}/auto/oen/{self.oe_page_id}-{self.oe_page_alias}"
