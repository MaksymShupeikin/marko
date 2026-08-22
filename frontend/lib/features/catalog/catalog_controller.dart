import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_api.dart';
import 'catalog_models.dart';

class CatalogState {
  const CatalogState({
    required this.page,
    this.query = '',
    this.selectedStoreIds = const {},
    this.kempStatus,
    this.noOem = false,
    this.isSearching = false,
    this.isLoadingMore = false,
    this.deepLinkUnavailable = false,
    this.error,
  });

  final CatalogProductPage page;
  final String query;
  final Set<String> selectedStoreIds;
  final String? kempStatus;
  final bool noOem;
  final bool isSearching;
  final bool isLoadingMore;
  final bool deepLinkUnavailable;
  final String? error;

  CatalogState copyWith({
    CatalogProductPage? page,
    String? query,
    Set<String>? selectedStoreIds,
    String? kempStatus,
    bool? noOem,
    bool clearKempStatus = false,
    bool? isSearching,
    bool? isLoadingMore,
    bool? deepLinkUnavailable,
    String? error,
    bool clearError = false,
  }) {
    return CatalogState(
      page: page ?? this.page,
      query: query ?? this.query,
      selectedStoreIds: selectedStoreIds ?? this.selectedStoreIds,
      kempStatus: clearKempStatus ? null : kempStatus ?? this.kempStatus,
      noOem: noOem ?? this.noOem,
      isSearching: isSearching ?? this.isSearching,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      deepLinkUnavailable: deepLinkUnavailable ?? this.deepLinkUnavailable,
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
    await _reload(
      query: query,
      storeIds: _current.selectedStoreIds,
      kempStatus: _current.kempStatus,
      noOem: _current.noOem,
    );
  }

  Future<void> selectStores(Set<String> storeIds) async {
    await _reload(
      query: _current.query,
      storeIds: storeIds,
      kempStatus: _current.kempStatus,
      noOem: _current.noOem,
    );
  }

  Future<void> selectIdentityFilter({String? kempStatus, bool noOem = false}) {
    return _reload(
      query: _current.query,
      storeIds: _current.selectedStoreIds,
      kempStatus: kempStatus,
      noOem: noOem,
    );
  }

  Future<CatalogCompetitorComparison> loadCompetitors(CatalogProduct product) {
    return _api.listCompetitors(
      productId: product.id,
      sku: product.sku,
      oe: product.oe,
      mpn: product.mpn,
      brand: product.brand,
    );
  }

  Future<CatalogProduct?> ensureVisible(String productId) async {
    final current = state.value;
    if (current == null) return null;
    for (final product in current.page.items) {
      if (product.id == productId) return product;
    }
    try {
      final product = await _api.getProduct(productId);
      final latest = state.value;
      if (latest == null) return null;
      final items = [
        product,
        ...latest.page.items.where((item) => item.id != product.id),
      ];
      state = AsyncData(
        latest.copyWith(
          page: CatalogProductPage(
            items: items,
            total: latest.page.total,
            catalogTotal: latest.page.catalogTotal,
            listingTotal: latest.page.listingTotal,
            duplicatesRemoved: latest.page.duplicatesRemoved,
            storeTotal: latest.page.storeTotal,
            stores: latest.page.stores,
            limit: latest.page.limit,
            offset: latest.page.offset,
          ),
          deepLinkUnavailable: false,
          clearError: true,
        ),
      );
      return product;
    } catch (_) {
      final latest = state.value;
      if (latest != null) {
        state = AsyncData(latest.copyWith(deepLinkUnavailable: true));
      }
      return null;
    }
  }

  Future<CatalogCompetitorComparison> discoverCompetitors(
    CatalogProduct product,
  ) async {
    var oe = product.oe;
    var mpn = product.mpn;
    // Legacy store-sync rows may have neither public OE nor persisted MPN.
    // Repair one exact owned listing before discovery so the search does not
    // silently fall back to a weak title-only path.
    if (oe == null && mpn == null) {
      final store = product.primaryStore;
      // Витрина несёт два разных внешних номера: магазина (`externalId`) и
      // объявления (`sourceListingId`). Починке нужен номер объявления —
      // подстановка номера магазина искала `listings.external_id`, которого
      // там не бывает никогда, и роняла сбор 404-й у 69,5 % карточек Prom.
      final listingExternalId = store?.sourceListingId;
      if (store != null &&
          listingExternalId != null &&
          listingExternalId.isNotEmpty) {
        try {
          final enriched = await _api.enrichIdentifiers(
            storeId: store.storeId,
            externalId: listingExternalId,
          );
          oe = enriched.oe;
          mpn = enriched.mpn;
        } catch (error) {
          if (markoIsSessionExpired(error)) rethrow;
          // Починка карточки — не условие поиска, а попытка его улучшить.
          // Её отказ оставляет сбор на артикуле и названии, а не отменяет.
        }
      }
    }
    return _api.discoverCompetitors(
      sku: product.sku,
      oe: oe,
      mpn: mpn,
      brand: product.brand,
      title: product.name,
      currentPrice: product.primaryStore?.price ?? product.priceMin,
      currency: product.primaryStore?.currency ?? product.currency,
    );
  }

  /// Запустить отсев моделью по последнему сбору этой карточки.
  ///
  /// Возвращает `null`, если дорожка выключена в этой среде: тогда карточка
  /// ведёт себя как прежде и просто перечитывает сохранённое, а не показывает
  /// оператору ошибку про выключенный флаг.
  Future<CatalogMatchRun?> startMatch(CatalogProduct product) async {
    try {
      return await _api.startMatch(
        sku: product.sku,
        oe: product.oe,
        mpn: product.mpn,
        brand: product.brand,
        title: product.name,
        // Состояние товара живёт в характеристиках объявления, которых у
        // карточки нет; сервер берёт его из собранного снимка сам.
      );
    } on ApiException catch (error) {
      if (error.code == 'CATALOG_MATCH_DISABLED') return null;
      rethrow;
    }
  }

  Future<CatalogMatchRun> matchStatus(String matchRunId) =>
      _api.getMatch(matchRunId);

  Future<String?> enrichOe(CatalogProduct product) {
    final store = product.primaryStore;
    // Тот же адресный номер, что и в discoverCompetitors: объявления, не
    // магазина.
    final listingExternalId = store?.sourceListingId;
    if (store == null ||
        listingExternalId == null ||
        listingExternalId.isEmpty) {
      return Future.value(null);
    }
    return _api.enrichOe(
      storeId: store.storeId,
      externalId: listingExternalId,
    );
  }

  Future<void> _reload({
    required String query,
    required Set<String> storeIds,
    String? kempStatus,
    bool noOem = false,
  }) async {
    final generation = ++_requestGeneration;
    state = AsyncData(
      _current.copyWith(
        query: query,
        selectedStoreIds: storeIds,
        kempStatus: kempStatus,
        noOem: noOem,
        clearKempStatus: kempStatus == null,
        isSearching: true,
        clearError: true,
      ),
    );
    try {
      final page = await _api.listProducts(
        query: query,
        storeIds: storeIds.toList(growable: false),
        kempStatus: kempStatus,
        noOem: noOem,
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

  Future<void> refresh() => _reload(
    query: _current.query,
    storeIds: _current.selectedStoreIds,
    kempStatus: _current.kempStatus,
    noOem: _current.noOem,
  );

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
        kempStatus: current.kempStatus,
        noOem: current.noOem,
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
            limit: next.limit,
            offset: current.page.offset,
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
