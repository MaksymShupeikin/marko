import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'store_models.dart';
import 'stores_api.dart';

class StoresController extends AsyncNotifier<StoresState> {
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
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.host != 'prom.ua' && uri.host != 'www.prom.ua')) {
      state = AsyncData(
        _current.copyWith(
          error: 'Введите корректную ссылку магазина на prom.ua',
        ),
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
          await refresh();
          return;
        }
      } catch (error) {
        state = AsyncData(_current.copyWith(error: error.toString()));
      }
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }
}

final storesControllerProvider =
    AsyncNotifierProvider<StoresController, StoresState>(StoresController.new);

class StoreProductsController extends AsyncNotifier<StoreProductsState> {
  StoreProductsController(this.storeId);

  final String storeId;
  StoresApi get _api => ref.read(storesApiProvider);

  @override
  Future<StoreProductsState> build() async {
    final api = ref.watch(storesApiProvider);
    final storeFuture = api.getStore(storeId);
    final productsFuture = api.listProducts(storeId);
    return StoreProductsState(
      store: await storeFuture,
      page: await productsFuture,
    );
  }

  Future<void> reload() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(build);
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
      );
      state = AsyncData(
        current.copyWith(
          isLoadingMore: false,
          page: ProductPage(
            items: [...current.page.items, ...next.items],
            total: next.total,
          ),
        ),
      );
    } catch (error) {
      state = AsyncData(
        current.copyWith(isLoadingMore: false, error: error.toString()),
      );
    }
  }

  Future<bool> deleteStore() async {
    final current = state.value;
    if (current == null || current.isDeleting) return false;
    state = AsyncData(current.copyWith(isDeleting: true, clearError: true));
    try {
      await _api.deleteStore(storeId);
      ref.invalidate(storesControllerProvider);
      return true;
    } catch (error) {
      state = AsyncData(
        current.copyWith(isDeleting: false, error: error.toString()),
      );
      return false;
    }
  }
}

final storeProductsProvider = AsyncNotifierProvider.autoDispose
    .family<StoreProductsController, StoreProductsState, String>(
      StoreProductsController.new,
    );
