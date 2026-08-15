part of '../recommendations_page.dart';

class _RecommendationQueue extends ConsumerStatefulWidget {
  const _RecommendationQueue({
    required this.state,
    required this.canAdministerWorkspace,
    required this.sessionExpired,
    required this.initialRecommendationId,
    required this.onOpenDeepLink,
    required this.onLoadMore,
  });

  final RecommendationsState state;
  final bool canAdministerWorkspace;
  final bool sessionExpired;
  final String? initialRecommendationId;
  final ValueChanged<String>? onOpenDeepLink;
  final VoidCallback onLoadMore;

  @override
  ConsumerState<_RecommendationQueue> createState() =>
      _RecommendationQueueState();
}

class _RecommendationQueueState extends ConsumerState<_RecommendationQueue> {
  int _focused = 0;
  late String? _detailId = widget.initialRecommendationId;

  List<PricingRecommendation> get _items => widget.state.page.items;

  @override
  Widget build(BuildContext context) {
    final wide =
        MarkoBreakpoints.isWide(MediaQuery.sizeOf(context).width) &&
        !markoWidgetTestBinding;
    final items = _items;
    if (items.isEmpty) return const SizedBox.shrink();
    final focused = items[_focused.clamp(0, items.length - 1)];
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyJ): () => _move(1),
        const SingleActivator(LogicalKeyboardKey.keyK): () => _move(-1),
        const SingleActivator(LogicalKeyboardKey.enter): () =>
            _open(focused.id),
        const SingleActivator(LogicalKeyboardKey.keyA): () =>
            _decide(focused, 'accepted'),
        const SingleActivator(LogicalKeyboardKey.keyR): () =>
            _decide(focused, 'rejected'),
        const SingleActivator(LogicalKeyboardKey.keyX): () => ref
            .read(recommendationsControllerProvider.notifier)
            .toggleSelected(focused.id),
        const SingleActivator(LogicalKeyboardKey.escape): () =>
            setState(() => _detailId = null),
      },
      child: Focus(
        autofocus: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SelectionBar(
              selectedCount: widget.state.selectedIds.length,
              visibleCount: items.length,
              busy: widget.state.batchBusy,
              sessionExpired: widget.sessionExpired,
              onSelectVisible: () => ref
                  .read(recommendationsControllerProvider.notifier)
                  .selectVisible(),
              onClear: () => ref
                  .read(recommendationsControllerProvider.notifier)
                  .clearSelection(),
              onAccept: () => _batch('accepted'),
              onReject: () => _batch('rejected'),
            ),
            if (wide)
              _RecommendationTable(
                items: items,
                selectedIds: widget.state.selectedIds,
                focusedId: focused.id,
                detailId: _detailId,
                onFocused: (id) => setState(
                  () => _focused = items.indexWhere((item) => item.id == id),
                ),
                onOpen: _open,
                onToggle: (id) => ref
                    .read(recommendationsControllerProvider.notifier)
                    .toggleSelected(id),
                canAdministerWorkspace: widget.canAdministerWorkspace,
                onOpenDeepLink: widget.onOpenDeepLink,
              )
            else
              ...items.asMap().entries.map(
                (entry) => Padding(
                  padding: const EdgeInsets.only(bottom: MarkoSpacing.sm),
                  child: _RecommendationCard(
                    recommendation: entry.value,
                    canAdministerWorkspace: widget.canAdministerWorkspace,
                    initiallyExpanded:
                        entry.value.id == widget.initialRecommendationId,
                    onOpenDeepLink: widget.onOpenDeepLink,
                  ),
                ),
              ),
            if (widget.state.page.hasMore)
              Center(
                child: OutlinedButton.icon(
                  onPressed: widget.state.isLoadingMore || widget.sessionExpired
                      ? null
                      : widget.onLoadMore,
                  icon: widget.state.isLoadingMore
                      ? const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.expand_more_rounded),
                  label: Text(
                    context.localized(
                      ru: 'Показать ещё (${items.length} из ${widget.state.page.total})',
                      uk: 'Показати ще (${items.length} із ${widget.state.page.total})',
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  void _move(int delta) {
    if (_items.isEmpty) return;
    setState(() {
      _focused = (_focused + delta).clamp(0, _items.length - 1);
    });
  }

  void _open(String id) {
    widget.onOpenDeepLink?.call(id);
    setState(() => _detailId = id);
  }

  Future<void> _decide(PricingRecommendation item, String decision) async {
    if (widget.sessionExpired) return;
    final values = await showRecommendationDecisionDialog(
      context,
      recommendation: item,
      decision: decision,
    );
    if (values == null || !mounted) return;
    await ref
        .read(recommendationsControllerProvider.notifier)
        .recordDecision(item.id, values);
  }

  Future<void> _batch(String decision) async {
    if (widget.sessionExpired || widget.state.selectedIds.isEmpty) return;
    final sample = _items
        .where((item) => widget.state.selectedIds.contains(item.id))
        .firstOrNull;
    if (sample == null) return;
    final values = await showRecommendationDecisionDialog(
      context,
      recommendation: sample,
      decision: decision,
    );
    if (values == null || !mounted) return;
    final result = await ref
        .read(recommendationsControllerProvider.notifier)
        .recordDecisionsBatch(decision: decision, values: values);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          context.localized(
            ru: 'Записано ${result.accepted}, ошибок ${result.failed}.',
            uk: 'Записано ${result.accepted}, помилок ${result.failed}.',
          ),
        ),
      ),
    );
  }
}

