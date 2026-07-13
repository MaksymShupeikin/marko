import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'store_models.dart';

class StoresApi {
  const StoresApi(this._client);

  final ApiClient _client;

  Future<List<StoreSummary>> listStores() async {
    final payload = await _client.getJson('/api/v1/stores') as List<dynamic>;
    return payload
        .map((item) => StoreSummary.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<StoreSummary> getStore(String id) async {
    final payload = await _client.getJson('/api/v1/stores/$id');
    return StoreSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<StoreSync> addStore(String url) async {
    final payload = await _client.postJson(
      '/api/v1/stores',
      body: {'url': url},
    );
    return StoreSync.fromJson(payload as Map<String, dynamic>);
  }

  Future<StoreSync> syncStore(String id) async {
    final payload = await _client.postJson('/api/v1/stores/$id/sync');
    return StoreSync.fromJson(payload as Map<String, dynamic>);
  }

  Future<SyncRun> getJob(String id) async {
    final payload = await _client.getJson('/api/v1/jobs/$id');
    return SyncRun.fromJson(payload as Map<String, dynamic>);
  }

  Future<ProductPage> listProducts(String storeId, {int offset = 0}) async {
    final payload = await _client.getJson(
      '/api/v1/stores/$storeId/products',
      queryParameters: {'limit': '100', 'offset': '$offset'},
    );
    return ProductPage.fromJson(payload as Map<String, dynamic>);
  }
}

final storesApiProvider = Provider<StoresApi>((ref) {
  return StoresApi(ref.watch(apiClientProvider));
});
