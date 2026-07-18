import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'pricing_models.dart';

class PricingApi {
  const PricingApi(this._client);

  final ApiClient _client;

  Future<RecommendationPage> listRecommendations({
    String queue = 'raise',
    String? action,
    String sort = 'priority',
  }) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/recommendations',
      queryParameters: {
        'limit': '250',
        'sort': sort,
        'queue': queue,
        'action': ?action,
      },
    );
    return RecommendationPage.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> startRun(String importBatchId) async {
    final payload = await _client.postJson(
      '/api/v1/pricing/runs',
      body: {'import_batch_id': importBatchId},
    );
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> getRun(String id) async {
    final payload = await _client.getJson('/api/v1/pricing/runs/$id');
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<List<RecommendationEvidence>> getEvidence(
    String recommendationId,
  ) async {
    final payload =
        await _client.getJson(
              '/api/v1/pricing/recommendations/$recommendationId/evidence',
            )
            as List<dynamic>;
    return payload
        .map(
          (item) =>
              RecommendationEvidence.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }

  Future<RecommendationReplay> verifyReplay(String recommendationId) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/recommendations/$recommendationId/replay',
    );
    return RecommendationReplay.fromJson(payload as Map<String, dynamic>);
  }

  Future<void> saveCatalogContext(
    String catalogItemId,
    Map<String, dynamic> values,
  ) async {
    await _client.postJson(
      '/api/v1/pricing/catalog-items/$catalogItemId/overrides',
      body: values,
    );
  }

  Future<void> recordDecision(
    String recommendationId,
    Map<String, dynamic> values,
  ) async {
    await _client.postJson(
      '/api/v1/pricing/recommendations/$recommendationId/decisions',
      body: values,
    );
  }

  Future<void> overrideTier(
    String observationId, {
    required String tier,
    required String reason,
  }) async {
    await _client.postJson(
      '/api/v1/pricing/observations/$observationId/tier-overrides',
      body: {'tier': tier, 'reason': reason},
    );
  }
}

final pricingApiProvider = Provider<PricingApi>((ref) {
  return PricingApi(ref.watch(apiClientProvider));
});
