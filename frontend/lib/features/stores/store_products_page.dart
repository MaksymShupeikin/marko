import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_cached_image.dart';
import 'store_models.dart';
import 'stores_controller.dart';
import 'widgets/product_card.dart';

double _horizontalContentPadding(double width) {
  return width > 1168 ? (width - 1120) / 2 : 24;
}

class StoreProductsPage extends ConsumerWidget {
  const StoreProductsPage({required this.storeId, super.key});

  final String storeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = storeProductsProvider(storeId);
    final asyncState = ref.watch(provider);
    final controller = ref.read(provider.notifier);

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _ProductsHeader(
              title:
                  asyncState.value?.store.displayName ??
                  context.localized(
                    ru: 'Товары магазина',
                    uk: 'Товари магазину',
                  ),
              count: asyncState.value?.page.total,
              onBack: context.pop,
              onRefresh: controller.reload,
            ),
            Expanded(
              child: asyncState.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (error, _) => _ProductsError(
                  message: error.toString(),
                  onRetry: controller.reload,
                ),
                data: (state) => _ProductCatalog(
                  state: state,
                  onRefresh: controller.reload,
                  onLoadMore: controller.loadMore,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProductsHeader extends StatelessWidget {
  const _ProductsHeader({
    required this.title,
    required this.count,
    required this.onBack,
    required this.onRefresh,
  });

  final String title;
  final int? count;
  final VoidCallback onBack;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      height: 72,
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final horizontalPadding = _horizontalContentPadding(
            constraints.maxWidth,
          );
          return Padding(
            padding: EdgeInsets.symmetric(horizontal: horizontalPadding),
            child: Row(
              children: [
                IconButton(
                  tooltip: context.localized(
                    ru: 'Назад к магазинам',
                    uk: 'Назад до магазинів',
                  ),
                  onPressed: onBack,
                  icon: const Icon(Icons.arrow_back_rounded, size: 20),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      if (count != null)
                        Text(
                          context.localized(
                            ru: '$count товаров в каталоге',
                            uk: '$count товарів у каталозі',
                          ),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: onRefresh,
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: Text(context.localized(ru: 'Обновить', uk: 'Оновити')),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ProductCatalog extends StatefulWidget {
  const _ProductCatalog({
    required this.state,
    required this.onRefresh,
    required this.onLoadMore,
  });

  final StoreProductsState state;
  final Future<void> Function() onRefresh;
  final VoidCallback onLoadMore;

  @override
  State<_ProductCatalog> createState() => _ProductCatalogState();
}

class _ProductCatalogState extends State<_ProductCatalog> {
  final Set<String> _preloadedUrls = {};
  bool _preloadScheduled = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _schedulePreload();
  }

  @override
  void didUpdateWidget(covariant _ProductCatalog oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state.page.items.length != widget.state.page.items.length) {
      _schedulePreload();
    }
  }

  @override
  Widget build(BuildContext context) {
    final products = widget.state.page.items;
    if (products.isEmpty) {
      return RefreshIndicator(
        onRefresh: widget.onRefresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(24),
          children: const [SizedBox(height: 120), _EmptyProducts()],
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final horizontalPadding = _horizontalContentPadding(
          constraints.maxWidth,
        );
        final contentWidth = constraints.maxWidth - (horizontalPadding * 2);
        final columns = contentWidth >= 1000
            ? 4
            : contentWidth >= 720
            ? 3
            : contentWidth >= 500
            ? 2
            : 1;
        final cardWidth = (contentWidth - (14 * (columns - 1))) / columns;

        return RefreshIndicator(
          onRefresh: widget.onRefresh,
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverPadding(
                padding: EdgeInsets.fromLTRB(
                  horizontalPadding,
                  28,
                  horizontalPadding,
                  0,
                ),
                sliver: const SliverToBoxAdapter(child: _CatalogHeading()),
              ),
              if (widget.state.error != null)
                SliverPadding(
                  padding: EdgeInsets.fromLTRB(
                    horizontalPadding,
                    14,
                    horizontalPadding,
                    0,
                  ),
                  sliver: SliverToBoxAdapter(
                    child: MarkoInlineMessage(
                      message: widget.state.error!,
                      tone: MarkoMessageTone.error,
                    ),
                  ),
                ),
              SliverPadding(
                padding: EdgeInsets.fromLTRB(
                  horizontalPadding,
                  18,
                  horizontalPadding,
                  0,
                ),
                sliver: SliverGrid(
                  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: columns,
                    crossAxisSpacing: 14,
                    mainAxisSpacing: 14,
                    mainAxisExtent: cardWidth + 126,
                  ),
                  delegate: SliverChildBuilderDelegate(
                    (context, index) => ProductCard(product: products[index]),
                    childCount: products.length,
                  ),
                ),
              ),
              if (widget.state.page.hasMore)
                SliverPadding(
                  padding: EdgeInsets.fromLTRB(
                    horizontalPadding,
                    20,
                    horizontalPadding,
                    0,
                  ),
                  sliver: SliverToBoxAdapter(
                    child: Center(
                      child: OutlinedButton.icon(
                        onPressed: widget.state.isLoadingMore
                            ? null
                            : widget.onLoadMore,
                        icon: widget.state.isLoadingMore
                            ? const SizedBox.square(
                                dimension: 17,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.expand_more_rounded, size: 18),
                        label: Text(
                          context.localized(
                            ru:
                                'Показать ещё '
                                '(${products.length} из ${widget.state.page.total})',
                            uk:
                                'Показати ще '
                                '(${products.length} з ${widget.state.page.total})',
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              const SliverPadding(padding: EdgeInsets.only(bottom: 28)),
            ],
          ),
        );
      },
    );
  }

  void _schedulePreload() {
    if (_preloadScheduled || widget.state.page.items.isEmpty) return;
    _preloadScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _preloadScheduled = false;
      if (!mounted) return;
      final width = MediaQuery.sizeOf(context).width;
      final limit = width >= 1000
          ? 12
          : width >= 700
          ? 9
          : 6;
      final urls = widget.state.page.items
          .map((product) => product.imageUrl)
          .whereType<String>()
          .where((url) => !_preloadedUrls.contains(url))
          .take(limit)
          .toList(growable: false);
      if (urls.isEmpty) return;
      _preloadedUrls.addAll(urls);
      unawaited(precacheMarkoImages(context, urls, limit: limit));
    });
  }
}

class _CatalogHeading extends StatelessWidget {
  const _CatalogHeading();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          context.localized(ru: 'Каталог', uk: 'Каталог'),
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 7),
        Text(
          context.localized(
            ru: 'Фото и текущая цена каждого импортированного товара.',
            uk: 'Фото та поточна ціна кожного імпортованого товару.',
          ),
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
        ),
      ],
    );
  }
}

class _EmptyProducts extends StatelessWidget {
  const _EmptyProducts();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: MarkoPanel(
          padding: const EdgeInsets.all(30),
          child: Column(
            children: [
              Icon(Icons.inventory_2_outlined, color: colors.muted, size: 30),
              const SizedBox(height: 13),
              Text(
                context.localized(
                  ru: 'Каталог пока пуст',
                  uk: 'Каталог поки порожній',
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 5),
              Text(
                context.localized(
                  ru: 'Запустите синхронизацию магазина, чтобы импортировать товары.',
                  uk: 'Запустіть синхронізацію магазину, щоб імпортувати товари.',
                ),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
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
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Column(
            children: [
              MarkoInlineMessage(
                message: message,
                tone: MarkoMessageTone.error,
              ),
              const SizedBox(height: 14),
              MarkoButton(
                label: context.localized(ru: 'Повторить', uk: 'Повторити'),
                onPressed: onRetry,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
