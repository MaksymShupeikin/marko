import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_menu.dart';
import 'catalog_controller.dart';
import 'catalog_import_dialog.dart';
import 'catalog_models.dart';
import 'widgets/catalog_product_card.dart';
import 'widgets/catalog_product_details_sheet.dart';

class CatalogPage extends ConsumerStatefulWidget {
  const CatalogPage({
    required this.onOpenPriceComparison,
    this.canAdministerWorkspace = false,
    this.initialStoreId,
    this.onInitialStoreApplied,
    this.initialProductId,
    this.onOpenProductDeepLink,
    super.key,
  });

  final VoidCallback onOpenPriceComparison;
  final bool canAdministerWorkspace;

  /// Store to preselect in the filter, set when the operator opened this page
  /// by tapping that store in "Мои магазины".
  final String? initialStoreId;

  /// Reported once the preselection has been applied, so the caller can drop
  /// it and leave the filter under the operator's control from then on.
  final VoidCallback? onInitialStoreApplied;

  /// Stable product identity carried by `/catalog/products/:productId`.
  final String? initialProductId;

  /// Updates the browser location before opening a product from the list.
  final ValueChanged<String>? onOpenProductDeepLink;

  @override
  ConsumerState<CatalogPage> createState() => _CatalogPageState();
}

class _CatalogPageState extends ConsumerState<CatalogPage> {
  final _searchController = TextEditingController();
  Timer? _searchDebounce;

