"""Схема позиции каталога обязана читаться со строки каталога.

`_catalog_item_response` собирает ответ через `getattr` по именам полей схемы,
поэтому поле, которого нет у ORM-модели, роняет `GET /api/v1/catalog/items`
целиком — а этот эндпоинт открывает пользователю запуск прогона. Так в схему
попало `is_owned` (свойство продавца, не позиции), и список позиций отвечал 500
две с половиной недели: тестов на этот контракт не было.
"""

from marko.api.routers.v1.catalog import DERIVED_CATALOG_ITEM_FIELDS
from marko.api.schemas.catalog import CatalogItemResponse
from marko.infrastructure.db.models import CatalogItem


def test_every_read_field_of_the_response_exists_on_the_catalog_row() -> None:
    read_fields = set(CatalogItemResponse.model_fields) - DERIVED_CATALOG_ITEM_FIELDS

    missing = sorted(field for field in read_fields if not hasattr(CatalogItem, field))

    assert missing == [], (
        "поля схемы отсутствуют у CatalogItem и уронят /catalog/items: "
        f"{missing}"
    )


def test_derived_fields_are_declared_by_the_response() -> None:
    unknown = sorted(DERIVED_CATALOG_ITEM_FIELDS - set(CatalogItemResponse.model_fields))

    assert unknown == [], f"исключения ссылаются на несуществующие поля: {unknown}"


def test_seller_ownership_is_not_a_catalog_item_field() -> None:
    assert "is_owned" not in CatalogItemResponse.model_fields
