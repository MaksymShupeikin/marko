import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'pricing_api.dart';
import 'pricing_models.dart';

class RecommendationsState {
  const RecommendationsState({
    required this.page,
    required this.queue,
    this.actionFilter,
    this.error,
  });

  final RecommendationPage page;
  final String queue;
  final String? actionFilter;
  final String? error;

  RecommendationsState copyWith({
    RecommendationPage? page,
    String? queue,
    String? actionFilter,
    bool clearFilter = false,
    String? error,
    bool clearError = false,
  }) {
    return RecommendationsState(
      page: page ?? this.page,
      queue: queue ?? this.queue,
      actionFilter: clearFilter ? null : actionFilter ?? this.actionFilter,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class RecommendationsController extends AsyncNotifier<RecommendationsState> {
  PricingApi get _api => ref.read(pricingApiProvider);

  @override
  Future<RecommendationsState> build() async {
    return RecommendationsState(
      page: await ref
          .watch(pricingApiProvider)
          .listRecommendations(queue: 'raise'),
      queue: 'raise',
    );
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
          ),
          queue: current.queue,
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
            sort: queue == 'review' ? 'review_priority' : 'priority',
          ),
          queue: queue,
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
