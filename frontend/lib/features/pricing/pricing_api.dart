import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/environment.dart';
import 'pricing_models.dart';

class PricingApi {
  const PricingApi(this._client);

  final ApiClient _client;

  Future<PricingRecommendation> getRecommendation(
    String recommendationId,
  ) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/recommendations/$recommendationId',
    );
    return PricingRecommendation.fromJson(payload as Map<String, dynamic>);
  }

  Future<RecommendationPage> listRecommendations({
    String queue = 'all',
    String? action,
    String sort = 'ABSOLUTE_RECOMMENDED_CHANGE',
    int limit = 50,
    int offset = 0,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/recommendations',
      queryParameters: {
        'limit': '$limit',
        'offset': '$offset',
        'sort': sort,
        'queue': queue,
        'action': ?action,
      },
    );
    return RecommendationPage.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> startRun(String importBatchId) async {
    final payload = await _client.postJson(
      Environment.e2eMode ? '/api/v1/e2e/pricing/runs' : '/api/v1/pricing/runs',
      body: {'import_batch_id': importBatchId},
    );
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> getRun(String id) async {
    final payload = await _client.getJson('/api/v1/pricing/runs/$id');
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<List<PricingRunSummary>> listRuns({int limit = 25}) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/runs',
      queryParameters: {'limit': '$limit', 'offset': '0'},
    );
    return ((payload as Map<String, dynamic>)['items'] as List<dynamic>)
        .map((item) => PricingRunSummary.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<PricingRunSummary> cancelRun(String id) async {
    final payload = await _client.postJson('/api/v1/pricing/runs/$id/cancel');
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<BinaryDownload> exportRecommendations({
    required String format,
    required String queue,
    required String sort,
    String? action,
  }) {
    return _client.getBytes(
      '/api/v1/pricing/recommendations/export',
      queryParameters: {
        'format': format,
        'queue': queue,
        'sort': sort,
        'action': ?action,
      },
      fallbackFilename: 'marko-recommendations.$format',
    );
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

  Future<ComparabilityReview> reviewComparability(
    String observationId, {
    bool force = false,
  }) async {
    final payload = await _client.postJson(
      '/api/v1/pricing/observations/$observationId/comparability-reviews',
      body: {'force': force},
    );
    return ComparabilityReview.fromJson(payload as Map<String, dynamic>);
  }

  Future<ComparabilityReview> recordComparabilityFeedback(
    String reviewId,
    Map<String, dynamic> values,
  ) async {
    final payload = await _client.postJson(
      '/api/v1/pricing/comparability-reviews/$reviewId/feedback',
      body: values,
    );
    return ComparabilityReview.fromJson(payload as Map<String, dynamic>);
  }
}

final pricingApiProvider = Provider<PricingApi>((ref) {
  return PricingApi(ref.watch(apiClientProvider));
});
