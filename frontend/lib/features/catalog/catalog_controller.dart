import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'catalog_api.dart';
import 'catalog_models.dart';

class CatalogState {
  const CatalogState({
    required this.page,
    this.query = '',
    this.selectedStoreIds = const {},
    this.isSearching = false,
    this.isLoadingMore = false,
    this.error,
  });

  final CatalogProductPage page;
  final String query;
  final Set<String> selectedStoreIds;
  final bool isSearching;
  final bool isLoadingMore;
  final String? error;

  CatalogState copyWith({
    CatalogProductPage? page,
    String? query,
    Set<String>? selectedStoreIds,
    bool? isSearching,
    bool? isLoadingMore,
    String? error,
    bool clearError = false,
  }) {
    return CatalogState(
      page: page ?? this.page,
      query: query ?? this.query,
      selectedStoreIds: selectedStoreIds ?? this.selectedStoreIds,
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
    await _reload(query: query, storeIds: _current.selectedStoreIds);
  }

  Future<void> selectStores(Set<String> storeIds) async {
    await _reload(query: _current.query, storeIds: storeIds);
  }

  Future<CatalogCompetitorComparison> loadCompetitors(CatalogProduct product) {
    return _api.listCompetitors(
      sku: product.sku,
      oe: product.oe,
      brand: product.brand,
    );
  }

  Future<CatalogCompetitorComparison> discoverCompetitors(
    CatalogProduct product,
  ) {
    return _api.discoverCompetitors(
      sku: product.sku,
      oe: product.oe,
      brand: product.brand,
      title: product.name,
      currentPrice: product.primaryStore?.price ?? product.priceMin,
      currency: product.primaryStore?.currency ?? product.currency,
    );
  }

  Future<String?> enrichOe(CatalogProduct product) {
    final store = product.primaryStore;
    if (store == null) return Future.value(null);
    return _api.enrichOe(storeId: store.storeId, externalId: store.externalId);
  }

  Future<void> _reload({
    required String query,
    required Set<String> storeIds,
  }) async {
    final generation = ++_requestGeneration;
    state = AsyncData(
      _current.copyWith(
        query: query,
        selectedStoreIds: storeIds,
        isSearching: true,
        clearError: true,
      ),
    );
    try {
      final page = await _api.listProducts(
        query: query,
        storeIds: storeIds.toList(growable: false),
      );
      if (generation != _requestGeneration) return;
      state = AsyncData(
        _current.copyWith(
          page: page,
          query: query,
          selectedStoreIds: storeIds,
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
      _reload(query: _current.query, storeIds: _current.selectedStoreIds);

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
        storeIds: current.selectedStoreIds.toList(growable: false),
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
