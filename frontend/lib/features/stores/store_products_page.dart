import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'store_models.dart';
import 'stores_controller.dart';

class StoreProductsPage extends ConsumerWidget {
  const StoreProductsPage({required this.storeId, super.key});

  final String storeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = storeProductsProvider(storeId);
    final asyncState = ref.watch(provider);
    final controller = ref.read(provider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: Text(asyncState.value?.store.displayName ?? 'Товары магазина'),
        actions: [
          IconButton(
            tooltip: 'Обновить товары',
            onPressed: controller.reload,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: asyncState.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _ProductsError(
          message: error.toString(),
          onRetry: controller.reload,
        ),
        data: (state) => _ProductList(
          state: state,
          onRefresh: controller.reload,
          onLoadMore: controller.loadMore,
        ),
      ),
    );
  }
}

class _ProductList extends StatelessWidget {
  const _ProductList({
    required this.state,
    required this.onRefresh,
    required this.onLoadMore,
  });

  final StoreProductsState state;
  final Future<void> Function() onRefresh;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    if (state.page.items.isEmpty) {
      return RefreshIndicator(
        onRefresh: onRefresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: const [
            SizedBox(height: 180),
            Center(
              child: Text('В этом магазине пока нет импортированных товаров'),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: state.page.items.length + (state.page.hasMore ? 1 : 0),
        separatorBuilder: (_, _) => const SizedBox(height: 8),
        itemBuilder: (context, index) {
          if (index == state.page.items.length) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton.icon(
                  onPressed: state.isLoadingMore ? null : onLoadMore,
                  icon: state.isLoadingMore
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.expand_more),
                  label: Text(
                    'Показать ещё (${state.page.items.length} из ${state.page.total})',
                  ),
                ),
              ),
            );
          }
          final product = state.page.items[index];
          return Card(
            child: ListTile(
              title: Text(product.name),
              subtitle: Text(product.details),
              trailing: Text(
                product.priceLabel,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          );
        },
      ),
    );
  }
}

class _ProductsError extends StatelessWidget {
  const _ProductsError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('Повторить')),
          ],
        ),
      ),
    );
  }
}
