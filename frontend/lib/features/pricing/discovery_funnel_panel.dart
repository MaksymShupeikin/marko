import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import 'discovery_funnel_models.dart';
import 'operations_api.dart';

class DiscoveryFunnelPanel extends ConsumerStatefulWidget {
  const DiscoveryFunnelPanel({super.key});

  @override
  ConsumerState<DiscoveryFunnelPanel> createState() =>
      _DiscoveryFunnelPanelState();
}

class _DiscoveryFunnelPanelState extends ConsumerState<DiscoveryFunnelPanel> {
  DiscoveryFunnelSnapshot? _snapshot;
  bool _loading = false;
  String? _error;

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final snapshot = await ref
          .read(operationsApiProvider)
          .getDiscoveryFunnel();
      if (!mounted) return;
      setState(() => _snapshot = snapshot);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return MarkoPanel(
      padding: EdgeInsets.zero,
      child: ExpansionTile(
        key: const ValueKey('discovery-funnel-panel'),
        onExpansionChanged: (expanded) {
          if (expanded && _snapshot == null && !_loading) {
            unawaited(_load());
          }
        },
        title: Text(
          context.localized(
            ru: 'Воронка discovery и потолки гейтов',
            uk: 'Воронка discovery та межі гейтів',
          ),
        ),
        subtitle: Text(
          context.localized(
            ru: 'Показывает, где кандидаты перестают быть ценовым доказательством.',
            uk: 'Показує, де кандидати перестають бути ціновим доказом.',
          ),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        children: [
          if (_loading) const LinearProgressIndicator(),
          if (_error != null) ...[
            MarkoInlineMessage(
              message: _error!,
              tone: MarkoMessageTone.error,
              action: TextButton(
                onPressed: _load,
                child: Text(
                  context.localized(ru: 'Повторить', uk: 'Повторити'),
                ),
              ),
            ),
          ],
          if (_snapshot case final snapshot?) _FunnelBody(snapshot: snapshot),
        ],
      ),
    );
  }
}

class _FunnelBody extends StatelessWidget {
  const _FunnelBody({required this.snapshot});

  final DiscoveryFunnelSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final visibleGates = snapshot.gates.entries
        .where((entry) => entry.value.reached > 0)
        .toList(growable: false);
    final coverage = snapshot.retrievalCoverageRatio;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 12),
        Wrap(
          spacing: 14,
          runSpacing: 6,
          children: [
            Text(
              context.localized(
                ru: 'Запусков: ${snapshot.sampledRuns}',
                uk: 'Запусків: ${snapshot.sampledRuns}',
              ),
            ),
            Text(
              context.localized(
                ru: 'Кандидатов: ${snapshot.totalCandidates}',
                uk: 'Кандидатів: ${snapshot.totalCandidates}',
              ),
            ),
            if (coverage != null)
              Text(
                context.localized(
                  ru: 'Получено от заявленного: ${(coverage * 100).toStringAsFixed(1)}%',
                  uk: 'Отримано від заявленого: ${(coverage * 100).toStringAsFixed(1)}%',
                ),
              ),
          ],
        ),
        if (snapshot.sampledRuns == 0) ...[
          const SizedBox(height: 10),
          Text(
            context.localized(
              ru: 'Завершённых discovery-запусков пока нет.',
              uk: 'Завершених discovery-запусків поки немає.',
            ),
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: colors.muted),
          ),
        ] else ...[
          const SizedBox(height: 16),
          Text(
            context.localized(
              ru: 'Потолок разблокировки — это текущие EVIDENCE плюс кандидаты, остановленные одним гейтом. Из-за остановки на первом отказе это верхняя граница, а не прогноз.',
              uk: 'Межа розблокування — це поточні EVIDENCE плюс кандидати, зупинені одним гейтом. Через зупинку на першій відмові це верхня межа, а не прогноз.',
            ),
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
          const SizedBox(height: 12),
          ...visibleGates.map(
            (entry) => _GateRow(name: entry.key, metric: entry.value),
          ),
          if (snapshot.categories.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(
              context.localized(ru: 'Категории', uk: 'Категорії'),
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 7),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: snapshot.categories
                  .take(8)
                  .map(
                    (category) => Chip(
                      label: Text(
                        '${category.category}: ${category.totalCandidates}',
                      ),
                    ),
                  )
                  .toList(growable: false),
            ),
          ],
        ],
        if (snapshot.correlationId case final correlationId?) ...[
          const SizedBox(height: 12),
          SelectableText(
            'Correlation ID: $correlationId',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
        ],
      ],
    );
  }
}

class _GateRow extends StatelessWidget {
  const _GateRow({required this.name, required this.metric});

  final String name;
  final DiscoveryGateMetric metric;

  @override
  Widget build(BuildContext context) {
    final ceiling = metric.singleGateUnlockUpperBoundRatio;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            spacing: 8,
            runSpacing: 3,
            children: [
              Text(_gateLabel(context, name)),
              Text(
                context.localized(
                  ru: 'дошли ${metric.reached} · остановлены ${metric.terminal} · потолок разблокировки ${_percent(ceiling)}',
                  uk: 'дійшли ${metric.reached} · зупинені ${metric.terminal} · межа розблокування ${_percent(ceiling)}',
                ),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          const SizedBox(height: 4),
          LinearProgressIndicator(value: ceiling),
        ],
      ),
    );
  }
}

String _percent(double? value) =>
    value == null ? '—' : '${(value * 100).toStringAsFixed(1)}%';

String _gateLabel(BuildContext context, String gate) => switch (gate) {
  'own_seller' => context.localized(
    ru: 'Исключение своих продавцов',
    uk: 'Виключення власних продавців',
  ),
  'dismantler_seller' => context.localized(
    ru: 'Исключение разборок',
    uk: 'Виключення розборок',
  ),
  'category_domain' => context.localized(
    ru: 'Категория товара',
    uk: 'Категорія товару',
  ),
  'condition' => context.localized(ru: 'Состояние', uk: 'Стан'),
  'remanufactured' => context.localized(
    ru: 'Восстановленный товар',
    uk: 'Відновлений товар',
  ),
  'oem_identity' => 'OEM identity',
  'oem_stuffing' => 'OEM stuffing',
  'variant' => context.localized(ru: 'Вариант', uk: 'Варіант'),
  'package' => context.localized(ru: 'Комплектность', uk: 'Комплектність'),
  'applicability' => context.localized(
    ru: 'Применяемость',
    uk: 'Застосовність',
  ),
  'tier_classification' => context.localized(
    ru: 'Классификация уровня',
    uk: 'Класифікація рівня',
  ),
  'own_brand' => context.localized(
    ru: 'Собственный бренд',
    uk: 'Власний бренд',
  ),
  'tier_known' => context.localized(
    ru: 'Известный уровень бренда',
    uk: 'Відомий рівень бренду',
  ),
  'premium_calibration' => context.localized(
    ru: 'Премиальная калибровка',
    uk: 'Преміальна калібровка',
  ),
  'price_anomaly' => context.localized(
    ru: 'Аномалия цены',
    uk: 'Аномалія ціни',
  ),
  _ => gate,
};
