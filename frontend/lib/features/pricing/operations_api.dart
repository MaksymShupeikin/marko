import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'discovery_funnel_models.dart';

class OperationsApi {
  const OperationsApi(this._client);

  final ApiClient _client;

  Future<DiscoveryFunnelSnapshot> getDiscoveryFunnel({
    int runLimit = 400,
    int categoryLimit = 50,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/operations/discovery-funnel',
      queryParameters: {
        'run_limit': '$runLimit',
        'category_limit': '$categoryLimit',
      },
    );
    return DiscoveryFunnelSnapshot.fromJson(payload as Map<String, dynamic>);
  }
}

final operationsApiProvider = Provider<OperationsApi>((ref) {
  return OperationsApi(ref.watch(apiClientProvider));
});
