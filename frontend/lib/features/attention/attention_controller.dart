import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'attention_api.dart';
import 'attention_models.dart';

class AttentionState {
  const AttentionState({
    required this.summary,
    required this.page,
    this.status,
    this.query = '',
    this.isRefreshing = false,
    this.isLoadingMore = false,
    this.error,
  });

  final AttentionSummary summary;
  final AttentionPageResult page;
  final String? status;
  final String query;
  final bool isRefreshing;
  final bool isLoadingMore;
  final String? error;

  AttentionState copyWith({
    AttentionSummary? summary,
    AttentionPageResult? page,
    String? status,
    bool clearStatus = false,
    String? query,
    bool? isRefreshing,
    bool? isLoadingMore,
    String? error,
    bool clearError = false,
  }) {
    return AttentionState(
      summary: summary ?? this.summary,
      page: page ?? this.page,
      status: clearStatus ? null : status ?? this.status,
      query: query ?? this.query,
      isRefreshing: isRefreshing ?? this.isRefreshing,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class AttentionController extends AsyncNotifier<AttentionState> {
  Timer? _refreshTimer;
  int _generation = 0;

  AttentionApi get _api => ref.read(attentionApiProvider);

  @override
  Future<AttentionState> build() async {
    ref.onDispose(() {
      _generation++;
      _refreshTimer?.cancel();
    });
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 15),
      (_) => unawaited(refresh(silent: true)),
    );
    final results = await Future.wait<Object>([_api.summary(), _api.list()]);
    return AttentionState(
      summary: results[0] as AttentionSummary,
      page: results[1] as AttentionPageResult,
    );
  }

  Future<void> selectStatus(String? status) async {
    final current = state.value;
    if (current == null || current.status == status) return;
    await _reload(status: status, query: current.query);
  }

  Future<void> search(String query) async {
    final current = state.value;
    if (current == null) return;
    await _reload(status: current.status, query: query.trim());
  }

  Future<void> refresh({bool silent = false}) async {
    final current = state.value;
    if (current == null || current.isRefreshing) return;
    final generation = ++_generation;
    if (!silent) {
      state = AsyncData(current.copyWith(isRefreshing: true, clearError: true));
    }
    try {
      final results = await Future.wait<Object>([
        _api.summary(),
        _api.list(status: current.status, query: current.query),
      ]);
      if (generation != _generation) return;
      state = AsyncData(
        current.copyWith(
          summary: results[0] as AttentionSummary,
          page: results[1] as AttentionPageResult,
          isRefreshing: false,
          clearError: true,
        ),
      );
    } catch (error) {
      if (generation != _generation || silent) return;
      state = AsyncData(
        current.copyWith(isRefreshing: false, error: error.toString()),
      );
    }
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || current.isLoadingMore || !current.page.hasMore) {
      return;
    }
    state = AsyncData(current.copyWith(isLoadingMore: true, clearError: true));
    try {
      final next = await _api.list(
        status: current.status,
        query: current.query,
        offset: current.page.items.length,
      );
      final latest = state.requireValue;
      state = AsyncData(
        latest.copyWith(
          page: AttentionPageResult(
            items: [...current.page.items, ...next.items],
            total: next.total,
            limit: next.limit,
            offset: 0,
          ),
          isLoadingMore: false,
          clearError: true,
        ),
      );
    } catch (error) {
      state = AsyncData(
        state.requireValue.copyWith(
          isLoadingMore: false,
          error: error.toString(),
        ),
      );
    }
  }

  Future<void> _reload({required String? status, required String query}) async {
    final current = state.requireValue;
    final generation = ++_generation;
    state = AsyncData(
      current.copyWith(
        status: status,
        clearStatus: status == null,
        query: query,
        isRefreshing: true,
        clearError: true,
      ),
    );
    try {
      final page = await _api.list(status: status, query: query);
      if (generation != _generation) return;
      state = AsyncData(
        state.requireValue.copyWith(
          page: page,
          isRefreshing: false,
          clearError: true,
        ),
      );
    } catch (error) {
      if (generation != _generation) return;
      state = AsyncData(
        state.requireValue.copyWith(
          isRefreshing: false,
          error: error.toString(),
        ),
      );
    }
  }
}

final attentionControllerProvider =
    AsyncNotifierProvider.autoDispose<AttentionController, AttentionState>(
      AttentionController.new,
    );
