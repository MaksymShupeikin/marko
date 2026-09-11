import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'repricing_api.dart';
import 'repricing_models.dart';

/// Everything the repricing window shows at once.
class RepricingState {
  const RepricingState({
    this.preview,
    this.reconciliation,
    this.run,
    this.items = RepriceItemPage.empty,
    this.history = const [],
    this.scope = RepriceScope.partial,
    this.mode = RepriceMode.fresh,
    this.policy = RepricePolicy.balanced,
    this.count = 1,
    this.filter,
    this.showHistory = false,
    this.busy = false,
    this.error,
  });

  final RepricePreview? preview;

  /// Що вціліло з пораховного після зміни складу каталогу.
  final Reconciliation? reconciliation;

  /// Прогін, який зараз відкритий: свіжий, поточний або вибраний з історії.
  final RepriceRun? run;
  final RepriceItemPage items;
  final List<RepriceRun> history;

  final RepriceScope scope;
  final RepriceMode mode;
  final RepricePolicy policy;

  /// Значення повзунка. Для повного каталогу не використовується.
  final int count;

  /// Показувати лише один результат: `null` — усі.
  final RepriceOutcome? filter;
  final bool showHistory;
  final bool busy;
  final String? error;

  /// Верхня межа повзунка: скільки товарів доступно в обраному режимі.
  int get maxCount {
    final available = mode == RepriceMode.resume
        ? preview?.remaining ?? 0
        : preview?.matching ?? 0;
    return available < 1 ? 1 : available;
  }

  bool get canStart {
    if (busy) return false;
    if (run?.isRunning ?? false) return false;
    return maxCount > 0 && (preview?.matching ?? 0) > 0;
  }

  /// Скільки перевірок може списати прогін у найгіршому випадку.
  int get plannedCount => scope == RepriceScope.full ? maxCount : count;

  /// Ліміту не вистачить — краще сказати до запуску, ніж впасти на середині.
  bool get exceedsChecks {
    final left = preview?.checksLeft;
    return left != null && plannedCount > left;
  }

