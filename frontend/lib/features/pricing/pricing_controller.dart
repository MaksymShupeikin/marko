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
    this.error,
  });

  final RecommendationPage page;
  final String queue;
  final String sort;
  final String? actionFilter;
  final String? error;

  RecommendationsState copyWith({
    RecommendationPage? page,
    String? queue,
    String? sort,
    String? actionFilter,
    bool clearFilter = false,
    String? error,
    bool clearError = false,
  }) {
    return RecommendationsState(
      page: page ?? this.page,
      queue: queue ?? this.queue,
      sort: sort ?? this.sort,
      actionFilter: clearFilter ? null : actionFilter ?? this.actionFilter,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class RecommendationsController extends AsyncNotifier<RecommendationsState> {
  PricingApi get _api => ref.read(pricingApiProvider);

  @override
  Future<RecommendationsState> build() async {
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
    try {
      state = AsyncData(
        current.copyWith(
          page: await _api.listRecommendations(
            queue: current.queue,
            action: current.actionFilter,
            sort: current.sort,
          ),
          clearError: true,
        ),
      );
    } catch (error) {
      state = AsyncData(current.copyWith(error: error.toString()));
    }
  }

  Future<void> setActionFilter(String? action) async {
    final current = state.value;
    if (current == null || current.actionFilter == action) return;
    state = const AsyncLoading();
    try {
      state = AsyncData(
        RecommendationsState(
          page: await _api.listRecommendations(
            queue: current.queue,
            action: action,
            sort: current.sort,
          ),
          queue: current.queue,
          sort: current.sort,
          actionFilter: action,
        ),
      );
    } catch (error, stackTrace) {
      state = AsyncError(error, stackTrace);
    }
  }

  Future<void> setQueue(String queue) async {
    final current = state.value;
    if (current == null || current.queue == queue) return;
    state = const AsyncLoading();
    try {
      state = AsyncData(
        RecommendationsState(
          page: await _api.listRecommendations(
            queue: queue,
            sort: current.sort,
          ),
          queue: queue,
          sort: current.sort,
        ),
      );
    } catch (error, stackTrace) {
      state = AsyncError(error, stackTrace);
    }
  }

  Future<void> setSort(String sort) async {
    final current = state.value;
    if (current == null || current.sort == sort) return;
    state = const AsyncLoading();
    try {
      state = AsyncData(
        RecommendationsState(
          page: await _api.listRecommendations(
            queue: current.queue,
            action: current.actionFilter,
            sort: sort,
          ),
          queue: current.queue,
          sort: sort,
          actionFilter: current.actionFilter,
        ),
      );
    } catch (error, stackTrace) {
      state = AsyncError(error, stackTrace);
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
