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

  /// [runId] binds the request to one pricing run. Omitting it lets the
  /// backend fall back to the newest run, which silently changes the answer
  /// whenever a run finishes mid-session.
  Future<RecommendationPage> listRecommendations({
    String queue = 'all',
    String? action,
    String? runId,
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
        'run_id': ?runId,
      },
    );
    return RecommendationPage.fromJson(payload as Map<String, dynamic>);
  }

  /// Заморозить область прогона и показать её цену до запуска.
  ///
  /// Без побочных эффектов: прогон не создаётся. Возвращённые хеши передаются
  /// в [startRun], чтобы запуск отказался стартовать, если каталог успел
  /// измениться между предпросмотром и подтверждением.
  Future<PricingRunPreview> previewRun(
    String importBatchId, {
    String scopeMode = 'FULL_CATALOG',
    List<String> catalogItemIds = const <String>[],
  }) async {
    final payload = await _client.postJson(
      '/api/v1/pricing/runs/preview',
      body: {
        'import_batch_id': importBatchId,
        'scope_mode': scopeMode,
        if (catalogItemIds.isNotEmpty) 'catalog_item_ids': catalogItemIds,
      },
      // Предпросмотр обходит каждую позицию области: замораживает снимок,
      // считает пригодность, оценивает запросы и потолок платных вызовов.
      // На общем 15-секундном лимите он успевал ответить 200, но клиент уже
      // сдавался — владелец видел TimeoutException на запуске, который сервер
      // выполнил.
      timeout: const Duration(minutes: 2),
    );
    return PricingRunPreview.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> startRun(
    String importBatchId, {
    String scopeMode = 'FULL_CATALOG',
    List<String> catalogItemIds = const <String>[],
    bool confirmFullCatalog = false,
    String? idempotencyKey,
    // Непрозрачный токен из ответа предпросмотра. Хеши клиент больше не шлёт:
    // сервер сам их публиковал, и «подтверждение» состояло из значения,
    // которое подтверждающий получил от подтверждаемого.
    required String previewToken,
  }) async {
    final payload = await _client.postJson(
      Environment.e2eMode ? '/api/v1/e2e/pricing/runs' : '/api/v1/pricing/runs',
      body: {
        'import_batch_id': importBatchId,
        'scope_mode': scopeMode,
        if (catalogItemIds.isNotEmpty) 'catalog_item_ids': catalogItemIds,
        // Полный каталог — самый дорогой режим, сервер требует явного согласия.
        if (scopeMode == 'FULL_CATALOG')
          'confirm_full_catalog': confirmFullCatalog,
        'idempotency_key': ?idempotencyKey,
        'preview_token': previewToken,
      },
    );
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<PricingRunSummary> getRun(String id) async {
    final payload = await _client.getJson('/api/v1/pricing/runs/$id');
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<ComparabilityRunReport> getComparabilityReport(String runId) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/runs/$runId/comparability-report',
    );
    return ComparabilityRunReport.fromJson(payload as Map<String, dynamic>);
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

  Future<PricingDiscoveryReviewQueue> getDiscoveryReviews(String runId) async {
    final payload = await _client.getJson(
      '/api/v1/pricing/runs/$runId/discovery-reviews',
    );
    return PricingDiscoveryReviewQueue.fromJson(
      payload as Map<String, dynamic>,
    );
  }

  Future<void> decideDiscoveryOffer({
    required String runId,
    required PricingDiscoveryReviewOffer offer,
    required String decision,
    required String reason,
  }) async {
    await _client.postJson(
      '/api/v1/pricing/runs/$runId/discovery-offers/${offer.offerId}/decision',
      body: {
        'decision': decision,
        'reason': reason,
        'expected_offer_sha256': offer.offerSha256,
        'idempotency_key':
            'ui:$runId:${offer.offerId}:$decision:${DateTime.now().microsecondsSinceEpoch}',
      },
    );
  }

  Future<PricingRunSummary> resumeRun(
    String runId,
    String reviewSnapshotHash,
  ) async {
    final payload = await _client.postJson(
      '/api/v1/pricing/runs/$runId/resume',
      body: {'review_snapshot_hash': reviewSnapshotHash},
    );
    return PricingRunSummary.fromJson(payload as Map<String, dynamic>);
  }

  Future<BinaryDownload> exportRecommendations({
    required String format,
    required String queue,
    required String sort,
    String? action,
    String? runId,
  }) {
    return _client.getBytes(
      '/api/v1/pricing/recommendations/export',
      queryParameters: {
        'format': format,
        'queue': queue,
        'sort': sort,
        'action': ?action,
        'run_id': ?runId,
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