class _SelectionBar extends StatelessWidget {
  const _SelectionBar({
    required this.selectedCount,
    required this.visibleCount,
    required this.busy,
    required this.sessionExpired,
    required this.onSelectVisible,
    required this.onClear,
    required this.onAccept,
    required this.onReject,
  });

  final int selectedCount;
  final int visibleCount;
  final bool busy;
  final bool sessionExpired;
  final VoidCallback onSelectVisible;
  final VoidCallback onClear;
  final VoidCallback onAccept;
  final VoidCallback onReject;

  @override
  Widget build(BuildContext context) {
    if (selectedCount == 0) {
      return Align(
        alignment: Alignment.centerRight,
        child: TextButton(
          onPressed: onSelectVisible,
          child: Text(
            context.localized(
              ru: 'Выбрать видимые ($visibleCount)',
              uk: 'Вибрати видимі ($visibleCount)',
            ),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MarkoSpacing.sm),
      child: MarkoPanel(
        padding: const EdgeInsets.symmetric(
          horizontal: MarkoSpacing.md,
          vertical: MarkoSpacing.sm,
        ),
        child: Wrap(
          spacing: MarkoSpacing.sm,
          runSpacing: MarkoSpacing.xs,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              context.localized(
                ru: 'Выбрано $selectedCount',
                uk: 'Вибрано $selectedCount',
              ),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            FilledButton(
              onPressed: busy || sessionExpired ? null : onAccept,
              child: Text(context.localized(ru: 'Принять', uk: 'Прийняти')),
            ),
            OutlinedButton(
              onPressed: busy || sessionExpired ? null : onReject,
              child: Text(context.localized(ru: 'Отклонить', uk: 'Відхилити')),
            ),
            TextButton(
              onPressed: busy ? null : onClear,
              child: Text(context.localized(ru: 'Снять', uk: 'Зняти')),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecommendationTable extends StatelessWidget {
  const _RecommendationTable({
    required this.items,
    required this.selectedIds,
    required this.focusedId,
    required this.detailId,
    required this.onFocused,
    required this.onOpen,
    required this.onToggle,
    required this.canAdministerWorkspace,
    required this.onOpenDeepLink,
  });

  final List<PricingRecommendation> items;
  final Set<String> selectedIds;
  final String focusedId;
  final String? detailId;
  final ValueChanged<String> onFocused;
  final ValueChanged<String> onOpen;
  final ValueChanged<String> onToggle;
  final bool canAdministerWorkspace;
  final ValueChanged<String>? onOpenDeepLink;

  @override
  Widget build(BuildContext context) {
    final detail = items.where((item) => item.id == detailId).firstOrNull;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          flex: 7,
          child: MarkoPanel(
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                _tableHeader(context),
                for (final item in items)
                  _RecommendationTableRow(
                    item: item,
                    selected: selectedIds.contains(item.id),
                    focused: item.id == focusedId,
                    onFocused: () => onFocused(item.id),
                    onOpen: () => onOpen(item.id),
                    onToggle: () => onToggle(item.id),
                  ),
              ],
            ),
          ),
        ),
        if (detail != null) ...[
          const SizedBox(width: MarkoSpacing.md),
          Expanded(
            flex: 5,
            child: _RecommendationCard(
              recommendation: detail,
              canAdministerWorkspace: canAdministerWorkspace,
              initiallyExpanded: true,
              onOpenDeepLink: onOpenDeepLink,
            ),
          ),
        ],
      ],
    );
  }

  Widget _tableHeader(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final style = Theme.of(context).textTheme.labelMedium;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpacing.sm,
        vertical: MarkoSpacing.sm,
      ),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: colors.border),
        ),
      ),
      child: Row(
        children: [
          const SizedBox(width: 36),
          Expanded(
            flex: 4,
            child: Text(
              context.localized(ru: 'Товар', uk: 'Товар'),
              style: style,
            ),
          ),
          Expanded(
            child: Text(
              context.localized(ru: 'Текущая', uk: 'Поточна'),
              style: style,
              textAlign: TextAlign.end,
            ),
          ),
          Expanded(
            child: Text(
              context.localized(ru: 'Рекомендуемая', uk: 'Рекомендована'),
              style: style,
              textAlign: TextAlign.end,
            ),
          ),
          Expanded(
            child: Text('Δ', style: style, textAlign: TextAlign.end),
          ),
          Expanded(
            child: Text('Δ%', style: style, textAlign: TextAlign.end),
          ),
          Expanded(
            child: Text(
              context.localized(ru: 'Действие', uk: 'Дія'),
              style: style,
            ),
          ),
          SizedBox(
            width: 72,
            child: Text(
              context.localized(ru: 'Данные', uk: 'Дані'),
              style: style,
              textAlign: TextAlign.end,
            ),
          ),
        ],
      ),
    );
  }
}

