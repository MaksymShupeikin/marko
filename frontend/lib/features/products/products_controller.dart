import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'products_api.dart';
import 'products_models.dart';

class ProductsController extends AsyncNotifier<CatalogState> {
  static const _pageSize = 60;
  // Typing should not fire a request per keystroke.
  static const _searchDebounce = Duration(milliseconds: 350);

  Timer? _debounce;
  int _generation = 0;

  ProductsApi get _api => ref.read(productsApiProvider);
  CatalogState get _current =>
      state.value ?? const CatalogState(page: CatalogPage(items: [], total: 0));

  @override
  Future<CatalogState> build() async {
    ref.onDispose(() {
      _debounce?.cancel();
      _generation++;
    });
    return CatalogState(page: await ref.watch(productsApiProvider).search());
  }

  void search(String query) {
    state = AsyncData(_current.copyWith(query: query));
    _debounce?.cancel();
    _debounce = Timer(_searchDebounce, _reload);
  }

  void sortBy(ProductSort sort) {
    state = AsyncData(_current.copyWith(sort: sort));
    _reload();
  }

  /// Typed into, so it debounces like the search box.
  void filterByPrice(double? min, double? max) {
    state = AsyncData(_current.copyWith(price: (min, max)));
    _debounce?.cancel();
    _debounce = Timer(_searchDebounce, _reload);
  }

  void select(StoreProduct? product) {
    state = AsyncData(
      product == null
          ? _current.copyWith(clearSelected: true)
          : _current.copyWith(selected: product),
    );
  }

  Future<void> refresh() => _reload();

  Future<void> loadMore() async {
    final current = _current;
    if (current.isLoadingMore || !current.page.hasMore) return;
    state = AsyncData(current.copyWith(isLoadingMore: true, clearError: true));
    final generation = _generation;
    try {
      final next = await _api.search(
        query: current.query,
        sort: current.sort,
        priceMin: current.priceMin,
        priceMax: current.priceMax,
        offset: current.page.items.length,
      );
      if (generation != _generation) return;
      state = AsyncData(
        _current.copyWith(
          isLoadingMore: false,
          page: CatalogPage(
            items: [..._current.page.items, ...next.items],
            total: next.total,
          ),
        ),
      );
    } catch (error) {
      state = AsyncData(
        _current.copyWith(isLoadingMore: false, error: error.toString()),
      );
    }
  }

  void dismissError() {
    state = AsyncData(_current.copyWith(clearError: true));
  }

  Future<void> _reload() async {
    final current = _current;
    final generation = ++_generation;
    state = AsyncData(current.copyWith(isRefreshing: true, clearError: true));
    try {
      final page = await _api.search(
        query: current.query,
        sort: current.sort,
        priceMin: current.priceMin,
        priceMax: current.priceMax,
        limit: _pageSize,
      );
      if (generation != _generation) return;
      state = AsyncData(_current.copyWith(page: page, isRefreshing: false));
    } catch (error) {
      if (generation != _generation) return;
      state = AsyncData(
        _current.copyWith(isRefreshing: false, error: error.toString()),
      );
    }
  }
}

final productsControllerProvider =
    AsyncNotifierProvider<ProductsController, CatalogState>(
      ProductsController.new,
    );

class CatalogImportController extends AsyncNotifier<CatalogImportState> {
  int _pollGeneration = 0;

  ProductsApi get _api => ref.read(productsApiProvider);
  CatalogImportState get _current => state.value ?? const CatalogImportState();

  @override
  Future<CatalogImportState> build() async {
    ref.onDispose(() => _pollGeneration++);
    return const CatalogImportState();
  }

  Future<bool> addStore(String rawUrl) async {
    final url = rawUrl.trim();
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.host != 'prom.ua' && uri.host != 'www.prom.ua')) {
      state = AsyncData(
        _current.copyWith(
          error: 'Введіть коректне посилання магазину на prom.ua',
        ),
      );
      return false;
    }
    return _startSync(() => _api.addStore(url));
  }

  Future<bool> importFile(String filename, List<int> bytes) async {
    state = AsyncData(
      _current.copyWith(
        isSubmitting: true,
        clearError: true,
        clearImport: true,
      ),
    );
    try {
      final result = await _api.importCatalogFile(filename, bytes);
      state = AsyncData(
        _current.copyWith(isSubmitting: false, lastImport: result),
      );
      await ref.read(productsControllerProvider.notifier).refresh();
      return true;
    } catch (error) {
      state = AsyncData(
        _current.copyWith(isSubmitting: false, error: error.toString()),
      );
      return false;
    }
  }

  void dismissImport() {
    state = AsyncData(_current.copyWith(clearImport: true));
  }

  void dismissError() {
    state = AsyncData(_current.copyWith(clearError: true));
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
    while (generation == _pollGeneration) {
      try {
        final job = await _api.getJob(sync.syncRunId);
        if (generation != _pollGeneration) return;
        state = AsyncData(_current.copyWith(activeJob: job, clearError: true));
        if (job.isFinished) {
          await ref.read(productsControllerProvider.notifier).refresh();
          return;
        }
      } catch (error) {
        state = AsyncData(_current.copyWith(error: error.toString()));
      }
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }
}

final catalogImportProvider =
    AsyncNotifierProvider<CatalogImportController, CatalogImportState>(
      CatalogImportController.new,
    );

/// Alias for backwards compatibility if needed
final storesControllerProvider = catalogImportProvider;

/// Live avto.pro lookup; `AsyncData(null)` means "not searched yet".
class CompetitorSearchController extends AsyncNotifier<CompetitorSearch?> {
  @override
  Future<CompetitorSearch?> build() async => null;

  Future<void> search(String oem, {String? brand}) async {
    final query = oem.trim();
    if (query.isEmpty) return;
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref
          .read(productsApiProvider)
          .searchCompetitors(query, brand: brand?.trim()),
    );
  }

  void reset() => state = const AsyncData(null);
}

final competitorSearchProvider =
    AsyncNotifierProvider.autoDispose<
      CompetitorSearchController,
      CompetitorSearch?
    >(CompetitorSearchController.new);
