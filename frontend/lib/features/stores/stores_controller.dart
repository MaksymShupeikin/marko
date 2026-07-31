import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'store_models.dart';
import 'stores_api.dart';

bool isSupportedPromStoreUrl(String rawUrl) {
  final uri = Uri.tryParse(rawUrl.trim());
  if (uri == null || uri.scheme.toLowerCase() != 'https' || uri.host.isEmpty) {
    return false;
  }
  final host = uri.host.toLowerCase();
  return host == 'prom.ua' ||
      host == 'www.prom.ua' ||
      host.endsWith('.prom.ua');
}

class StoresController extends AsyncNotifier<StoresState> {
  StoresController({
    this.pollBaseDelay = const Duration(seconds: 2),
    this.maxConsecutivePollFailures = 5,
  });

  final Duration pollBaseDelay;
  final int maxConsecutivePollFailures;
  int _pollGeneration = 0;

  StoresApi get _api => ref.read(storesApiProvider);
  StoresState get _current => state.value ?? const StoresState();

  @override
  Future<StoresState> build() async {
    ref.onDispose(() => _pollGeneration++);
    return StoresState(stores: await ref.watch(storesApiProvider).listStores());
  }

  Future<void> refresh() async {
    try {
      state = AsyncData(
        _current.copyWith(stores: await _api.listStores(), clearError: true),
      );
    } catch (error) {
      state = AsyncData(_current.copyWith(error: error.toString()));
    }
  }

  Future<bool> addStore(String rawUrl) async {
    final url = rawUrl.trim();
    if (!isSupportedPromStoreUrl(url)) {
      state = AsyncData(
        _current.copyWith(error: 'Введите HTTPS-ссылку магазина на prom.ua'),
      );
      return false;
    }
    return _startSync(() => _api.addStore(url));
  }

  Future<void> syncStore(StoreSummary store) async {
    if (!_current.hasActiveJob) {
      await _startSync(() => _api.syncStore(store.id));
    }
  }

  Future<bool> deleteStore(StoreSummary store) async {
    if (_current.isDeleting) return false;
    state = AsyncData(
      _current.copyWith(deletingStoreId: store.id, clearError: true),
    );
    try {
      await _api.deleteStore(store.id);
      final deletingActiveSync = _current.activeSync?.storeId == store.id;
      if (deletingActiveSync) _pollGeneration++;
      state = AsyncData(
        _current.copyWith(
          stores: _current.stores
              .where((item) => item.id != store.id)
              .toList(growable: false),
          clearDeletingStore: true,
          clearSync: deletingActiveSync,
          clearError: true,
        ),
      );
      return true;
    } catch (error) {
      state = AsyncData(
        _current.copyWith(clearDeletingStore: true, error: error.toString()),
      );
      return false;
    }
  }

  void dismissError() {
    state = AsyncData(_current.copyWith(clearError: true));
  }

  void retryMonitoring() {
    final sync = _current.activeSync;
    if (sync == null) return;
    state = AsyncData(_current.copyWith(clearJob: true, clearError: true));
    final generation = ++_pollGeneration;
    unawaited(_followSync(sync, generation));
  }

  Future<bool> _startSync(Future<StoreSync> Function() request) async {
    state = AsyncData(_current.copyWith(isSubmitting: true, clearError: true));
    try {
      final sync = await request();
      state = AsyncData(
        _current.copyWith(
          isSubmitting: false,
          activeSync: sync,
          clearJob: true,
        ),
      );
      final generation = ++_pollGeneration;
      unawaited(_followSync(sync, generation));
      return true;
    } catch (error) {
      state = AsyncData(
        _current.copyWith(isSubmitting: false, error: error.toString()),
      );
      return false;
    }
  }

  Future<void> _followSync(StoreSync sync, int generation) async {
    var consecutiveFailures = 0;
    while (generation == _pollGeneration) {
      var delay = pollBaseDelay;
      try {
        final job = await _api.getJob(sync.syncRunId);
        if (generation != _pollGeneration) return;
        consecutiveFailures = 0;
        state = AsyncData(_current.copyWith(activeJob: job, clearError: true));
        if (job.isFinished) {
          await refresh();
          return;
        }
      } catch (error) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= maxConsecutivePollFailures) {
          const message =
              'Не удалось получить статус синхронизации после нескольких попыток. '
              'Проверьте соединение и повторите отслеживание.';
          state = AsyncData(
            _current.copyWith(
              activeJob: const SyncRun(
                status: 'monitoring_failed',
                progressCurrent: 0,
                progressTotal: null,
                error: message,
              ),
              error: message,
            ),
          );
          return;
        }
        state = AsyncData(_current.copyWith(error: error.toString()));
        delay = _pollFailureDelay(consecutiveFailures);
      }
      await Future<void>.delayed(delay);
    }
  }

  Duration _pollFailureDelay(int consecutiveFailures) {
    if (pollBaseDelay == Duration.zero) return Duration.zero;
    final exponent = consecutiveFailures <= 1
        ? 0
        : consecutiveFailures >= 5
        ? 4
        : consecutiveFailures - 1;
    final milliseconds = pollBaseDelay.inMilliseconds * (1 << exponent);
    final bounded = milliseconds < 1
        ? 1
        : milliseconds > 30000
        ? 30000
        : milliseconds;
    return Duration(milliseconds: bounded);
  }
}