  String? _appliedStoreId;
  String? _appliedProductId;

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  /// Applies the store the operator arrived with, once, after the first page
  /// is in place. Reading the controller any earlier would race its own build.
  void _applyInitialStore() {
    final storeId = widget.initialStoreId;
    if (storeId == null || storeId == _appliedStoreId) return;
    _appliedStoreId = storeId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      widget.onInitialStoreApplied?.call();
      unawaited(
        ref.read(catalogControllerProvider.notifier).selectStores({storeId}),
      );
    });
  }

  void _applyInitialProduct(CatalogState state) {
    final productId = widget.initialProductId;
    if (productId == null || productId == _appliedProductId) return;
    _appliedProductId = productId;
    final visible = state.page.items
        .where((product) => product.id == productId)
        .firstOrNull;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final product =
          visible ??
          await ref
              .read(catalogControllerProvider.notifier)
              .ensureVisible(productId);
      if (!mounted || product == null) return;
      _showProductDetails(product, updateLocation: false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final asyncState = ref.watch(catalogControllerProvider);
    return asyncState.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => MarkoAsyncErrorView(
        error: error,
        forbiddenResourceRu: 'каталогу товаров',
        forbiddenResourceUk: 'каталогу товарів',
        onRetry: () => ref.invalidate(catalogControllerProvider),
      ),
      data: (state) {
        _applyInitialStore();
        _applyInitialProduct(state);
        return _CatalogContent(
          state: state,
          canAdministerWorkspace: widget.canAdministerWorkspace,
          searchController: _searchController,
          onShowProductDetails: _showProductDetails,
          onQueryChanged: _queueSearch,
          onQuerySubmitted: _searchNow,
          onClearQuery: _clearSearch,
          onStoreChanged: (storeIds) => ref
              .read(catalogControllerProvider.notifier)
              .selectStores(storeIds),
          onRefresh: () =>
              ref.read(catalogControllerProvider.notifier).refresh(),
          onImport: _showCatalogImport,
          onLoadMore: () =>
              ref.read(catalogControllerProvider.notifier).loadMore(),
        );
      },
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

  void _showProductDetails(
    CatalogProduct product, {
    bool updateLocation = true,
  }) {
    final openDeepLink = widget.onOpenProductDeepLink;
    if (updateLocation && openDeepLink != null) {
      openDeepLink(product.id);
      return;
    }
    unawaited(
      showCatalogProductDetailsSheet(
        context: context,
        product: product,
        loadCompetitors: () => ref
            .read(catalogControllerProvider.notifier)
            .loadCompetitors(product),
        discoverCompetitors: widget.canAdministerWorkspace
            ? () => ref
                  .read(catalogControllerProvider.notifier)
                  .discoverCompetitors(product)
            : null,
        onCompare: widget.onOpenPriceComparison,
      ),
    );
  }

  void _showCatalogImport() {
    unawaited(
      showCatalogImportDialog(
        context: context,
        canAdministerWorkspace: widget.canAdministerWorkspace,
        onImported: () {
          unawaited(ref.read(catalogControllerProvider.notifier).refresh());
        },
      ),
    );
  }
}

class _CatalogContent extends StatelessWidget {
  const _CatalogContent({
    required this.state,
    required this.canAdministerWorkspace,
    required this.searchController,
    required this.onShowProductDetails,
    required this.onQueryChanged,
    required this.onQuerySubmitted,
    required this.onClearQuery,
    required this.onStoreChanged,
    required this.onRefresh,
    required this.onImport,
    required this.onLoadMore,
  });

  final CatalogState state;
  final bool canAdministerWorkspace;
  final TextEditingController searchController;
  final ValueChanged<CatalogProduct> onShowProductDetails;
  final ValueChanged<String> onQueryChanged;
  final ValueChanged<String> onQuerySubmitted;
  final VoidCallback onClearQuery;
  final ValueChanged<Set<String>> onStoreChanged;
  final VoidCallback onRefresh;
  final VoidCallback onImport;
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
                _CatalogHeader(
                  canImport: canAdministerWorkspace,
                  onImport: onImport,
                  onRefresh: onRefresh,
                ),
                const SizedBox(height: 20),
                TextField(
                  key: const ValueKey('catalog-oe-search'),
                  controller: searchController,
                  onChanged: onQueryChanged,
                  onSubmitted: onQuerySubmitted,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: context.localized(
                      ru: 'Поиск по OEM/OE, артикулу или названию объявления',
                      uk: 'Пошук за OEM/OE, артикулу або назві оголошення',
                    ),
                    prefixIcon: const Icon(Icons.search_rounded),
                    suffixIcon: searchController.text.isEmpty
                        ? null
                        : IconButton(
                            tooltip: context.localized(
                              ru: 'Очистить поиск',
                              uk: 'Очистити пошук',
                            ),
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
                _CatalogStats(state: state, onStoreChanged: onStoreChanged),
                if (state.error != null) ...[
                  const SizedBox(height: 14),
                  MarkoInlineMessage(
                    message: state.error!,
                    tone: MarkoMessageTone.error,
                  ),
                ],
                const SizedBox(height: 20),
                if (page.items.isEmpty)
                  _EmptyCatalog(
                    hasQuery:
                        state.query.isNotEmpty ||
                        state.selectedStoreIds.isNotEmpty,
                    canImport: canAdministerWorkspace,
                    onImport: onImport,
                  )
                else ...[
                  Text(
                    state.query.isEmpty
                        ? context.localized(ru: 'Товары', uk: 'Товари')
                        : context.localized(
                            ru: 'Найдено ${page.total}',
                            uk: 'Знайдено ${page.total}',
                          ),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 12),
                  if (state.deepLinkUnavailable) ...[
                    MarkoInlineMessage(
                      message: context.localized(
                        ru: 'Не удалось открыть товар по ссылке. Он недоступен в этой рабочей области или больше не существует.',
                        uk: 'Не вдалося відкрити товар за посиланням. Він недоступний у цій робочій області або більше не існує.',
                      ),
                      tone: MarkoMessageTone.warning,
                    ),
                    const SizedBox(height: 12),
                  ],
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
                              onShowDetails: () =>
                                  onShowProductDetails(product),
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
                          context.localized(
                            ru: 'Показать ещё (${page.items.length} из ${page.total})',
                            uk: 'Показати ще (${page.items.length} з ${page.total})',
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
                const SizedBox(height: 12),
                Text(
                  context.localized(
                    ru:
                        'Дубли объединяются только по подтверждаемому артикулу и бренду. '
                        'Похожие названия без идентификатора остаются отдельными товарами.',
                    uk:
                        'Дублі об’єднуються лише за підтвердженим артикулом і брендом. '
                        'Схожі назви без ідентифікатора залишаються окремими товарами.',
                  ),
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
  const _CatalogHeader({
    required this.canImport,
    required this.onImport,
    required this.onRefresh,
  });

  final bool canImport;
  final VoidCallback onImport;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.start,
      spacing: 16,
      runSpacing: 12,
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                context.localized(ru: 'Каталог Prom.ua', uk: 'Каталог Prom.ua'),
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 7),
              Text(
                context.localized(
                  ru: 'Товары из «Моих магазинов» без повторяющихся объявлений.',
                  uk: 'Товари з «Моїх магазинів» без повторюваних оголошень.',
                ),
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.muted),
              ),
            ],
          ),
        ),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (canImport)
              FilledButton.icon(
                key: const ValueKey('catalog-import-open'),
                onPressed: onImport,
                icon: const Icon(Icons.upload_file_rounded, size: 19),
                label: Text(
                  context.localized(ru: 'Импорт XLSX', uk: 'Імпорт XLSX'),
                ),
              ),
            IconButton.outlined(
              tooltip: context.localized(
                ru: 'Обновить каталог',
                uk: 'Оновити каталог',
              ),
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh_rounded, size: 19),
            ),
          ],
        ),
      ],
    );
  }
}

class _CatalogStats extends StatelessWidget {
  const _CatalogStats({required this.state, required this.onStoreChanged});

  final CatalogState state;
  final ValueChanged<Set<String>> onStoreChanged;

