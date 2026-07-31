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
import 'widgets/cross_store_match_card.dart';
import 'widgets/product_card.dart';

double _horizontalContentPadding(double width) {
  return width > 1168 ? (width - 1120) / 2 : 24;
}

class StoreProductsPage extends ConsumerStatefulWidget {
  const StoreProductsPage({
    required this.storeId,
    this.initialQuery = '',
    super.key,
  });

  final String storeId;

  /// Query carried by the route, used when arriving from a cross-store hint.
  final String initialQuery;

  @override
  ConsumerState<StoreProductsPage> createState() => _StoreProductsPageState();
}

class _StoreProductsPageState extends ConsumerState<StoreProductsPage> {
  late final TextEditingController _searchController = TextEditingController(
    text: widget.initialQuery,
  );

  @override
  void initState() {
    super.initState();
    if (widget.initialQuery.trim().isNotEmpty) {
      _applyRouteQuery(widget.initialQuery);
    }
  }

  @override
  void didUpdateWidget(covariant StoreProductsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialQuery != oldWidget.initialQuery) {
      _searchController.text = widget.initialQuery;
      _applyRouteQuery(widget.initialQuery);
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _applyRouteQuery(String query) {
    final provider = storeProductsProvider(widget.storeId);
    // The catalog is still loading on the first frame; the controller keeps
    // the query and applies it as soon as the first page arrives.
    unawaited(
      ref
          .read(provider.future)
          .then((_) => ref.read(provider.notifier).applyQuery(query)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = storeProductsProvider(widget.storeId);
    final asyncState = ref.watch(provider);
    final controller = ref.read(provider.notifier);
    final state = asyncState.value;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _ProductsHeader(
              title:
                  state?.store.displayName ??
                  context.localized(
                    ru: 'Товары магазина',
                    uk: 'Товари магазину',
                  ),
              count: state?.page.total,
              searching: state?.hasQuery ?? false,
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
                  searchController: _searchController,
                  onSearch: controller.search,
                  onRefresh: controller.reload,
                  onLoadMore: controller.loadMore,
                  onOpenMatch: _openMatch,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openMatch(CrossStoreMatch match) {
    final storeId = match.storeId;
    if (storeId == null) return;
    context.goNamed(
      'store-products',
      pathParameters: {'storeId': storeId},
      queryParameters: {'q': match.matchedValue},
    );
  }
}

class _ProductsHeader extends StatelessWidget {
  const _ProductsHeader({
    required this.title,
    required this.count,
    required this.searching,
    required this.onBack,
    required this.onRefresh,
  });

  final String title;
  final int? count;
  final bool searching;
  final VoidCallback onBack;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 72),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final horizontalPadding = _horizontalContentPadding(
            constraints.maxWidth,
          );
          final compactActions =
              constraints.maxWidth < 600 ||
              MediaQuery.textScalerOf(context).scale(14) >= 21;
          return Padding(
            padding: EdgeInsets.symmetric(
              horizontal: horizontalPadding,
              vertical: 8,
            ),
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
                          searching
                              ? context.localized(
                                  ru: 'найдено товаров: $count',
                                  uk: 'знайдено товарів: $count',
                                )
                              : context.localized(
                                  ru: '$count товаров в каталоге',
                                  uk: '$count товарів у каталозі',
                                ),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                if (compactActions)
                  IconButton.outlined(
                    tooltip: context.localized(ru: 'Обновить', uk: 'Оновити'),
                    onPressed: onRefresh,
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                  )
                else
                  OutlinedButton.icon(
                    onPressed: onRefresh,
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                    label: Text(
                      context.localized(ru: 'Обновить', uk: 'Оновити'),
                    ),
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
    required this.searchController,
    required this.onSearch,
    required this.onRefresh,
    required this.onLoadMore,
    required this.onOpenMatch,
  });

  final StoreProductsState state;
  final TextEditingController searchController;
  final ValueChanged<String> onSearch;
  final Future<void> Function() onRefresh;
  final VoidCallback onLoadMore;
  final void Function(CrossStoreMatch match) onOpenMatch;

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
    final state = widget.state;
    final products = state.page.items;

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
        final textScale = MediaQuery.textScalerOf(context).scale(1);
        final cardDetailsExtent = 126 + ((textScale - 1).clamp(0.0, 1.0) * 72);
        EdgeInsets inset(double top) =>
            EdgeInsets.fromLTRB(horizontalPadding, top, horizontalPadding, 0);

        return RefreshIndicator(
          onRefresh: widget.onRefresh,
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverPadding(
                padding: inset(28),
                sliver: SliverToBoxAdapter(
                  child: _CatalogHeading(
                    controller: widget.searchController,
                    onSearch: widget.onSearch,
                    isSearching: state.isSearching,
                    compact: contentWidth < 720,
                  ),
                ),
              ),
              if (state.error != null)
                SliverPadding(
                  padding: inset(14),
                  sliver: SliverToBoxAdapter(
                    child: MarkoInlineMessage(
                      message: state.error!,
                      tone: MarkoMessageTone.error,
                    ),
                  ),
                ),
              if (products.isNotEmpty)
                SliverPadding(
                  padding: inset(18),
                  sliver: SliverGrid(
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: columns,
                      crossAxisSpacing: 14,
                      mainAxisSpacing: 14,
                      mainAxisExtent: cardWidth + cardDetailsExtent,
                    ),
                    delegate: SliverChildBuilderDelegate(
                      (context, index) => ProductCard(product: products[index]),
                      childCount: products.length,
                    ),
                  ),
                )
              else if (!state.isSearching)
                SliverPadding(
                  padding: inset(24),
                  sliver: SliverToBoxAdapter(
                    child: state.hasQuery
                        ? _NoLocalMatches(query: state.query.trim())
                        : const _EmptyProducts(),
                  ),
                ),
              if (state.isEmptyResult)
                SliverPadding(
                  padding: inset(20),
                  sliver: SliverToBoxAdapter(
                    child: _ElsewhereSection(
                      state: state,
                      onOpenMatch: widget.onOpenMatch,
                    ),
                  ),
                ),
              if (state.page.hasMore)
                SliverPadding(
                  padding: inset(20),
                  sliver: SliverToBoxAdapter(
                    child: Center(
                      child: OutlinedButton.icon(
                        onPressed: state.isLoadingMore
                            ? null
                            : widget.onLoadMore,
                        icon: state.isLoadingMore
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
                                '(${products.length} из ${state.page.total})',
                            uk:
                                'Показати ще '
                                '(${products.length} з ${state.page.total})',
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
  const _CatalogHeading({
    required this.controller,
    required this.onSearch,
    required this.isSearching,
    required this.compact,
  });

  final TextEditingController controller;
  final ValueChanged<String> onSearch;
  final bool isSearching;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final heading = Column(
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
    final search = _CatalogSearchField(
      controller: controller,
      onSearch: onSearch,
      isSearching: isSearching,
    );

    if (compact) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [heading, const SizedBox(height: 16), search],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(child: heading),
        const SizedBox(width: 24),
        SizedBox(width: 340, child: search),
      ],
    );
  }
}

class _CatalogSearchField extends StatelessWidget {
  const _CatalogSearchField({
    required this.controller,
    required this.onSearch,
    required this.isSearching,
  });

  final TextEditingController controller;
  final ValueChanged<String> onSearch;
  final bool isSearching;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<TextEditingValue>(
      valueListenable: controller,
      builder: (context, value, _) {
        return TextField(
          controller: controller,
          onChanged: onSearch,
          onSubmitted: onSearch,
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            isDense: true,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 14,
              vertical: 12,
            ),
            hintText: context.localized(
              ru: 'Поиск по названию, SKU или OEM',
              uk: 'Пошук за назвою, SKU або OEM',
            ),
            prefixIcon: const Icon(Icons.search_rounded, size: 19),
            suffixIcon: isSearching
                ? const Padding(
                    padding: EdgeInsets.all(13),
                    child: SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  )
                : value.text.isEmpty
                ? null
                : IconButton(
                    tooltip: context.localized(ru: 'Очистить', uk: 'Очистити'),
                    onPressed: () {
                      controller.clear();
                      onSearch('');
                    },
                    icon: const Icon(Icons.close_rounded, size: 18),
                  ),
          ),
        );
      },
    );
  }
}

class _NoLocalMatches extends StatelessWidget {
  const _NoLocalMatches({required this.query});

  final String query;

  @override
  Widget build(BuildContext context) {
    return MarkoInlineMessage(
      tone: MarkoMessageTone.warning,
      message: context.localized(
        ru: 'В этом магазине ничего не найдено по запросу «$query».',
        uk: 'У цьому магазині нічого не знайдено за запитом «$query».',
      ),
    );
  }
}

class _ElsewhereSection extends StatelessWidget {
  const _ElsewhereSection({required this.state, required this.onOpenMatch});

  final StoreProductsState state;
  final void Function(CrossStoreMatch match) onOpenMatch;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    if (state.isSearchingElsewhere) {
      return Row(
        children: [
          const SizedBox.square(
            dimension: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 10),
          Text(
            context.localized(
              ru: 'Ищем в других магазинах…',
              uk: 'Шукаємо в інших магазинах…',
            ),
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: colors.muted),
          ),
        ],
      );
    }

    final elsewhere = state.elsewhere;
    if (elsewhere == null) return const SizedBox.shrink();
    if (elsewhere.matches.isEmpty) {
      return Text(
        context.localized(
          ru: 'В других подключённых магазинах тоже ничего не нашлось.',
          uk: 'В інших підключених магазинах теж нічого не знайшлося.',
        ),
        style: Theme.of(
          context,
        ).textTheme.bodyMedium?.copyWith(color: colors.muted),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          context.localized(
            ru: 'Найдено в других магазинах',
            uk: 'Знайдено в інших магазинах',
          ),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 4),
        Text(
          elsewhere.normalizedQuery.isEmpty
              ? context.localized(
                  ru: 'Совпадения по названию товара.',
                  uk: 'Збіги за назвою товару.',
                )
              : context.localized(
                  ru:
                      'Совпадения по номеру ${elsewhere.normalizedQuery}. '
                      'Откройте карточку, чтобы продолжить работу там.',
                  uk:
                      'Збіги за номером ${elsewhere.normalizedQuery}. '
                      'Відкрийте картку, щоб продовжити роботу там.',
                ),
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
        const SizedBox(height: 12),
        for (final match in elsewhere.matches) ...[
          CrossStoreMatchCard(match: match, onOpenStore: onOpenMatch),
          const SizedBox(height: 10),
        ],
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
