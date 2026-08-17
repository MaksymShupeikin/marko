import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import 'pricing_api.dart';
import 'pricing_models.dart';

Future<PricingRunSummary?> showPricingDiscoveryReviewDialog({
  required BuildContext context,
  required PricingApi api,
  required PricingRunSummary run,
}) => showDialog<PricingRunSummary>(
  context: context,
  barrierDismissible: false,
  builder: (_) => _PricingDiscoveryReviewDialog(api: api, run: run),
);

class _PricingDiscoveryReviewDialog extends StatefulWidget {
  const _PricingDiscoveryReviewDialog({required this.api, required this.run});

  final PricingApi api;
  final PricingRunSummary run;

  @override
  State<_PricingDiscoveryReviewDialog> createState() =>
      _PricingDiscoveryReviewDialogState();
}

class _PricingDiscoveryReviewDialogState
    extends State<_PricingDiscoveryReviewDialog> {
  PricingDiscoveryReviewQueue? _queue;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      final queue = await widget.api.getDiscoveryReviews(widget.run.id);
      if (mounted) setState(() => _queue = queue);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _decide(
    PricingDiscoveryReviewOffer offer,
    String decision,
  ) async {
    final reason = await _decisionReason(decision);
    if (reason == null || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.decideDiscoveryOffer(
        runId: widget.run.id,
        offer: offer,
        decision: decision,
        reason: reason,
      );
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<String?> _decisionReason(String decision) async {
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          decision == 'APPROVE' ? 'Причина approve' : 'Причина reject',
        ),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 2000,
          maxLines: 4,
          decoration: const InputDecoration(
            hintText: 'Зафиксируйте признаки совпадения или причину отказа',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () {
              final value = controller.text.trim();
              if (value.isNotEmpty) Navigator.of(dialogContext).pop(value);
            },
            child: const Text('Сохранить решение'),
          ),
        ],
      ),
    );
    controller.dispose();
    return result;
  }

  Future<void> _resume() async {
    final queue = _queue;
    if (queue == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final run = await widget.api.resumeRun(
        widget.run.id,
        queue.reviewSnapshotHash,
      );
      if (mounted) Navigator.of(context).pop(run);
    } catch (error) {
      if (mounted) {
        setState(() => _error = error);
        await _load();
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final queue = _queue;
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 920, maxHeight: 780),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                context.localized(
                  ru: 'Проверка найденных no-OEM предложений',
                  uk: 'Перевірка знайдених no-OEM пропозицій',
                ),
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 6),
              Text(
                context.localized(
                  ru: 'Luna проверяет сопоставимость и коммерческую честность карточки: цену-заглушку, «от», залог, опт, б/у, комплектность и подозрительно одинокий минимум. Luna не назначает цену. Формула системы — минимальная одобренная цена минус 5%.',
                  uk: 'Luna перевіряє зіставність і комерційну чесність картки: ціну-заглушку, «від», заставу, опт, вживаний стан, комплектність і підозріло поодинокий мінімум. Luna не призначає ціну. Формула системи — мінімальна схвалена ціна мінус 5%.',
                ),
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: colors.muted),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                MarkoInlineMessage(
                  message: _error.toString(),
                  tone: MarkoMessageTone.error,
                ),
              ],
              const SizedBox(height: 12),
              Expanded(
                child: queue == null
                    ? const Center(child: CircularProgressIndicator())
                    : queue.items.isEmpty
                    // Пауза без строк — законное состояние: проверка Luna ещё
                    // не записана или совпадений нет вовсе. Без подсказки
                    // оператор видит пустоту и не знает, что жать.
                    ? Center(
                        child: Text(
                          context.localized(
                            ru:
                                'Одобрять нечего: у этой паузы нет записанных '
                                'предложений. Нажмите «Продолжить расчёт» — '
                                'позиции без одобренных предложений получат '
                                'вердикт «недостаточно данных».',
                            uk:
                                'Схвалювати нічого: у цієї паузи немає '
                                'записаних пропозицій. Натисніть «Продовжити '
                                'розрахунок» — позиції без схвалених '
                                'пропозицій отримають вердикт «недостатньо '
                                'даних».',
                          ),
                          textAlign: TextAlign.center,
                          style: Theme.of(
                            context,
                          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                        ),
                      )
                    : ListView.separated(
                        itemCount: queue.items.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 10),
                        itemBuilder: (context, index) {
                          final offer = queue.items[index];
                          return MarkoPanel(
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  offer.sourceName,
                                  style: Theme.of(context).textTheme.titleSmall,
                                ),
                                Text(
                                  [
                                    'SKU ${offer.sourceSku}',
                                    if (offer.sourceInternalCode != null)
                                      'KEMP ${offer.sourceInternalCode}',
                                  ].join(' · '),
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                                const Divider(height: 20),
                                Text(offer.candidateTitle),
                                Text(
                                  '${offer.sellerName} · ${offer.price.toFixed(2)} ${offer.currency}',
                                  style: Theme.of(context).textTheme.titleSmall,
                                ),
                                TextButton.icon(
                                  onPressed: () => launchUrl(
                                    Uri.parse(offer.candidateUrl),
                                    mode: LaunchMode.externalApplication,
                                  ),
                                  icon: const Icon(Icons.open_in_new_rounded),
                                  label: const Text('Prom URL'),
                                ),
                                Text(
                                  'Luna: ${offer.lunaVerdict} — ${offer.lunaRationale}',
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                                if (offer.conflicts.isNotEmpty)
                                  Text(
                                    'Конфликты: ${offer.conflicts.length}',
                                    style: Theme.of(context).textTheme.bodySmall
                                        ?.copyWith(color: colors.negative),
                                  ),
                                const SizedBox(height: 8),
                                if (offer.decision != null)
                                  Text(
                                    offer.decision == 'APPROVE'
                                        ? 'APPROVE — допущено только в этот run'
                                        : 'REJECT — исключено',
                                    style: Theme.of(context).textTheme.bodySmall
                                        ?.copyWith(fontWeight: FontWeight.w700),
                                  )
                                else
                                  Wrap(
                                    spacing: 8,
                                    children: [
                                      FilledButton(
                                        onPressed:
                                            _busy ||
                                                offer.lunaVerdict != 'MATCH' ||
                                                offer.conflicts.isNotEmpty ||
                                                offer.isAvailable != true
                                            ? null
                                            : () => _decide(offer, 'APPROVE'),
                                        child: const Text('Approve'),
                                      ),
                                      OutlinedButton(
                                        onPressed: _busy
                                            ? null
                                            : () => _decide(offer, 'REJECT'),
                                        child: const Text('Reject'),
                                      ),
                                    ],
                                  ),
                              ],
                            ),
                          );
                        },
                      ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _busy ? null : () => Navigator.of(context).pop(),
                    child: Text(
                      context.localized(ru: 'Закрыть', uk: 'Закрити'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.icon(
                    key: const ValueKey('pricing-discovery-resume'),
                    onPressed: _busy || queue == null ? null : _resume,
                    icon: const Icon(Icons.play_arrow_rounded),
                    label: Text(
                      context.localized(
                        ru: 'Продолжить расчёт',
                        uk: 'Продовжити розрахунок',
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
