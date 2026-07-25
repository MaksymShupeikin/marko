import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'catalog_api.dart';
import 'catalog_models.dart';

class CatalogState {
  const CatalogState({
    required this.page,
    this.query = '',
    this.selectedStoreId,
    this.isSearching = false,
    this.isLoadingMore = false,
    this.error,
  });

  final CatalogProductPage page;
  final String query;
  final String? selectedStoreId;
  final bool isSearching;
  final bool isLoadingMore;
  final String? error;

  CatalogState copyWith({
    CatalogProductPage? page,
    String? query,
    String? selectedStoreId,
    bool clearSelectedStore = false,
    bool? isSearching,
    bool? isLoadingMore,
    String? error,
    bool clearError = false,
  }) {
    return CatalogState(
      page: page ?? this.page,
      query: query ?? this.query,
      selectedStoreId: clearSelectedStore
          ? null
          : selectedStoreId ?? this.selectedStoreId,
      isSearching: isSearching ?? this.isSearching,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class CatalogController extends AsyncNotifier<CatalogState> {
  int _requestGeneration = 0;

  CatalogApi get _api => ref.read(catalogApiProvider);
  CatalogState get _current => state.requireValue;

  @override
  Future<CatalogState> build() async {
    ref.onDispose(() => _requestGeneration++);
    final page = await ref.watch(catalogApiProvider).listProducts();
    return CatalogState(page: page);
  }

  Future<void> search(String rawQuery) async {
    final query = rawQuery.trim();
    await _reload(query: query, storeId: _current.selectedStoreId);
  }

  Future<void> selectStore(String? storeId) async {
    await _reload(query: _current.query, storeId: storeId);
  }

  Future<CatalogCompetitorComparison> loadCompetitors(CatalogProduct product) {
    return _api.listCompetitors(
      sku: product.sku,
      oe: product.oe,
      brand: product.brand,
    );
  }

  Future<void> _reload({
    required String query,
    required String? storeId,
  }) async {
    final generation = ++_requestGeneration;
    state = AsyncData(
      _current.copyWith(
        query: query,
        selectedStoreId: storeId,
        clearSelectedStore: storeId == null,
        isSearching: true,
        clearError: true,
      ),
    );
    try {
      final page = await _api.listProducts(query: query, storeId: storeId);
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _current.copyWith(
          page: page,
          query: query,
          selectedStoreId: storeId,
          clearSelectedStore: storeId == null,
          isSearching: false,
          isLoadingMore: false,
          clearError: true,
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _current.copyWith(isSearching: false, error: error.toString()),
      );
    }
  }

  Future<void> refresh() =>
      _reload(query: _current.query, storeId: _current.selectedStoreId);

  Future<void> loadMore() async {
    final current = _current;
    if (current.isLoadingMore || current.isSearching || !current.page.hasMore) {
      return;
    }
    final generation = _requestGeneration;
    state = AsyncData(current.copyWith(isLoadingMore: true, clearError: true));
    try {
      final next = await _api.listProducts(
        query: current.query,
        storeId: current.selectedStoreId,
        offset: current.page.items.length,
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _current.copyWith(
          page: CatalogProductPage(
            items: [...current.page.items, ...next.items],
            total: next.total,
            catalogTotal: next.catalogTotal,
            listingTotal: next.listingTotal,
            duplicatesRemoved: next.duplicatesRemoved,
            storeTotal: next.storeTotal,
            stores: next.stores,
          ),
          isLoadingMore: false,
          clearError: true,
        ),
      );
    } catch (error) {
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _current.copyWith(isLoadingMore: false, error: error.toString()),
      );
    }
  }
}

final catalogControllerProvider =
    AsyncNotifierProvider.autoDispose<CatalogController, CatalogState>(
      CatalogController.new,
    );