  @override
  Widget build(BuildContext context) {
    final page = state.page;
    final values = <(String, String)>[
      (
        context.localized(ru: 'Уникальных товаров', uk: 'Унікальних товарів'),
        '${page.catalogTotal}',
      ),
      (
        context.localized(ru: 'Объявлений', uk: 'Оголошень'),
        '${page.listingTotal}',
      ),
      (
        context.localized(ru: 'Дублей объединено', uk: 'Дублів об’єднано'),
        '${page.duplicatesRemoved}',
      ),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        ...values.map((value) => _StatChip(label: value.$1, value: value.$2)),
        _StoreFilterChip(
          stores: page.stores,
          storeTotal: page.storeTotal,
          selectedStoreIds: state.selectedStoreIds,
          enabled: !state.isSearching,
          onChanged: onStoreChanged,
        ),
      ],
    );
  }
}

class _StoreFilterChip extends StatelessWidget {
  const _StoreFilterChip({
    required this.stores,
    required this.storeTotal,
    required this.selectedStoreIds,
    required this.enabled,
    required this.onChanged,
  });

  final List<CatalogStoreOption> stores;
  final int storeTotal;
  final Set<String> selectedStoreIds;
  final bool enabled;
  final ValueChanged<Set<String>> onChanged;

  @override
  Widget build(BuildContext context) {
    final selectedStores = stores
        .where((store) => selectedStoreIds.contains(store.storeId))
        .toList(growable: false);

    return MarkoMultiMenuButton<String>(
      key: const ValueKey('catalog-store-filter'),
      tooltip: context.localized(ru: 'Выбрать магазины', uk: 'Обрати магазини'),
      enabled: enabled && stores.isNotEmpty,
      header: context.localized(ru: 'Магазины', uk: 'Магазини'),
      allLabel: context.localized(ru: 'Все магазины', uk: 'Усі магазини'),
      selectedValues: selectedStoreIds,
      onChanged: onChanged,
      entries: stores
          .map(
            (store) => MarkoMenuEntry(
              value: store.storeId,
              label: store.name,
              avatarText: _storeMonogram(store.name),
            ),
          )
          .toList(growable: false),
      child: _StatChip(
        label: switch (selectedStores.length) {
          0 => context.localized(ru: 'Магазинов', uk: 'Магазинів'),
          1 => context.localized(ru: 'Магазин', uk: 'Магазин'),
          _ => context.localized(ru: 'Магазины', uk: 'Магазини'),
        },
        value: switch (selectedStores.length) {
          0 => '$storeTotal',
          1 => selectedStores.first.name,
          final count => '$count',
        },
        trailing: const Icon(Icons.keyboard_arrow_down_rounded, size: 18),
      ),
    );
  }
}

String _storeMonogram(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) {
    return '?';
  }
  return trimmed.characters.first.toUpperCase();
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.value, this.trailing});

  final String label;
  final String value;
  final Widget? trailing;

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
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '$value  ',
                    style: TextStyle(
                      color: colors.ink,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  TextSpan(
                    text: label,
                    style: TextStyle(color: colors.muted),
                  ),
                ],
              ),
              style: Theme.of(context).textTheme.bodySmall,
              softWrap: true,
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: 5),
            IconTheme(
              data: IconThemeData(color: colors.muted),
              child: trailing!,
            ),
          ],
        ],
      ),
    );
  }
}

class _EmptyCatalog extends StatelessWidget {
  const _EmptyCatalog({
    required this.hasQuery,
    required this.canImport,
    required this.onImport,
  });

  final bool hasQuery;
  final bool canImport;
  final VoidCallback onImport;

  @override
  Widget build(BuildContext context) {
    return MarkoPanel(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          const Icon(Icons.inventory_2_outlined, size: 30),
          const SizedBox(height: 12),
          Text(
            hasQuery
                ? context.localized(
                    ru: 'По вашему запросу ничего не найдено',
                    uk: 'За вашим запитом нічого не знайдено',
                  )
                : context.localized(
                    ru: 'Каталог пока пуст',
                    uk: 'Каталог поки порожній',
                  ),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            hasQuery
                ? context.localized(
                    ru: 'Ищите по OEM/OE, артикулу, названию объявления или запчасти.',
                    uk: 'Шукайте за OEM/OE, артикулом, назвою оголошення або запчастини.',
                  )
                : context.localized(
                    ru: canImport
                        ? 'Импортируйте XLSX или добавьте магазин и дождитесь синхронизации.'
                        : 'Добавьте магазин в «Мои магазины» и дождитесь синхронизации.',
                    uk: canImport
                        ? 'Імпортуйте XLSX або додайте магазин і дочекайтеся синхронізації.'
                        : 'Додайте магазин у «Мої магазини» та дочекайтеся синхронізації.',
                  ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (!hasQuery && canImport) ...[
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onImport,
              icon: const Icon(Icons.upload_file_rounded),
              label: Text(
                context.localized(
                  ru: 'Импортировать XLSX',
                  uk: 'Імпортувати XLSX',
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