  RepricingState copyWith({
    RepricePreview? preview,
    Reconciliation? reconciliation,
    RepriceRun? run,
    RepriceItemPage? items,
    List<RepriceRun>? history,
    RepriceScope? scope,
    RepriceMode? mode,
    RepricePolicy? policy,
    int? count,
    RepriceOutcome? filter,
    bool clearFilter = false,
    bool? showHistory,
    bool? busy,
    String? error,
    bool clearError = false,
  }) {
    return RepricingState(
      preview: preview ?? this.preview,
      reconciliation: reconciliation ?? this.reconciliation,
      run: run ?? this.run,
      items: items ?? this.items,
      history: history ?? this.history,
      scope: scope ?? this.scope,
      mode: mode ?? this.mode,
      policy: policy ?? this.policy,
      count: count ?? this.count,
      filter: clearFilter ? null : (filter ?? this.filter),
      showHistory: showHistory ?? this.showHistory,
      busy: busy ?? this.busy,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class RepricingController extends AsyncNotifier<RepricingState> {
  // Прогін по каталогу довгий: частіший опит нічого не додає, крім запитів.
  static const _pollInterval = Duration(seconds: 2);

  int _generation = 0;

  RepricingApi get _api => ref.read(repricingApiProvider);
  RepricingState get _current => state.value ?? const RepricingState();

  @override
  Future<RepricingState> build() async {
    ref.onDispose(() => _generation++);
    final api = ref.watch(repricingApiProvider);
    final preview = await api.preview();
    final history = await api.history(limit: 20);
    final reconciliation = await api.reconciliation();
    final latest = history.isEmpty ? null : history.first;
    // Завершений прогін одразу показує свої рядки: інакше людина заходить
    // у вікно й бачить порожньо, хоча результат уже є.
    final items = latest != null && latest.isFinished
        ? await api.items(latest.id)
        : RepriceItemPage.empty;
    if (latest != null && latest.isRunning) {
      unawaited(_follow(latest.id));
    }
    return RepricingState(
      preview: preview,
      reconciliation: reconciliation,
      history: history,
      run: latest,
      items: items,
      count: preview.matching < 1 ? 1 : preview.matching,
    );
  }

  void chooseScope(RepriceScope scope) {
    state = AsyncData(_current.copyWith(scope: scope, clearError: true));
  }

  Future<void> chooseMode(RepriceMode mode) async {
    final next = _current.copyWith(mode: mode, clearError: true);
    state = AsyncData(next);
    // Межа повзунка інша для «продовжити» — перерахунок робить сервер.
    await refreshPreview();
  }

  void choosePolicy(RepricePolicy policy) {
    state = AsyncData(_current.copyWith(policy: policy));
  }

  void chooseCount(int count) {
    final bounded = count < 1 ? 1 : count;
    state = AsyncData(_current.copyWith(count: bounded));
  }

  void filterBy(RepriceOutcome? outcome) {
    state = AsyncData(
      outcome == null
          ? _current.copyWith(clearFilter: true)
          : _current.copyWith(filter: outcome),
    );
    final run = _current.run;
    if (run != null) unawaited(_loadItems(run.id));
  }

  void toggleHistory() {
    state = AsyncData(_current.copyWith(showHistory: !_current.showHistory));
  }

  Future<void> refreshPreview() async {
    try {
      final preview = await _api.preview(mode: _current.mode);
      final bounded = _current.count > preview.remaining
          ? (preview.remaining < 1 ? 1 : preview.remaining)
          : _current.count;
      state = AsyncData(
        _current.copyWith(preview: preview, count: bounded, clearError: true),
      );
    } catch (error) {
      state = AsyncData(_current.copyWith(error: '$error'));
    }
  }

  /// Зараховує вцілілі товари під новий каталог замість рахувати їх знову.
  Future<void> carryOver() async {
    state = AsyncData(_current.copyWith(busy: true, clearError: true));
    try {
      await _api.carryOver();
      state = AsyncData(
        _current.copyWith(
          busy: false,
          reconciliation: await _api.reconciliation(),
        ),
      );
      await refreshPreview();
      await _loadHistory();
    } catch (error) {
      state = AsyncData(_current.copyWith(busy: false, error: '$error'));
    }
  }

  Future<void> start() async {
    final current = _current;
    if (!current.canStart) return;
    state = AsyncData(current.copyWith(busy: true, clearError: true));
    try {
      final run = await _api.start(
        scope: current.scope,
        mode: current.mode,
        policy: current.policy,
        count: current.scope == RepriceScope.partial ? current.count : null,
      );
      state = AsyncData(
        _current.copyWith(
          run: run,
          items: RepriceItemPage.empty,
          busy: false,
          showHistory: false,
          clearFilter: true,
        ),
      );
      unawaited(_follow(run.id));
    } catch (error) {
      state = AsyncData(_current.copyWith(busy: false, error: '$error'));
    }
  }

  Future<void> openRun(String runId) async {
    state = AsyncData(_current.copyWith(busy: true, showHistory: false));
    try {
      final run = await _api.getRun(runId);
      state = AsyncData(
        _current.copyWith(run: run, busy: false, clearFilter: true),
      );
      await _loadItems(runId);
      if (run.isRunning) unawaited(_follow(runId));
    } catch (error) {
      state = AsyncData(_current.copyWith(busy: false, error: '$error'));
    }
  }

  /// Ховає рядок зі звіту. Товар у каталозі лишається на місці.
  Future<void> dismiss(String listingId, {required bool dismissed}) async {
    final run = _current.run;
    if (run == null) return;
    try {
      await _api.dismissItem(run.id, listingId, dismissed: dismissed);
      await _loadItems(run.id);
    } catch (error) {
      state = AsyncData(_current.copyWith(error: '$error'));
    }
  }

  /// Байти вивантаження будь-якого прогону — не лише відкритого зараз.
  Future<List<int>> exportBytes(String runId) => _api.exportBytes(runId);

  /// Опитуємо прогін, поки він не завершиться, і тоді показуємо рядки.
  Future<void> _follow(String runId) async {
    final generation = _generation;
    while (generation == _generation) {
      await Future<void>.delayed(_pollInterval);
      if (generation != _generation) return;
      RepriceRun run;
      try {
        run = await _api.getRun(runId);
      } catch (_) {
        return;
      }
      if (generation != _generation) return;
      state = AsyncData(_current.copyWith(run: run));
      if (run.isFinished) {
        await _loadItems(runId);
        await refreshPreview();
        await _loadHistory();
        return;
      }
    }
  }

  Future<void> _loadItems(String runId) async {
    try {
      final page = await _api.items(runId, outcome: _current.filter);
      state = AsyncData(_current.copyWith(items: page));
    } catch (error) {
      state = AsyncData(_current.copyWith(error: '$error'));
    }
  }

  Future<void> _loadHistory() async {
    try {
      state = AsyncData(_current.copyWith(history: await _api.history()));
    } catch (_) {
      // Історія — не критична частина екрана: мовчки лишаємо попередню.
    }
  }
}

final repricingControllerProvider =
    AsyncNotifierProvider<RepricingController, RepricingState>(
      RepricingController.new,
    );
