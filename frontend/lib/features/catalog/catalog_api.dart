import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_models.dart';

class CatalogApi {
  const CatalogApi(this._client);

  final ApiClient _client;

  Future<CatalogProductPage> listProducts({
    String query = '',
    String? storeId,
    int offset = 0,
    int limit = 48,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/products',
      queryParameters: {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        'store_id': ?storeId,
        'limit': '$limit',
        'offset': '$offset',
      },
    );
    return CatalogProductPage.fromJson(payload as Map<String, dynamic>);
  }

  Future<CatalogCompetitorComparison> listCompetitors({
    String? sku,
    String? oe,
    String? brand,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/competitors',
      queryParameters: {'sku': ?sku, 'oe': ?oe, 'brand': ?brand},
    );
    return CatalogCompetitorComparison.fromJson(
      payload as Map<String, dynamic>,
    );
  }
}

final catalogApiProvider = Provider<CatalogApi>((ref) {
  return CatalogApi(ref.watch(apiClientProvider));
});
