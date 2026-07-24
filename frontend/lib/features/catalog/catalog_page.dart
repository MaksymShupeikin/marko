import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import 'catalog_controller.dart';
import 'widgets/catalog_product_card.dart';

class CatalogPage extends ConsumerStatefulWidget {
  const CatalogPage({required this.onOpenPriceComparison, super.key});

  final VoidCallback onOpenPriceComparison;

  @override
  ConsumerState<CatalogPage> createState() => _CatalogPageState();
}

class _CatalogPageState extends ConsumerState<CatalogPage> {
  final _searchController = TextEditingController();
  Timer? _searchDebounce;

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncState = ref.watch(catalogControllerProvider);
    return asyncState.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: MarkoInlineMessage(
          message: error.toString(),
          tone: MarkoMessageTone.error,
          action: TextButton(
            onPressed: () => ref.invalidate(catalogControllerProvider),
            child: const Text('Повторить'),
          ),
        ),
      ),
      data: (state) => _CatalogContent(
        state: state,
        searchController: _searchController,
        onOpenPriceComparison: widget.onOpenPriceComparison,
        onQueryChanged: _queueSearch,
        onQuerySubmitted: _searchNow,
        onClearQuery: _clearSearch,
        onRefresh: () => ref.read(catalogControllerProvider.notifier).refresh(),
        onLoadMore: () =>
            ref.read(catalogControllerProvider.notifier).loadMore(),
      ),
    );
  }

  void _queueSearch(String query) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 350), () {
      if (mounted) _searchNow(query);
    });
    setState(() {});
  }

  void _searchNow(String query) {
    _searchDebounce?.cancel();
    ref.read(catalogControllerProvider.notifier).search(query);
  }

  void _clearSearch() {
    _searchController.clear();
    _searchNow('');
    setState(() {});
  }
}

class _CatalogContent extends StatelessWidget {
  const _CatalogContent({
    required this.state,
    required this.searchController,
    required this.onOpenPriceComparison,
    required this.onQueryChanged,
    required this.onQuerySubmitted,
    required this.onClearQuery,
    required this.onRefresh,
    required this.onLoadMore,
  });

  final CatalogState state;
  final TextEditingController searchController;
  final VoidCallback onOpenPriceComparison;
  final ValueChanged<String> onQueryChanged;
  final ValueChanged<String> onQuerySubmitted;
  final VoidCallback onClearQuery;
  final VoidCallback onRefresh;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final page = state.page;
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _CatalogHeader(onRefresh: onRefresh),
                const SizedBox(height: 20),
                TextField(
                  key: const ValueKey('catalog-oe-search'),
                  controller: searchController,
                  onChanged: onQueryChanged,
                  onSubmitted: onQuerySubmitted,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: 'Поиск по OE/OEM',
                    prefixIcon: const Icon(Icons.search_rounded),
                    suffixIcon: searchController.text.isEmpty
                        ? null
                        : IconButton(
                            tooltip: 'Очистить поиск',
                            onPressed: onClearQuery,
                            icon: const Icon(Icons.close_rounded),
                          ),
                  ),
                ),
                if (state.isSearching) ...[
                  const SizedBox(height: 2),
                  const LinearProgressIndicator(minHeight: 2),
                ],
                const SizedBox(height: 16),
                _CatalogStats(state: state),
                if (state.error != null) ...[
                  const SizedBox(height: 14),
                  MarkoInlineMessage(
                    message: state.error!,
                    tone: MarkoMessageTone.error,
                  ),
                ],
                const SizedBox(height: 20),
                if (page.items.isEmpty)
                  _EmptyCatalog(hasQuery: state.query.isNotEmpty)
                else ...[
                  Text(
                    state.query.isEmpty ? 'Товары' : 'Найдено ${page.total}',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 12),
                  ...page.items.map(
                    (product) => Align(
                      alignment: Alignment.centerLeft,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 780),
                        child: SizedBox(
                          width: double.infinity,
                          child: Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: CatalogProductCard(
                              product: product,
                              onCompare: onOpenPriceComparison,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (page.hasMore) ...[
                    const SizedBox(height: 6),
                    Center(
                      child: OutlinedButton.icon(
                        onPressed: state.isLoadingMore ? null : onLoadMore,
                        icon: state.isLoadingMore
                            ? const SizedBox.square(
                                dimension: 17,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.expand_more_rounded, size: 18),
                        label: Text(
                          'Показать ещё (${page.items.length} из ${page.total})',
                        ),
                      ),
                    ),
                  ],
                ],
                const SizedBox(height: 12),
                Text(
                  'Дубли объединяются только по подтверждаемому артикулу и бренду. '
                  'Похожие названия без идентификатора остаются отдельными товарами.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: colors.muted),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _CatalogHeader extends StatelessWidget {
  const _CatalogHeader({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Каталог Prom.ua',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 7),
              Text(
                'Товары из «Моих магазинов» без повторяющихся объявлений.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.muted),
              ),
            ],
          ),
        ),
        IconButton.outlined(
          tooltip: 'Обновить каталог',
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh_rounded, size: 19),
        ),
      ],
    );
  }
}

class _CatalogStats extends StatelessWidget {
  const _CatalogStats({required this.state});

  final CatalogState state;

  @override
  Widget build(BuildContext context) {
    final page = state.page;
    final values = <(String, String)>[
      ('Уникальных товаров', '${page.catalogTotal}'),
      ('Объявлений', '${page.listingTotal}'),
      ('Дублей объединено', '${page.duplicatesRemoved}'),
      ('Магазинов', '${page.storeTotal}'),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: values
          .map((value) => _StatChip(label: value.$1, value: value.$2))
          .toList(growable: false),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border.all(color: colors.border),
        borderRadius: BorderRadius.circular(9),
      ),
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '$value  ',
              style: TextStyle(color: colors.ink, fontWeight: FontWeight.w700),
            ),
            TextSpan(
              text: label,
              style: TextStyle(color: colors.muted),
            ),
          ],
        ),
        style: Theme.of(context).textTheme.bodySmall,
      ),
    );
  }
}

class _EmptyCatalog extends StatelessWidget {
  const _EmptyCatalog({required this.hasQuery});

  final bool hasQuery;

  @override
  Widget build(BuildContext context) {
    return MarkoPanel(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          const Icon(Icons.inventory_2_outlined, size: 30),
          const SizedBox(height: 12),
          Text(
            hasQuery ? 'По OE/OEM ничего не найдено' : 'Каталог пока пуст',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            hasQuery
                ? 'Проверьте номер или попробуйте артикул без пробелов и дефисов.'
                : 'Добавьте магазин в «Мои магазины» и дождитесь синхронизации.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
