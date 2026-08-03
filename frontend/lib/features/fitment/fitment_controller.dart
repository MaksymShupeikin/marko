import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session_expiry.dart';
import 'fitment_api.dart';
import 'fitment_models.dart';

class FitmentReviewState {
  const FitmentReviewState({
    required this.bundle,
    this.isSubmitting = false,
    this.message,
    this.error,
  });

  final FitmentReviewBundle bundle;
  final bool isSubmitting;
  final String? message;
  final String? error;

  FitmentReviewState copyWith({
    FitmentReviewBundle? bundle,
    bool? isSubmitting,
    String? message,
    String? error,
    bool clearMessage = false,
    bool clearError = false,
  }) {
    return FitmentReviewState(
      bundle: bundle ?? this.bundle,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      message: clearMessage ? null : message ?? this.message,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class FitmentController extends AsyncNotifier<FitmentReviewState> {
  FitmentController(this.catalogItemId);

  final String catalogItemId;

  FitmentApi get _api => ref.read(fitmentApiProvider);
  FitmentReviewState? get _current => state.value;

  @override
  Future<FitmentReviewState> build() async {
    try {
      final state = FitmentReviewState(bundle: await _loadBundle());
      ref.observeLiveSession();
      return state;
    } catch (error) {
      // Мёртвый токен — состояние приложения, а не свойство fitment. Пока эта
      // ветка отдавала исключение как есть, панель печатала «Fitment
      // intelligence недоступен: Authentication required» — техническую
      // неправду про подсистему вместо единственного действия, которое
      // что-то меняет.
      ref.classifySessionExpiry(error);
      rethrow;
    }
  }

  Future<FitmentReviewBundle> _loadBundle() async {
    final values = await Future.wait<Object?>([
      _api.listCandidates(catalogItemId),
      _api.getRecommendation(catalogItemId),
    ]);
    return FitmentReviewBundle(
      page: values[0] as FitmentCandidatePage,
      recommendation: values[1] as FitmentMarketRecommendation?,
    );
  }

  Future<void> reload() async {
    final current = _current;
    if (current == null) {
      state = const AsyncLoading();
      state = await AsyncValue.guard(build);
      return;
    }
    try {
      final bundle = await _loadBundle();
      ref.observeLiveSession();
      state = AsyncData(
        current.copyWith(bundle: bundle, clearError: true, clearMessage: true),
      );
    } catch (error, stackTrace) {
      // Строки уже на экране остаются: они были правдой, когда пришли.
      if (ref.classifySessionExpiry(error)) {
        state = AsyncData(
          current.copyWith(
            isSubmitting: false,
            clearError: true,
            clearMessage: true,
          ),
        );
        return;
      }
      state = AsyncError(error, stackTrace);
    }
  }

  Future<bool> generateRecommendation() async {
    final analysisId = _current?.bundle.page.analysisId;
    if (analysisId == null) return false;
    return _runAction(
      () => _api.generateRecommendation(catalogItemId, analysisId: analysisId),
      successMessage: 'Рекомендация рассчитана без автопубликации.',
    );
  }

  Future<bool> reviewCandidate(
    FitmentCandidate candidate, {
    required String decision,
    required String reasonCode,
    String? comment,
    Map<String, String> evidenceVerdicts = const {},
  }) {
    return _runAction(
      () => _api.reviewCandidate(
        candidate.id,
        decision: decision,
        reasonCode: reasonCode,
        comment: comment,
        evidenceVerdicts: evidenceVerdicts,
      ),
      successMessage: 'Fitment-решение сохранено в audit trail.',
    );
  }

  Future<bool> reviewRecommendation(
    FitmentMarketRecommendation recommendation, {
    required String operation,
    required String reasonCode,
    double? approvedPrice,
    String? comment,
    bool allowBelowFloor = false,
    bool belowFloorWarningConfirmed = false,
  }) {
    return _runAction(
      () => _api.reviewRecommendation(
        recommendation.id,
        operation: operation,
        reasonCode: reasonCode,
        approvedPrice: approvedPrice,
        comment: comment,
        allowBelowFloor: allowBelowFloor,
        belowFloorWarningConfirmed: belowFloorWarningConfirmed,
      ),
      successMessage: 'Решение сохранено. Цена на Prom.ua не изменялась.',
    );
  }

  Future<bool> markSeller(
    FitmentCandidate candidate, {
    required String relation,
    required String reason,
  }) {
    return _runAction(
      () => _api.markSellerRelation(
        candidate,
        relation: relation,
        reason: reason,
      ),
      successMessage: 'Связь продавца сохранена.',
    );
  }

  void clearNotice() {
    final current = _current;
    if (current != null) {
      state = AsyncData(current.copyWith(clearMessage: true, clearError: true));
    }
  }

  Future<bool> _runAction(
    Future<Object?> Function() action, {
    required String successMessage,
  }) async {
    final current = _current;
    if (current == null || current.isSubmitting) return false;
    state = AsyncData(
      current.copyWith(
        isSubmitting: true,
        clearError: true,
        clearMessage: true,
      ),
    );
    try {
      await action();
      final bundle = await _loadBundle();
      ref.observeLiveSession();
      state = AsyncData(
        FitmentReviewState(bundle: bundle, message: successMessage),
      );
      return true;
    } catch (error) {
      if (ref.classifySessionExpiry(error)) {
        state = AsyncData(
          current.copyWith(
            isSubmitting: false,
            clearError: true,
            clearMessage: true,
          ),
        );
        return false;
      }
      state = AsyncData(
        current.copyWith(
          isSubmitting: false,
          error: error.toString(),
          clearMessage: true,
        ),
      );
      return false;
    }
  }
}

final fitmentControllerProvider = AsyncNotifierProvider.autoDispose
    .family<FitmentController, FitmentReviewState, String>(
      FitmentController.new,
    );
