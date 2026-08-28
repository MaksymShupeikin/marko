import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'products_models.dart';

class ProductsApi {
  const ProductsApi(this._client);

  final ApiClient _client;

  Future<CatalogPage> search({
    String query = '',
    ProductSort sort = ProductSort.name,
    double? priceMin,
    double? priceMax,
    ProductSource source = ProductSource.all,
    Set<String> storeIds = const {},
    int limit = 60,
    int offset = 0,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/products',
      queryParameters: {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        'sort': sort.value,
        if (priceMin != null) 'price_min': '$priceMin',
        if (priceMax != null) 'price_max': '$priceMax',
        if (source.value != null) 'source': source.value!,
        if (storeIds.isNotEmpty) 'store_ids': storeIds.join(','),
        'limit': '$limit',
        'offset': '$offset',
      },
    );
    return CatalogPage.fromJson(payload as Map<String, dynamic>);
  }

  /// The catalog filter a bulk action applies to; empty means the whole catalog.
  Map<String, dynamic> _filterBody({
    String query = '',
    double? priceMin,
    double? priceMax,
    ProductSource source = ProductSource.all,
    Set<String> storeIds = const {},
  }) => {
    if (query.trim().isNotEmpty) 'q': query.trim(),
    'price_min': ?priceMin,
    'price_max': ?priceMax,
    'source': ?source.value,
    if (storeIds.isNotEmpty) 'store_ids': [...storeIds],
  };

  /// Hides every product the filter matches. Returns how many were hidden.
  Future<int> deleteAllMatching({
    String query = '',
    double? priceMin,
    double? priceMax,
    ProductSource source = ProductSource.all,
    Set<String> storeIds = const {},
  }) async {
    final payload = await _client.postJson(
      '/api/v1/products/bulk/delete',
      body: _filterBody(
        query: query,
        priceMin: priceMin,
        priceMax: priceMax,
        source: source,
        storeIds: storeIds,
      ),
    );
    return ((payload as Map<String, dynamic>)['deleted'] as num).toInt();
  }

  /// Queues a re-read of every matching product; follow it through /jobs.
  Future<StoreSync> refreshAllMatching({
    String query = '',
    double? priceMin,
    double? priceMax,
    ProductSource source = ProductSource.all,
    Set<String> storeIds = const {},
  }) async {
    final payload = await _client.postJson(
      '/api/v1/products/bulk/refresh',
      body: _filterBody(
        query: query,
        priceMin: priceMin,
        priceMax: priceMax,
        source: source,
        storeIds: storeIds,
      ),
    );
    return StoreSync.fromJson(payload as Map<String, dynamic>);
  }

  Future<FileImportResult> importCatalogFile(
    String filename,
    List<int> bytes,
  ) async {
    final payload = await _client.postFile(
      '/api/v1/stores/import-file',
      field: 'file',
      filename: filename,
      bytes: bytes,
    );
    return FileImportResult.fromJson(payload as Map<String, dynamic>);
  }

  /// Підключені магазини воркспейсу — для стрічки над каталогом.
  Future<List<StoreInfo>> listStores() async {
    final payload = await _client.getJson('/api/v1/stores');
    return [
      for (final item in payload as List<dynamic>)
        StoreInfo.fromJson(item as Map<String, dynamic>),
    ];
  }

  Future<StoreSync> addStore(String url) async {
    final payload = await _client.postJson(
      '/api/v1/stores',
      body: {'url': url},
    );
    return StoreSync.fromJson(payload as Map<String, dynamic>);
  }

  Future<SyncRun> getJob(String id) async {
    final payload = await _client.getJson('/api/v1/jobs/$id');
    return SyncRun.fromJson(payload as Map<String, dynamic>);
  }

  /// Черга імпортів у порядку виконання: перший вантажиться, решта чекає.
  ///
  /// Бекенд віддає тут і поступ, і назву магазину, тож опитувати кожен
  /// запуск окремо не треба — одного запиту вистачає на всю чергу.
  Future<List<ActiveSyncRun>> getActiveJobs() async {
    final payload = await _client.getJson('/api/v1/jobs/active');
    return [
      for (final item in payload as List<dynamic>)
        ActiveSyncRun.fromJson(item as Map<String, dynamic>),
    ];
  }

  Future<void> cancelJob(String id) async {
    await _client.postJson('/api/v1/jobs/$id/cancel');
  }

  /// Ручний пошук за OEM/брендом — той самий конвеєр, що й у картці товару.
  Stream<Map<String, dynamic>> competitorSearchEvents(
    String oem, {
    String? brand,
  }) {
    return _client.streamJson(
      '/api/v1/competitors/search/stream',
      queryParameters: {
        'oem': oem,
        if (brand != null && brand.isNotEmpty) 'brand': brand,
      },
    );
  }

  Future<CompetitorPriceReport> competitorPrices(
    String productId, {
    bool refresh = false,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/products/$productId/competitor-prices',
      queryParameters: {if (refresh) 'refresh': 'true'},
    );
    return CompetitorPriceReport.fromJson(payload as Map<String, dynamic>);
  }

  /// Той самий звіт, але з подіями стадій: `{stage, message}`, далі `{stage: done, report}`.
  Stream<Map<String, dynamic>> competitorPriceEvents(
    String productId, {
    bool refresh = false,
  }) {
    return _client.streamJson(
      '/api/v1/products/$productId/competitor-prices/stream',
      queryParameters: {if (refresh) 'refresh': 'true'},
    );
  }

  Future<StoreProduct> updateProduct(
    String productId,
    ProductUpdate update,
  ) async {
    final payload = await _client.patchJson(
      '/api/v1/products/$productId',
      body: update.toJson(),
    );
    return StoreProduct.fromJson(payload as Map<String, dynamic>);
  }

  Future<StoreProduct> refreshProduct(String productId) async {
    final payload = await _client.postJson(
      '/api/v1/products/$productId/refresh',
    );
    return StoreProduct.fromJson(payload as Map<String, dynamic>);
  }

  Future<void> deleteProduct(String productId) async {
    await _client.deleteJson('/api/v1/products/$productId');
  }
}

final productsApiProvider = Provider<ProductsApi>((ref) {
  return ProductsApi(ref.watch(apiClientProvider));
});
