import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'products_api.dart';
import 'products_models.dart';

class ProductsController extends AsyncNotifier<CatalogState> {
  static const _pageSize = 60;
  // Typing should not fire a request per keystroke.
  static const _searchDebounce = Duration(milliseconds: 350);

  Timer? _debounce;
  int _generation = 0;
  int _bulkGeneration = 0;

  ProductsApi get _api => ref.read(productsApiProvider);
  CatalogState get _current =>
      state.value ?? const CatalogState(page: CatalogPage(items: [], total: 0));

  @override
  Future<CatalogState> build() async {
    ref.onDispose(() {
      _debounce?.cancel();
      _generation++;
      _bulkGeneration++;
    });
    final page = await ref.watch(productsApiProvider).search();
    return CatalogState(
      page: page,
      hasImportedProducts: page.total > 0 || page.items.isNotEmpty,
    );
  }

  void search(String query) {
    final trimmed = query.trim();
    state = AsyncData(_current.copyWith(query: query));
    _debounce?.cancel();
    if (trimmed.isEmpty) {
      _reload();
    } else {
      _debounce = Timer(_searchDebounce, _reload);
    }
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

  void filterBySource(ProductSource source) {
    if (_current.source == source) return;
    // Позначки стосувалися інших карток — нова вибірка їх не успадковує.
    state = AsyncData(
      _current.copyWith(
        source: source,
        selectedIds: const {},
        allMatchingSelected: false,
      ),
    );
    _reload();
  }

  void select(StoreProduct? product) {
    state = AsyncData(
      product == null
          ? _current.copyWith(clearSelected: true)
          : _current.copyWith(selected: product),
    );
  }

  void resetFilters() {
    _debounce?.cancel();
    state = AsyncData(
      _current.copyWith(
        query: '',
        price: (null, null),
        source: ProductSource.all,
        selectedIds: const {},
        allMatchingSelected: false,
      ),
    );
    _reload();
  }

  Future<void> refresh() => _reload();

  Future<StoreProduct> updateProduct(
    String productId,
    ProductUpdate update,
  ) async {
    final updated = await _api.updateProduct(productId, update);
    final current = _current;
    state = AsyncData(
      current.copyWith(
        page: CatalogPage(
          items: [
            for (final item in current.page.items)
              if (item.id == updated.id) updated else item,
          ],
          total: current.page.total,
        ),
        selected: updated,
        clearError: true,
      ),
    );
    return updated;
  }

  Future<StoreProduct> refreshProduct(String productId) async {
    final updated = await _api.refreshProduct(productId);
    final current = _current;
    state = AsyncData(
      current.copyWith(
        page: CatalogPage(
          items: [
            for (final item in current.page.items)
              if (item.id == updated.id) updated else item,
          ],
          total: current.page.total,
        ),
        selected: updated,
        clearError: true,
      ),
    );
    return updated;
  }

  void toggleSelection(String productId) {
    final current = _current;
    // Зняття позначки у режимі "вибрано все" повертає до явного вибору
    // завантажених карток — серверні сторінки в нього не потрапляють.
    final ids = current.allMatchingSelected
        ? {for (final item in current.page.items) item.id}
        : Set<String>.of(current.selectedIds);
    if (!ids.remove(productId)) ids.add(productId);
    state = AsyncData(
      current.copyWith(selectedIds: ids, allMatchingSelected: false),
    );
  }

  /// Switches the selection to "everything the current filter matches" —
  /// including pages that were never loaded. Actions then run server-side.
  void selectAllMatching() {
    state = AsyncData(
      _current.copyWith(selectedIds: const {}, allMatchingSelected: true),
    );
  }

  void clearSelection() {
    if (!_current.hasSelection) return;
    state = AsyncData(
      _current.copyWith(selectedIds: const {}, allMatchingSelected: false),
    );
  }

  /// Hides every product the filter matches. One request, whatever the count.
  Future<int> deleteAllMatching() async {
    final current = _current;
    final deleted = await _api.deleteAllMatching(
      query: current.query,
      priceMin: current.priceMin,
      priceMax: current.priceMax,
      source: current.source,
    );
    state = AsyncData(
      current.copyWith(
        selectedIds: const {},
        allMatchingSelected: false,
        clearSelected: true,
        clearError: true,
      ),
    );
    await _reload();
    return deleted;
  }

  /// Queues a catalog-wide re-read and follows the job until it finishes.
  Future<void> refreshAllMatching() async {
    final current = _current;
    final sync = await _api.refreshAllMatching(
      query: current.query,
      priceMin: current.priceMin,
      priceMax: current.priceMax,
      source: current.source,
    );
    state = AsyncData(
      current.copyWith(
        selectedIds: const {},
        allMatchingSelected: false,
        clearError: true,
      ),
    );
    final generation = ++_bulkGeneration;
    while (generation == _bulkGeneration) {
      final job = await _api.getJob(sync.syncRunId);
      if (generation != _bulkGeneration) return;
      state = AsyncData(_current.copyWith(bulkJob: job));
      if (job.isFinished) {
        await _reload();
        state = AsyncData(_current.copyWith(clearBulkJob: true));
        return;
      }
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }

  /// Re-reads every ticked product from its own URL. Returns how many failed.
  Future<int> refreshSelected() async {
    final ids = _current.selectedIds.toList();
    final updated = <String, StoreProduct>{};
    var failed = 0;
    for (final id in ids) {
      try {
        final product = await _api.refreshProduct(id);
        updated[product.id] = product;
      } catch (_) {
        failed++;
      }
    }
    final current = _current;
    state = AsyncData(
      current.copyWith(
        page: CatalogPage(
          items: [
            for (final item in current.page.items) updated[item.id] ?? item,
          ],
          total: current.page.total,
        ),
        selectedIds: const {},
        clearError: true,
      ),
    );
    return failed;
  }

  /// Removes every ticked product from the catalog. Returns how many failed.
  Future<int> deleteSelected() async {
    final ids = _current.selectedIds.toList();
    final removed = <String>{};
    var failed = 0;
    for (final id in ids) {
      try {
        await _api.deleteProduct(id);
        removed.add(id);
      } catch (_) {
        failed++;
      }
    }
    _generation++;
    final current = _current;
    final items = current.page.items
        .where((item) => !removed.contains(item.id))
        .toList(growable: false);
    state = AsyncData(
      current.copyWith(
        page: CatalogPage(
          items: items,
          total: (current.page.total - removed.length).clamp(
            0,
            current.page.total,
          ),
        ),
        selectedIds: const {},
        clearSelected: true,
        clearError: true,
      ),
    );
    return failed;
  }

  Future<void> deleteProduct(String productId) async {
    await _api.deleteProduct(productId);
    _generation++;
    final current = _current;
    final items = current.page.items
        .where((item) => item.id != productId)
        .toList(growable: false);
    state = AsyncData(
      current.copyWith(
        page: CatalogPage(
          items: items,
          total: current.page.total > 0 ? current.page.total - 1 : 0,
        ),
        clearSelected: true,
        clearError: true,
      ),
    );
  }

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
        source: current.source,
        offset: current.page.items.length,
      );
      if (generation != _generation) return;
      // Поки триває імпорт, offset-вікно зсувається — нові рядки лягають перед
      // поточною позицією, і сторінка повертає вже показані товари ще раз.
      final loaded = {for (final item in _current.page.items) item.id};
      state = AsyncData(
        _current.copyWith(
          isLoadingMore: false,
          page: CatalogPage(
            items: [
              ..._current.page.items,
              ...next.items.where((item) => !loaded.contains(item.id)),
            ],
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
        source: current.source,
        limit: _pageSize,
      );
      if (generation != _generation) return;
      final hasImported =
          current.hasImportedProducts || page.total > 0 || page.items.isNotEmpty;
      state = AsyncData(
        _current.copyWith(
          page: page,
          isRefreshing: false,
          hasImportedProducts: hasImported,
        ),
      );
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
    // Імпорт живе на сервері — після перезавантаження сторінки капсула
    // повертається і далі стежить за тим самим запуском.
    try {
      final active = await _api.getActiveJobs();
      if (active.isNotEmpty) {
        final sync = active.first;
        unawaited(_followSync(sync, ++_pollGeneration));
        return CatalogImportState(activeSync: sync);
      }
    } catch (_) {
      // Не змогли спитати про активні імпорти — стартуємо порожніми.
    }
    return const CatalogImportState();
  }

  Future<bool> addStore(String rawUrl) async {
    var url = rawUrl.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://$url';
    }
    final uri = Uri.tryParse(url);
    final host = uri?.host.toLowerCase() ?? '';
    final isValidProm = host == 'prom.ua' ||
        host == 'www.prom.ua' ||
        host.endsWith('.prom.ua');
    if (uri == null || !isValidProm) {
      state = AsyncData(
        _current.copyWith(
          error: 'Введіть коректне посилання магазину на prom.ua',
        ),
      );
      return false;
    }
    return _startSync(() => _api.addStore(url));
  }

  void setError(String error) {
    state = AsyncData(_current.copyWith(error: error));
  }

  Future<bool> importFile(String filename, List<int> bytes) async {
    state = AsyncData(
      _current.copyWith(
        submittingType: ImportSubmittingType.file,
        clearError: true,
        clearImport: true,
      ),
    );
    try {
      final result = await _api.importCatalogFile(filename, bytes);
      state = AsyncData(
        _current.copyWith(
          submittingType: ImportSubmittingType.none,
          lastImport: result,
        ),
      );
      await ref.read(productsControllerProvider.notifier).refresh();
      return true;
    } catch (error) {
      state = AsyncData(
        _current.copyWith(
          submittingType: ImportSubmittingType.none,
          error: error.toString(),
        ),
      );
      return false;
    }
  }

  void dismissImport() {
    state = AsyncData(_current.copyWith(clearImport: true));
  }

  /// Hides the sync capsule and stops following the job.
  void dismissSync() {
    _pollGeneration++;
    state = AsyncData(_current.copyWith(clearSync: true, clearJob: true));
  }

  /// Stops the import on the server, then hides the capsule.
  Future<void> cancelSync() async {
    final sync = _current.activeSync;
    if (sync == null) return;
    _pollGeneration++;
    try {
      await _api.cancelJob(sync.syncRunId);
      state = AsyncData(_current.copyWith(clearSync: true, clearJob: true));
      await ref.read(productsControllerProvider.notifier).refresh();
    } catch (error) {
      // Скасувати не вдалося — капсула лишається і далі стежить за запуском.
      state = AsyncData(_current.copyWith(error: error.toString()));
      unawaited(_followSync(sync, ++_pollGeneration));
    }
  }

  void dismissError() {
    state = AsyncData(_current.copyWith(clearError: true));
  }

  Future<bool> _startSync(Future<StoreSync> Function() request) async {
    state = AsyncData(
      _current.copyWith(
        submittingType: ImportSubmittingType.prom,
        clearError: true,
      ),
    );
    try {
      final sync = await request();
      state = AsyncData(
        _current.copyWith(
          submittingType: ImportSubmittingType.none,
          activeSync: sync,
          clearJob: true,
        ),
      );
      final generation = ++_pollGeneration;
      unawaited(_followSync(sync, generation));
      return true;
    } catch (error) {
      state = AsyncData(
        _current.copyWith(
          submittingType: ImportSubmittingType.none,
          error: error.toString(),
        ),
      );
      return false;
    }
  }

  Future<void> _followSync(StoreSync sync, int generation) async {
    var seen = -1;
    while (generation == _pollGeneration) {
      try {
        final job = await _api.getJob(sync.syncRunId);
        if (generation != _pollGeneration) return;
        // activeSync теж пишемо: перший поll може випередити результат build().
        state = AsyncData(
          _current.copyWith(activeSync: sync, activeJob: job, clearError: true),
        );
        // Товари, що вже приїхали, вливаються в сітку, не чекаючи кінця імпорту.
        if (job.progressCurrent != seen || job.isFinished) {
          seen = job.progressCurrent;
          await ref.read(productsControllerProvider.notifier).refresh();
        }
        if (job.isFinished) {
          // Капсула ще мить показує підсумок, потім зникає сама.
          await Future<void>.delayed(_lingerAfterFinish);
          if (generation == _pollGeneration) dismissSync();
          return;
        }
      } catch (error) {
        state = AsyncData(_current.copyWith(error: error.toString()));
      }
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }

  static const _lingerAfterFinish = Duration(seconds: 4);
}

final catalogImportProvider =
    AsyncNotifierProvider<CatalogImportController, CatalogImportState>(
      CatalogImportController.new,
    );

/// Alias for backwards compatibility if needed
final storesControllerProvider = catalogImportProvider;

/// Ключ стадії для ручного пошуку — товару в каталозі за ним немає.
const manualSearchKey = 'manual';

/// Live OEM/brand lookup; `AsyncData(null)` means "not searched yet".
class CompetitorSearchController extends AsyncNotifier<CompetitorPriceReport?> {
  @override
  Future<CompetitorPriceReport?> build() async => null;

  Future<void> search(String oem, {String? brand}) async {
    final query = oem.trim();
    if (query.isEmpty) return;
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => _readReport(
        ref
            .read(productsApiProvider)
            .competitorSearchEvents(query, brand: brand?.trim()),
        ref.read(competitorStageProvider(manualSearchKey).notifier),
      ),
    );
  }

  void reset() => state = const AsyncData(null);
}

final competitorSearchProvider =
    AsyncNotifierProvider.autoDispose<
      CompetitorSearchController,
      CompetitorPriceReport?
    >(CompetitorSearchController.new);

/// Підпис поточної стадії пошуку конкурентів; null — поки нічого не йде.
class CompetitorStageController extends Notifier<String?> {
  @override
  String? build() => null;

