import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/environment.dart';
import '../../core/session_expiry.dart';
import 'pricing_api.dart';
import 'pricing_models.dart';

class RecommendationsState {
  const RecommendationsState({
    required this.page,
    required this.queue,
    required this.sort,
    this.runId,
    this.actionFilter,
    this.isLoadingMore = false,
    this.deepLinkRequestedId,
    this.deepLinkUnavailable = false,
    this.newerRunAvailable = false,
    this.sessionExpired = false,
    this.error,
  });

  final RecommendationPage page;
  final String queue;
  final String sort;

  /// The pricing run this whole view is bound to. Every request the controller
  /// makes carries it, so rows, totals, counters and the export always describe
  /// the same calculation.
  final String? runId;
  final String? actionFilter;
  final bool isLoadingMore;
  final String? deepLinkRequestedId;
  final bool deepLinkUnavailable;

  /// A response arrived from a run other than [runId]: a newer calculation
  /// exists and the operator has to opt into it.
  final bool newerRunAvailable;

  /// The session died on a request made after the page was already on screen.
  /// It is not an error string: nothing the operator can read fixes it, and
  /// only a fresh sign-in does.
  final bool sessionExpired;
  final String? error;

  RecommendationsState copyWith({
    RecommendationPage? page,
    String? queue,
    String? sort,
    String? runId,
    String? actionFilter,
    bool clearFilter = false,
    bool? isLoadingMore,
    String? deepLinkRequestedId,
    bool? deepLinkUnavailable,
    bool? newerRunAvailable,
    bool? sessionExpired,
    String? error,
    bool clearError = false,
  }) {
    return RecommendationsState(
      page: page ?? this.page,
      queue: queue ?? this.queue,
      sort: sort ?? this.sort,
      runId: runId ?? this.runId,
      actionFilter: clearFilter ? null : actionFilter ?? this.actionFilter,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      deepLinkRequestedId: deepLinkRequestedId ?? this.deepLinkRequestedId,
      deepLinkUnavailable: deepLinkUnavailable ?? this.deepLinkUnavailable,
      newerRunAvailable: newerRunAvailable ?? this.newerRunAvailable,
      sessionExpired: sessionExpired ?? this.sessionExpired,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class RecommendationsController extends AsyncNotifier<RecommendationsState> {
  int _requestGeneration = 0;

  PricingApi get _api => ref.read(pricingApiProvider);

  /// Single funnel for every failure that lands while a page is already on
  /// screen.
  ///
  /// `build`, `setQueue`, `setSort` and `setActionFilter` hand their error to
  /// Riverpod, where [MarkoAsyncErrorView] applies the same classification.
  /// Refresh, pagination, the deep link and both writes keep their rows
  /// instead, so without this funnel a dead session degraded into an
  /// untranslated string next to a retry that could only fail again — on
  /// exactly the paths an operator hits most.
  ///
  /// The classification itself belongs to [MarkoSessionExpiry], so a 401 that
  /// arrives here also silences the run panel and the export button: it is one
  /// condition, not one per widget.
  RecommendationsState _failed(RecommendationsState current, Object error) {
    if (ref.classifySessionExpiry(error)) {
      return current.copyWith(
        isLoadingMore: false,
        sessionExpired: true,
        clearError: true,
      );
    }
    return current.copyWith(isLoadingMore: false, error: error.toString());
  }

  /// Ответ пришёл по живому токену.
  RecommendationsState _succeeded(RecommendationsState next) {
    ref.observeLiveSession();
    return next;
  }

  @override
  Future<RecommendationsState> build() async {
    ref.onDispose(() => _requestGeneration++);
    final initialQueue = Environment.e2eMode ? 'review' : 'all';
    const initialSort = 'ABSOLUTE_RECOMMENDED_CHANGE';
    final initialPage = await _loadInitialPage(
      ref.watch(pricingApiProvider),
      initialQueue,
      initialSort,
    );
    return RecommendationsState(
      page: initialPage,
      queue: initialQueue,
      sort: initialSort,
      runId: initialPage.runId,
    );
  }

  Future<RecommendationPage> _loadInitialPage(
    PricingApi api,
    String queue,
    String sort,
  ) async {
    final attempts = Environment.e2eMode ? 120 : 1;
    for (var attempt = 0; attempt < attempts; attempt += 1) {
      final page = await api.listRecommendations(queue: queue, sort: sort);
      if (!Environment.e2eMode || page.items.isNotEmpty) return page;
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    return api.listRecommendations(queue: queue, sort: sort);
  }

  Future<void> refresh() async {
    final current = state.value;
    if (current == null) return;
    final generation = ++_requestGeneration;
    try {
      final page = await _api.listRecommendations(
        queue: current.queue,
        action: current.actionFilter,
        sort: current.sort,
        runId: current.runId,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _succeeded(
          current.copyWith(
            page: page,
            isLoadingMore: false,
            sessionExpired: false,
            clearError: true,
          ),
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(_failed(current, error));
    }
  }

  /// Rebinds the screen to the newest run. Everything else stays on
  /// [RecommendationsState.runId], so moving between calculations is always an
  /// explicit act that replaces the view instead of mutating it underneath.
  Future<void> showLatestRun() async {
    final current = state.value;
    if (current == null) return;
    final generation = ++_requestGeneration;
    try {
      final page = await _api.listRecommendations(
        queue: current.queue,
        action: current.actionFilter,
        sort: current.sort,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _succeeded(
          RecommendationsState(
            page: page,
            queue: current.queue,
            sort: current.sort,
            runId: page.runId,
            actionFilter: current.actionFilter,
          ),
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(_failed(current, error));
    }
  }

  Future<void> ensureVisible(String recommendationId) async {
    final current = state.value;
    if (current == null || current.deepLinkRequestedId == recommendationId) {
      return;
    }
    final existing = current.page.items
        .where((item) => item.id == recommendationId)
        .firstOrNull;
    if (existing != null) {
      state = AsyncData(
        current.copyWith(
          deepLinkRequestedId: recommendationId,
          deepLinkUnavailable: false,
        ),
      );
      return;
    }
    state = AsyncData(
      current.copyWith(
        deepLinkRequestedId: recommendationId,
        deepLinkUnavailable: false,
      ),
    );
    try {
      final recommendation = await _api.getRecommendation(recommendationId);
      final latest = state.value;
      if (latest == null || latest.deepLinkRequestedId != recommendationId) {
        return;
      }
      state = AsyncData(
        _succeeded(
          latest.copyWith(
            page: RecommendationPage(
              items: [
                recommendation,
                ...latest.page.items.where(
                  (item) => item.id != recommendation.id,
                ),
              ],
              total: latest.page.total,
              runId: latest.page.runId,
              limit: latest.page.limit,
              offset: latest.page.offset,
              actionCounts: latest.page.actionCounts,
            ),
            deepLinkUnavailable: false,
            clearError: true,
          ),
        ),
      );
    } catch (error) {
      final latest = state.value;
      if (latest == null || latest.deepLinkRequestedId != recommendationId) {
        return;
      }
      // A dead session is not a missing recommendation. Swallowing the error
      // here told the operator their permanent link pointed at something that
      // "no longer exists or is not in this workspace" — a statement about
      // their data that was never true, and one that hides the only action
      // that would have opened the row.
      if (ref.classifySessionExpiry(error)) {
        state = AsyncData(latest.copyWith(sessionExpired: true));
        return;
      }
      state = AsyncData(latest.copyWith(deepLinkUnavailable: true));
    }
  }

  Future<void> setActionFilter(String? action) async {
    final current = state.value;
    if (current == null || current.actionFilter == action) return;
    final generation = ++_requestGeneration;
    state = const AsyncLoading();
    try {
      final page = await _api.listRecommendations(
        queue: current.queue,
        action: action,
        sort: current.sort,
        runId: current.runId,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(
          page: page,
          queue: current.queue,
          sort: current.sort,
          runId: current.runId,
          actionFilter: action,
        ),
      );
    } catch (error, stackTrace) {
      if (generation != _requestGeneration) return;
      state = AsyncError(error, stackTrace);
    }
  }

  Future<void> setQueue(String queue) async {
    final current = state.value;
    if (current == null || current.queue == queue) return;
    final generation = ++_requestGeneration;
    state = const AsyncLoading();
    try {
      final page = await _api.listRecommendations(
        queue: queue,
        sort: current.sort,
        runId: current.runId,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(
          page: page,
          queue: queue,
          sort: current.sort,
          runId: current.runId,
        ),
      );
    } catch (error, stackTrace) {
      if (generation != _requestGeneration) return;
      state = AsyncError(error, stackTrace);
    }
  }

  Future<void> setSort(String sort) async {
    final current = state.value;
    if (current == null || current.sort == sort) return;
    final generation = ++_requestGeneration;
    state = const AsyncLoading();
    try {
      final page = await _api.listRecommendations(
        queue: current.queue,
        action: current.actionFilter,
        sort: sort,
        runId: current.runId,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(
          page: page,
          queue: current.queue,
          sort: sort,
          runId: current.runId,
          actionFilter: current.actionFilter,
        ),
      );
    } catch (error, stackTrace) {
      if (generation != _requestGeneration) return;
      state = AsyncError(error, stackTrace);
    }
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || current.isLoadingMore || !current.page.hasMore) {
      return;
    }
    final generation = _requestGeneration;
    state = AsyncData(current.copyWith(isLoadingMore: true, clearError: true));
    try {
      final next = await _api.listRecommendations(
        queue: current.queue,
        action: current.actionFilter,
        sort: current.sort,
        runId: current.runId,
        limit: current.page.limit,
        offset: current.page.offset + current.page.items.length,
      );
      if (generation != _requestGeneration) return;
      if (current.runId != null &&
          next.runId != null &&
          next.runId != current.runId) {
        // Splicing two runs into one list would put prices, totals and
        // counters from different calculations under one heading.
        state = AsyncData(
          current.copyWith(isLoadingMore: false, newerRunAvailable: true),
        );
        return;
      }
      final byId = {
        for (final item in current.page.items) item.id: item,
        for (final item in next.items) item.id: item,
      };
      state = AsyncData(
        _succeeded(
          current.copyWith(
            page: RecommendationPage(
              items: byId.values.toList(growable: false),
              total: next.total,
              runId: next.runId,
              limit: next.limit,
              offset: current.page.offset,
              actionCounts: next.actionCounts,
            ),
            isLoadingMore: false,
            sessionExpired: false,
            clearError: true,
          ),
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(_failed(current, error));
    }
  }

  Future<bool> saveCatalogContext(
    String catalogItemId,
    Map<String, dynamic> values,
  ) async {
    final current = state.value;
    if (current == null) return false;
    try {
      await _api.saveCatalogContext(catalogItemId, values);
      state = AsyncData(
        _succeeded(current.copyWith(sessionExpired: false, clearError: true)),
      );
      return true;
    } catch (error) {
      state = AsyncData(_failed(current, error));
      return false;
    }
  }

  Future<bool> recordDecision(
    String recommendationId,
    Map<String, dynamic> values,
  ) async {
    final current = state.value;
    if (current == null) return false;
    try {
      await _api.recordDecision(recommendationId, values);
      state = AsyncData(
        _succeeded(current.copyWith(sessionExpired: false, clearError: true)),
      );
      return true;
    } catch (error) {
      state = AsyncData(_failed(current, error));
      return false;
    }
  }
}

final recommendationsControllerProvider =
    AsyncNotifierProvider<RecommendationsController, RecommendationsState>(
      RecommendationsController.new,
    );