final storesControllerProvider =
    AsyncNotifierProvider<StoresController, StoresState>(StoresController.new);

class StoreProductsController extends AsyncNotifier<StoreProductsState> {
  StoreProductsController(
    this.storeId, {
    this.searchDebounce = const Duration(milliseconds: 350),
  });

  final String storeId;
  final Duration searchDebounce;

  String _query = '';
  Timer? _debounce;
  int _searchGeneration = 0;

  StoresApi get _api => ref.read(storesApiProvider);
  StoreProductsState? get _current => state.value;

  @override
  Future<StoreProductsState> build() async {
    ref.onDispose(() {
      _debounce?.cancel();
      _searchGeneration++;
    });
    final api = ref.watch(storesApiProvider);
    final storeFuture = api.getStore(storeId);
    final productsFuture = api.listProducts(storeId, query: _query);
    return StoreProductsState(
      store: await storeFuture,
      page: await productsFuture,
      query: _query,
    );
  }

  Future<void> reload() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(build);
  }

  /// Types into the search box: debounced so a long article is one request.
  void search(String value) {
    _debounce?.cancel();
    if (value.trim() == _query.trim()) return;
    _query = value;
    if (searchDebounce == Duration.zero) {
      unawaited(_runSearch());
      return;
    }
    _debounce = Timer(searchDebounce, () => unawaited(_runSearch()));
  }

  /// Applies a query carried by the route, e.g. after following a cross-store
  /// suggestion, without waiting for the typing debounce.
  Future<void> applyQuery(String value) {
    _debounce?.cancel();
    if (value.trim() == _query.trim()) return Future<void>.value();
    _query = value;
    return _runSearch();
  }

  Future<void> _runSearch() async {
    final current = _current;
    if (current == null) return;
    final generation = ++_searchGeneration;
    final query = _query;
    state = AsyncData(
      current.copyWith(
        query: query,
        isSearching: true,
        isSearchingElsewhere: false,
        clearElsewhere: true,
        clearError: true,
      ),
    );
    try {
      final page = await _api.listProducts(storeId, query: query);
      if (generation != _searchGeneration) return;
      final searched = (_current ?? current).copyWith(
        page: page,
        isSearching: false,
      );
      state = AsyncData(searched);
      if (page.items.isEmpty && query.trim().isNotEmpty) {
        await _searchOtherStores(generation, query);
      }
    } catch (error) {
      if (generation != _searchGeneration) return;
      state = AsyncData(
        (_current ?? current).copyWith(
          isSearching: false,
          error: error.toString(),
        ),
      );
    }
  }

  Future<void> _searchOtherStores(int generation, String query) async {
    final current = _current;
    if (current == null) return;
    state = AsyncData(current.copyWith(isSearchingElsewhere: true));
    try {
      final result = await _api.searchOtherStores(storeId, query);
      if (generation != _searchGeneration) return;
      state = AsyncData(
        (_current ?? current).copyWith(
          isSearchingElsewhere: false,
          elsewhere: result,
        ),
      );
    } catch (error) {
      if (generation != _searchGeneration) return;
      state = AsyncData(
        (_current ?? current).copyWith(
          isSearchingElsewhere: false,
          error: error.toString(),
        ),
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
      final next = await _api.listProducts(
        storeId,
        offset: current.page.items.length,
        query: current.query,
      );
      state = AsyncData(
        current.copyWith(
          isLoadingMore: false,
          page: ProductPage(
            items: [...current.page.items, ...next.items],
            total: next.total,
            limit: next.limit,
            offset: current.page.offset,
          ),
        ),
      );
    } catch (error) {
      state = AsyncData(
        current.copyWith(isLoadingMore: false, error: error.toString()),
      );
    }
  }
}

final storeProductsProvider = AsyncNotifierProvider.autoDispose
    .family<StoreProductsController, StoreProductsState, String>(
      StoreProductsController.new,
    );
