import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'repricing_models.dart';

const xlsxMimeType =
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

class RepricingApi {
  const RepricingApi(this._client);

  final ApiClient _client;

  /// Скільки товарів під фільтром, скільки вже пораховано і чи лишився ліміт.
  Future<RepricePreview> preview({RepriceMode mode = RepriceMode.fresh}) async {
    final payload = await _client.postJson(
      '/api/v1/reprice/preview',
      body: {'mode': mode.value},
    );
    return RepricePreview.fromJson(payload as Map<String, dynamic>);
  }

  /// Що з пораховного вціліло після зміни складу каталогу.
  Future<Reconciliation> reconciliation() async {
    final payload = await _client.getJson('/api/v1/reprice/reconciliation');
    return Reconciliation.fromJson(payload as Map<String, dynamic>);
  }

  /// Зараховує вцілілі товари під новий каталог, щоб не рахувати їх знову.
  Future<void> carryOver() async {
    await _client.postJson('/api/v1/reprice/carry-over');
  }

  Future<RepriceRun> start({
    required RepriceScope scope,
    required RepriceMode mode,
    required RepricePolicy policy,
    int? count,
  }) async {
    final payload = await _client.postJson(
      '/api/v1/reprice/runs',
      body: {
        'scope': scope.value,
        'mode': mode.value,
        'policy': policy.value,
        'count': ?count,
      },
    );
    return RepriceRun.fromJson(payload as Map<String, dynamic>);
  }

  Future<List<RepriceRun>> history({int limit = 20, int offset = 0}) async {
    final payload = await _client.getJson(
      '/api/v1/reprice/runs',
      queryParameters: {'limit': '$limit', 'offset': '$offset'},
    );
    final json = payload as Map<String, dynamic>;
    return [
      for (final run in (json['items'] as List? ?? []))
        RepriceRun.fromJson(run as Map<String, dynamic>),
    ];
  }

  Future<RepriceRun> getRun(String runId) async {
    final payload = await _client.getJson('/api/v1/reprice/runs/$runId');
    return RepriceRun.fromJson(payload as Map<String, dynamic>);
  }

  Future<RepriceItemPage> items(
    String runId, {
    RepriceOutcome? outcome,
    int limit = 60,
    int offset = 0,
  }) async {
    final payload = await _client.getJson(
      '/api/v1/reprice/runs/$runId/items',
      queryParameters: {
        if (outcome != null) 'outcome': outcome.value,
        'limit': '$limit',
        'offset': '$offset',
      },
    );
    return RepriceItemPage.fromJson(payload as Map<String, dynamic>);
  }

  /// Ховає рядок зі звіту або повертає його. Товар у каталозі не чіпається.
  Future<void> dismissItem(
    String runId,
    String listingId, {
    required bool dismissed,
  }) async {
    await _client.postJson(
      '/api/v1/reprice/runs/$runId/items/$listingId/dismiss'
      '?dismissed=$dismissed',
    );
  }

  Future<List<int>> exportBytes(String runId) {
    return _client.getBytes('/api/v1/reprice/runs/$runId/export.xlsx');
  }
}

final repricingApiProvider = Provider<RepricingApi>(
  (ref) => RepricingApi(ref.watch(apiClientProvider)),
);