class _RecommendationTableRow extends StatelessWidget {
  const _RecommendationTableRow({
    required this.item,
    required this.selected,
    required this.focused,
    required this.onFocused,
    required this.onOpen,
    required this.onToggle,
  });

  final PricingRecommendation item;
  final bool selected;
  final bool focused;
  final VoidCallback onFocused;
  final VoidCallback onOpen;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final moneyStyle = Theme.of(context).textTheme.bodyMedium?.copyWith(
      fontFeatures: const [FontFeature.tabularFigures()],
      fontWeight: FontWeight.w600,
    );
    final target = item.recommendedPrice ?? item.advisoryRecommendedPrice;
    final delta = item.absoluteRecommendedChange;
    final percent = item.percentageRecommendedChange;
    return Material(
      color: focused ? colors.brandSoft : Colors.transparent,
      child: InkWell(
        onTap: () {
          onFocused();
          onOpen();
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: MarkoSpacing.sm,
            vertical: 10,
          ),
          child: Row(
            children: [
              SizedBox(
                width: 36,
                child: Checkbox(value: selected, onChanged: (_) => onToggle()),
              ),
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      'SKU ${item.sku}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Text(
                  _recommendationMoney(item, item.currentPrice),
                  style: moneyStyle,
                  textAlign: TextAlign.end,
                ),
              ),
              Expanded(
                child: Text(
                  target == null ? '—' : _recommendationMoney(item, target),
                  style: moneyStyle,
                  textAlign: TextAlign.end,
                ),
              ),
              Expanded(
                child: Text(
                  delta == null ? '—' : _recommendationMoney(item, delta),
                  style: moneyStyle,
                  textAlign: TextAlign.end,
                ),
              ),
              Expanded(
                child: Text(
                  percent == null
                      ? '—'
                      : '${(percent * 100).toStringAsFixed(1)}%',
                  style: moneyStyle,
                  textAlign: TextAlign.end,
                ),
              ),
              Expanded(
                child: Text(
                  _actionLabel(context, item.action),
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ),
              SizedBox(
                width: 72,
                child: Text(
                  '${(item.confidence * 100).round()}%',
                  style: moneyStyle,
                  textAlign: TextAlign.end,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
