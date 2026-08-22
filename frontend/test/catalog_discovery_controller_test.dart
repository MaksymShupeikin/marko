import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';

/// Сбор объявлений по карточке без OE и MPN.
///
/// Витрина магазина несёт два разных внешних номера — магазина
/// (`external_id`) и объявления (`source_listing_id`). Починка карточки
/// адресуется объявлением; подстановка номера магазина давала
/// гарантированный 404 «Catalog listing not found» и отменяла сбор целиком
/// у 26 686 карточек Prom из 38 375. Проверка живёт на уровне контроллера:
/// именно он выбирает значение, а слой HTTP отправляет «какое дали» и
/// подмену поймать не может.
void main() {
  test('починка карточки адресуется номером объявления, а не магазина', () async {
    final api = _DiscoveryCatalogApi();
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    await container.read(catalogControllerProvider.future);

    await container
        .read(catalogControllerProvider.notifier)
        .discoverCompetitors(_product());

    expect(api.enrichedExternalIds, ['3055129043']);
    expect(api.enrichedStoreIds, ['store-uuid']);
    expect(api.discoveredSkus, ['2141006']);
  });

  test('отказ починки не отменяет сбор', () async {
    final api = _DiscoveryCatalogApi(
      enrichFailure: const ApiException(
        'Catalog listing not found',
        statusCode: 404,
      ),
    );
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    await container.read(catalogControllerProvider.future);

    await container
        .read(catalogControllerProvider.notifier)
        .discoverCompetitors(_product());

    expect(api.enrichedExternalIds, ['3055129043']);
    expect(api.discoveredSkus, ['2141006']);
    expect(api.discoveredOes, [null]);
    expect(api.discoveredMpns, [null]);
  });

  test('протухшая сессия не проглатывается молча', () async {
    final api = _DiscoveryCatalogApi(
      enrichFailure: const ApiException(
        'Authentication required',
        statusCode: 401,
      ),
    );
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    await container.read(catalogControllerProvider.future);

    await expectLater(
      container
          .read(catalogControllerProvider.notifier)
          .discoverCompetitors(_product()),
      throwsA(isA<ApiException>()),
    );
    expect(api.discoveredSkus, isEmpty);
  });

  test('без номера объявления починка не запрашивается вовсе', () async {
    final api = _DiscoveryCatalogApi();
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    await container.read(catalogControllerProvider.future);

    await container
        .read(catalogControllerProvider.notifier)
        .discoverCompetitors(_product(sourceListingId: null));

    expect(api.enrichedExternalIds, isEmpty);
    expect(api.discoveredSkus, ['2141006']);
  });

  test('таймаут сбора покрывает измеренную длительность живого сбора', () {
    // Завершённые сборы по catalog_discovery_runs: 2:18, 3:34, 4:18.
    // На прежних двух минутах клиент обрывался раньше сервера, и оператор
    // видел «Сбор не завершён: TimeoutException» на 99 собранных
    // объявлениях.
    expect(catalogDiscoveryTimeout, greaterThan(const Duration(minutes: 5)));
  });

  test('у карточки с OE починка не нужна и не запрашивается', () async {
    final api = _DiscoveryCatalogApi();
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    await container.read(catalogControllerProvider.future);

    await container
        .read(catalogControllerProvider.notifier)
        .discoverCompetitors(_product(oe: '2141006'));

    expect(api.enrichedExternalIds, isEmpty);
    expect(api.discoveredOes, ['2141006']);
  });
}

CatalogProduct _product({
  String? oe,
  String? sourceListingId = '3055129043',
}) {
  return CatalogProduct(
    id: '1d62cf0f-008e-54a2-3207-102640412666',
    identityKind: oe == null ? 'sku' : 'oe',
    name: '(6шт) Шпилька \\ болт передньої ступиці (колісна) Mercedes 509',
    sku: '2141006',
    oe: oe,
    mpn: null,
    modelId: null,
    brand: 'Mercedes-Benz',
    imageUrl: null,
    priceMin: '720.00',
    priceMax: '720.00',
    currency: 'UAH',
    listingCount: 1,
    internalCode: '2141006',
    kempLinkStatus: 'UNLINKED_PROM_DIAGNOSTIC',
    stores: [
      CatalogStorePresence(
        storeId: 'store-uuid',
        // Внешний номер магазина parts-avto — в базе нет ни одного
        // объявления с таким external_id, поэтому подстановка этого
        // значения в починку всегда возвращала 404.
        externalId: '3912822',
        name: 'parts-avto',
        url: 'https://parts-avto.prom.ua',
        listingUrl: 'https://prom.ua/ua/p3055129043-6sht-shpilka-bolt.html',
        listingCount: 1,
        price: '720.00',
        currency: 'UAH',
        isAvailable: true,
        listingId: '46579838-bb72-4446-b7f1-1ee087ad2333',
        sourceListingId: sourceListingId,
      ),
    ],
  );
}

class _DiscoveryCatalogApi extends CatalogApi {
  _DiscoveryCatalogApi({this.enrichFailure})
    : super(
        ApiClient(
          client: MockClient((_) async => throw UnimplementedError()),
          baseUrl: 'http://api.test',
        ),
      );

  final Object? enrichFailure;
  final List<String> enrichedExternalIds = [];
  final List<String> enrichedStoreIds = [];
  final List<String?> discoveredSkus = [];
  final List<String?> discoveredOes = [];
  final List<String?> discoveredMpns = [];

  @override
  Future<CatalogProductPage> listProducts({
    String query = '',
    List<String>? storeIds,
    int offset = 0,
    int limit = 48,
    String? kempStatus,
    bool noOem = false,
  }) async {
    return const CatalogProductPage(
      items: [],
      total: 0,
      catalogTotal: 0,
      listingTotal: 0,
      duplicatesRemoved: 0,
      storeTotal: 1,
      stores: [],
    );
  }

  @override
  Future<CatalogIdentifierEnrichment> enrichIdentifiers({
    required String storeId,
    required String externalId,
  }) async {
    enrichedStoreIds.add(storeId);
    enrichedExternalIds.add(externalId);
    final failure = enrichFailure;
    if (failure != null) throw failure;
    return const CatalogIdentifierEnrichment(
      oe: null,
      mpn: null,
      status: 'NO_IDENTIFIER',
    );
  }

  @override
  Future<CatalogCompetitorComparison> discoverCompetitors({
    String? sku,
    String? oe,
    String? mpn,
    String? brand,
    String? title,
    Object? currentPrice,
    String? currency,
    String? category,
  }) async {
    discoveredSkus.add(sku);
    discoveredOes.add(oe);
    discoveredMpns.add(mpn);
    return CatalogCompetitorComparison(
      recommendationId: null,
      comparedAt: null,
      currentPrice: null,
      fairPrice: null,
      recommendedPrice: null,
      currency: 'UAH',
      reasonCodes: const [],
      items: const [],
    );
  }
}
