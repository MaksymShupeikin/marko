import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_models.dart';

class CatalogApi {
  const CatalogApi(this._client);

  final ApiClient _client;

  Future<CatalogProductPage> listProducts({
    String query = '',
    int offset = 0,
    int limit = 48,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/products',
      queryParameters: {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        'limit': '$limit',
        'offset': '$offset',
      },
    );
    return CatalogProductPage.fromJson(payload as Map<String, dynamic>);
  }
}

final catalogApiProvider = Provider<CatalogApi>((ref) {
  return CatalogApi(ref.watch(apiClientProvider));
});
