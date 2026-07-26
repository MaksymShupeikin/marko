import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_models.dart';

class CatalogApi {
  const CatalogApi(this._client);

  final ApiClient _client;

  Future<CatalogProductPage> listProducts({
    String query = '',
    List<String>? storeIds,
    int offset = 0,
    int limit = 48,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/products',
      queryParameters: {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        if (storeIds != null && storeIds.isNotEmpty) 'store_id': storeIds,
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

  Future<CatalogCompetitorComparison> discoverCompetitors({
    String? sku,
    String? oe,
    String? brand,
    String? title,
    double? currentPrice,
    String? currency,
    String? category,
  }) async {
    final payload = await _client.postJson(
      '/api/v1/catalog/competitors/discover',
      body: {
        'sku': sku,
        'oe': oe,
        'brand': brand,
        'title': title,
        'current_price': currentPrice,
        'currency': currency,
        'category': category,
      },
    );
    return CatalogCompetitorComparison.fromJson(
      payload as Map<String, dynamic>,
    );
  }

  Future<String?> enrichOe({
    required String storeId,
    required String externalId,
  }) async {
    final payload = await _client.postJson(
      '/api/v1/catalog/products/oe',
      body: {'store_id': storeId, 'external_id': externalId},
    );
    return (payload as Map<String, dynamic>)['oe'] as String?;
  }
}

final catalogApiProvider = Provider<CatalogApi>((ref) {
  return CatalogApi(ref.watch(apiClientProvider));
});
