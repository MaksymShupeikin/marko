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
        'limit': '$limit',
        'offset': '$offset',
      },
    );
    return CatalogPage.fromJson(payload as Map<String, dynamic>);
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

  Future<CompetitorSearch> searchCompetitors(
    String oem, {
    String? brand,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/competitors/avtopro',
      queryParameters: {
        'oem': oem,
        if (brand != null && brand.isNotEmpty) 'brand': brand,
      },
    );
    return CompetitorSearch.fromJson(payload as Map<String, dynamic>);
  }
}

final productsApiProvider = Provider<ProductsApi>((ref) {
  return ProductsApi(ref.watch(apiClientProvider));
});
