import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/environment.dart';
import 'pricing_api.dart';
import 'pricing_models.dart';

class RecommendationsState {
  const RecommendationsState({
    required this.page,
    required this.queue,
    required this.sort,
    this.actionFilter,
    this.isLoadingMore = false,
    this.deepLinkRequestedId,
    this.deepLinkUnavailable = false,
    this.error,
  });

  final RecommendationPage page;
  final String queue;
  final String sort;
  final String? actionFilter;
  final bool isLoadingMore;
  final String? deepLinkRequestedId;
  final bool deepLinkUnavailable;
  final String? error;

  RecommendationsState copyWith({
    RecommendationPage? page,
    String? queue,
    String? sort,
    String? actionFilter,
    bool clearFilter = false,
    bool? isLoadingMore,
    String? deepLinkRequestedId,
    bool? deepLinkUnavailable,
    String? error,
    bool clearError = false,
  }) {
    return RecommendationsState(
      page: page ?? this.page,
      queue: queue ?? this.queue,
      sort: sort ?? this.sort,
      actionFilter: clearFilter ? null : actionFilter ?? this.actionFilter,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      deepLinkRequestedId: deepLinkRequestedId ?? this.deepLinkRequestedId,
      deepLinkUnavailable: deepLinkUnavailable ?? this.deepLinkUnavailable,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class RecommendationsController extends AsyncNotifier<RecommendationsState> {
  int _requestGeneration = 0;

  PricingApi get _api => ref.read(pricingApiProvider);

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
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        current.copyWith(page: page, isLoadingMore: false, clearError: true),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(current.copyWith(error: error.toString()));
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
      );
    } catch (_) {
      final latest = state.value;
      if (latest != null && latest.deepLinkRequestedId == recommendationId) {
        state = AsyncData(latest.copyWith(deepLinkUnavailable: true));
      }
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
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(
          page: page,
          queue: current.queue,
          sort: current.sort,
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
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(page: page, queue: queue, sort: current.sort),
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
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        RecommendationsState(
          page: page,
          queue: current.queue,
          sort: sort,
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
        limit: current.page.limit,
        offset: current.page.offset + current.page.items.length,
      );
      if (generation != _requestGeneration) return;
      final byId = {
        for (final item in current.page.items) item.id: item,
        for (final item in next.items) item.id: item,
      };
      state = AsyncData(
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
          clearError: true,
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(
        current.copyWith(isLoadingMore: false, error: error.toString()),
      );
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
      state = AsyncData(current.copyWith(clearError: true));
      return true;
    } catch (error) {
      state = AsyncData(current.copyWith(error: error.toString()));
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
      state = AsyncData(current.copyWith(clearError: true));
      return true;
    } catch (error) {
      state = AsyncData(current.copyWith(error: error.toString()));
      return false;
    }
  }
}

final recommendationsControllerProvider =
    AsyncNotifierProvider<RecommendationsController, RecommendationsState>(
      RecommendationsController.new,
    );