  void show(String? message) => state = message;
}

final competitorStageProvider =
    NotifierProvider.family<CompetitorStageController, String?, String>(
      (productId) => CompetitorStageController(),
    );

class CompetitorPricesController extends AsyncNotifier<CompetitorPriceReport> {
  CompetitorPricesController(this._productId);

  final String _productId;
  ProductsApi get _api => ref.read(productsApiProvider);

  @override
  Future<CompetitorPriceReport> build() => _collect();

  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => _collect(refresh: true));
  }

  Future<CompetitorPriceReport> _collect({bool refresh = false}) => _readReport(
    _api.competitorPriceEvents(_productId, refresh: refresh),
    ref.read(competitorStageProvider(_productId).notifier),
  );
}

/// Веде звіт по подіях SSE, дорогою оновлюючи підпис стадії.
Future<CompetitorPriceReport> _readReport(
  Stream<Map<String, dynamic>> events,
  CompetitorStageController stage,
) async {
  try {
    await for (final event in events) {
      switch (event['stage']) {
        case 'done':
          return CompetitorPriceReport.fromJson(
            event['report'] as Map<String, dynamic>,
          );
        case 'error':
          throw ApiException(
            event['message']?.toString() ?? 'Не вдалося зібрати ціни',
          );
        default:
          stage.show(event['message']?.toString());
      }
    }
  } finally {
    stage.show(null);
  }
  throw const ApiException('Пошук перервано');
}

final competitorPricesProvider = AsyncNotifierProvider.autoDispose
    .family<CompetitorPricesController, CompetitorPriceReport, String>(
      (productId) => CompetitorPricesController(productId),
    );
