import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_models.dart';

class CatalogApi {
  const CatalogApi(this._client);

  final ApiClient _client;

  Future<CatalogIdentifierEnrichment> enrichIdentifiers({
    required String storeId,
    required String externalId,
  }) async {
    final payload = await _client.postJson(
      '/api/v1/catalog/products/identifiers',
      body: {'store_id': storeId, 'external_id': externalId},
    );
    return CatalogIdentifierEnrichment.fromJson(
      payload as Map<String, dynamic>,
    );
  }

  Future<CatalogProduct> getProduct(String productId) async {
    final legacyIdentity = RegExp(r'^[0-9a-f]{32}$').hasMatch(productId);
    final payload = await _client.getJson(
      legacyIdentity
          ? '/api/v1/catalog/products/$productId'
          : '/api/v1/catalog/unified-products/$productId',
    );
    return CatalogProduct.fromJson(payload as Map<String, dynamic>);
  }

  Future<CatalogProductPage> listProducts({
    String query = '',
    List<String>? storeIds,
    int offset = 0,
    int limit = 48,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/unified-products',
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
    String? productId,
    String? sku,
    String? oe,
    String? mpn,
    String? brand,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/competitors',
      queryParameters: {
        'product_id': ?productId,
        'sku': ?sku,
        'oe': ?oe,
        'mpn': ?mpn,
        'brand': ?brand,
      },
    );
    return CatalogCompetitorComparison.fromJson(
      payload as Map<String, dynamic>,
    );
  }

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
    final payload = await _client.postJson(
      '/api/v1/catalog/competitors/discover',
      timeout: const Duration(minutes: 2),
      body: {
        'sku': sku,
        'oe': oe,
        'mpn': mpn,
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
    return (await enrichIdentifiers(
      storeId: storeId,
      externalId: externalId,
    )).oe;
  }
}

class CatalogIdentifierEnrichment {
  const CatalogIdentifierEnrichment({
    required this.oe,
    required this.mpn,
    required this.status,
  });

  factory CatalogIdentifierEnrichment.fromJson(Map<String, dynamic> json) {
    return CatalogIdentifierEnrichment(
      oe: json['oe'] as String?,
      mpn: json['mpn'] as String?,
      status: json['status'] as String? ?? 'UNKNOWN',
    );
  }

  final String? oe;
  final String? mpn;
  final String status;
}

final catalogApiProvider = Provider<CatalogApi>((ref) {
  return CatalogApi(ref.watch(apiClientProvider));
});
