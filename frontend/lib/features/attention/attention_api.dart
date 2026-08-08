import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'attention_models.dart';

class AttentionApi {
  const AttentionApi(this._client);

  final ApiClient _client;

  Future<AttentionSummary> summary() async {
    final payload = await _client.getJson('/api/v1/attention/summary');
    return AttentionSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<AttentionPageResult> list({
    String? status,
    String query = '',
    int offset = 0,
    int limit = 50,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/attention/items',
      queryParameters: {
        'status': ?status,
        if (query.trim().isNotEmpty) 'q': query.trim(),
        'offset': '$offset',
        'limit': '$limit',
      },
    );
    return AttentionPageResult.fromJson(payload as Map<String, dynamic>);
  }
}

final attentionApiProvider = Provider<AttentionApi>((ref) {
  return AttentionApi(ref.watch(apiClientProvider));
});
