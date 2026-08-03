import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';

void main() {
  test(
    'loadMore uses server offset and deduplicates overlapping rows',
    () async {
      final api = _PagingPricingApi();
      final container = ProviderContainer(
        overrides: [pricingApiProvider.overrideWithValue(api)],
      );
      addTearDown(container.dispose);

      await container.read(recommendationsControllerProvider.future);
      await container
          .read(recommendationsControllerProvider.notifier)
          .loadMore();
      final state = container
          .read(recommendationsControllerProvider)
          .requireValue;

      expect(api.offsets, [0, 2]);
      expect(
        api.requestedRunIds,
        [null, 'run-1'],
        reason: 'the first page resolves the run, page two is bound to it',
      );
      expect(state.page.items.map((item) => item.id), [
        'rec-1',
        'rec-2',
        'rec-3',
      ]);
      expect(state.page.hasMore, isFalse);
      expect(state.page.actionCounts.raise, 2);
      expect(state.isLoadingMore, isFalse);
    },
  );

  test('loadMore keeps the loaded page when the next request fails', () async {
    final api = _PagingPricingApi(failNextPage: true);
    final container = ProviderContainer(
      overrides: [pricingApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);

    await container.read(recommendationsControllerProvider.future);
    await container.read(recommendationsControllerProvider.notifier).loadMore();
    final state = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(state.page.items.map((item) => item.id), ['rec-1', 'rec-2']);
    expect(state.page.total, 3);
    expect(state.error, contains('synthetic page failure'));
    expect(state.isLoadingMore, isFalse);
  });

  test('deep link pins a recommendation outside the first page', () async {
    final api = _PagingPricingApi();
    final container = ProviderContainer(
      overrides: [pricingApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);

    await container.read(recommendationsControllerProvider.future);
    await container
        .read(recommendationsControllerProvider.notifier)
        .ensureVisible('rec-deep');
    final state = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(state.page.items.first.id, 'rec-deep');
    expect(state.deepLinkRequestedId, 'rec-deep');
    expect(state.deepLinkUnavailable, isFalse);
    expect(api.requestedRecommendationIds, ['rec-deep']);
  });
}

class _PagingPricingApi extends PricingApi {
  _PagingPricingApi({this.failNextPage = false})
    : super(
        ApiClient(
          client: MockClient((_) async => throw UnimplementedError()),
          baseUrl: 'http://api.test',
        ),
      );

  final bool failNextPage;
  final List<int> offsets = [];
  final List<String?> requestedRunIds = [];
  final List<String> requestedRecommendationIds = [];

  @override
  Future<PricingRecommendation> getRecommendation(
    String recommendationId,
  ) async {
    requestedRecommendationIds.add(recommendationId);
    return _recommendation(recommendationId);
  }

  @override
  Future<RecommendationPage> listRecommendations({
    String queue = 'all',
    String? action,
    String? runId,
    String sort = 'ABSOLUTE_RECOMMENDED_CHANGE',
    int limit = 50,
    int offset = 0,
  }) async {
    offsets.add(offset);
    requestedRunIds.add(runId);
    if (offset == 0) {
      return RecommendationPage(
        items: [_recommendation('rec-1'), _recommendation('rec-2')],
        total: 3,
        runId: 'run-1',
        limit: 2,
        offset: 0,
        actionCounts: const RecommendationActionCounts(raise: 2, review: 1),
      );
    }
    if (failNextPage) throw StateError('synthetic page failure');
    return RecommendationPage(
      items: [_recommendation('rec-2'), _recommendation('rec-3')],
      total: 3,
      runId: 'run-1',
      limit: 2,
      offset: 2,
      actionCounts: const RecommendationActionCounts(raise: 2, review: 1),
    );
  }
}

PricingRecommendation _recommendation(String id) {
  return PricingRecommendation.fromJson({
    'id': id,
    'pricing_run_id': 'run-1',
    'catalog_snapshot_id': 'snapshot-1',
    'catalog_item_id': 'item-$id',
    'sku': 'SKU-$id',
    'oe_norm': 'OE-$id',
    'name': 'Product $id',
    'category': 'brakes',
    'stock_status': 'fresh',
    'action': id == 'rec-3' ? 'MANUAL_REVIEW' : 'RAISE',
    'current_price': '100',
    'recommended_price': '110',
    'confidence': '0.8',
    'confidence_grade': 'A',
    'competitor_count': 3,
    'priority_score': '10',
    'priority_score_type': 'gross_uplift_opportunity',
    'reason_codes': <String>[],
    'currency': 'UAH',
    'price_tick': '1',
    'computed_at': '2026-07-30T00:00:00Z',
  });
}
