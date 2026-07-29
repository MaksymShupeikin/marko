import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_theme.dart';
import '../../core/presentation_formatters.dart';
import 'fitment_models.dart';

typedef CandidateReviewCallback =
    Future<bool> Function({
      required String decision,
      required String reasonCode,
      String? comment,
      Map<String, String> evidenceVerdicts,
    });
typedef SellerReviewCallback =
    Future<bool> Function({required String relation, required String reason});

class FitmentCandidateTile extends StatelessWidget {
  const FitmentCandidateTile({
    required this.candidate,
    required this.isSubmitting,
    required this.onReview,
    this.onSellerReview,
    super.key,
  });

  final FitmentCandidate candidate;
  final bool isSubmitting;
  final CandidateReviewCallback onReview;
  final SellerReviewCallback? onSellerReview;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final rejected = candidate.compatibilityStatus == 'not_compatible';
    final confirmed = candidate.compatibilityStatus == 'confirmed_compatible';
    final statusColor = rejected
        ? colors.negative
        : confirmed
        ? colors.positive
        : colors.warning;
    final uri = Uri.tryParse(candidate.url);
    final canOpen =
        uri != null &&
        (uri.scheme == 'http' || uri.scheme == 'https') &&
        uri.host.isNotEmpty;
    return Container(
      margin: const EdgeInsets.only(bottom: 9),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${candidate.sellerName} · ${candidate.brand ?? 'brand unknown'}',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      candidate.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              _CandidatePrice(candidate: candidate, statusColor: statusColor),
            ],
          ),
          const SizedBox(height: 7),
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              Text(
                'score ${(candidate.compatibilityProbability * 100).toStringAsFixed(1)}%',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'coverage ${(candidate.coverage * 100).toStringAsFixed(0)}%',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'позиция ${candidate.positionLabel.isEmpty ? 'unknown' : candidate.positionLabel}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'tier ${candidate.tier}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'seller ${candidate.sellerRelation}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'sources ${candidate.independentSourceCount}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                candidate.authoritativeConfirmation
                    ? 'authoritative ✓'
                    : 'authority missing',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: candidate.authoritativeConfirmation
                      ? colors.positive
                      : colors.warning,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            candidate.priceEligible
                ? 'Цена допущена · W=${candidate.competitorWeight.toStringAsFixed(4)}'
                : 'Цена не допущена: ${summarizeLimited(candidate.priceReasonCodes, limit: 3, separator: ', ', overflowLabel: (hidden) => 'и ещё $hidden')}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: candidate.priceEligible ? colors.positive : colors.warning,
            ),
          ),
          if (candidate.hardRejections.isNotEmpty)
            Text(
              'Hard reject: ${candidate.hardRejections.join(', ')}',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.negative),
            ),
          if (candidate.missingCriticalFields.isNotEmpty)
            Text(
              'Не хватает: ${candidate.missingCriticalFields.join(', ')}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          if (candidate.reasonCodes.any((code) => code.contains('CONFLICT')))
            Text(
              'Конфликт evidence: ${candidate.reasonCodes.where((code) => code.contains('CONFLICT')).join(', ')}',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.negative),
            ),
          if (candidate.evidence.isNotEmpty)
            _EvidenceDisclosure(evidence: candidate.evidence),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              if (canOpen)
                TextButton.icon(
                  onPressed: () =>
                      launchUrl(uri, mode: LaunchMode.externalApplication),
                  icon: const Icon(Icons.open_in_new_rounded, size: 16),
                  label: const Text('Карточка'),
                ),
              OutlinedButton(
                onPressed: isSubmitting
                    ? null
                    : () => _review(
                        context,
                        decision: 'mark_candidate_compatible',
                        initialReason: 'human_fitment_confirmed',
                      ),
                child: const Text('Подходит'),
              ),
              OutlinedButton(
                onPressed: isSubmitting
                    ? null
                    : () => _review(
                        context,
                        decision: 'mark_candidate_incompatible',
                        initialReason: 'incorrect_cross',
                      ),
                child: const Text('Не подходит'),
              ),
              TextButton(
                onPressed: isSubmitting
                    ? null
                    : () => _review(
                        context,
                        decision: 'request_additional_check',
                        initialReason: 'additional_evidence_required',
                      ),
                child: const Text('Нужна проверка'),
              ),
              if (onSellerReview != null) ...[
                TextButton(
                  onPressed: isSubmitting
                      ? null
                      : () => _markSeller(context, relation: 'own'),
                  child: const Text('Наш магазин'),
                ),
                TextButton(
                  onPressed: isSubmitting
                      ? null
                      : () => _markSeller(context, relation: 'related'),
                  child: const Text('Связанный продавец'),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _review(
    BuildContext context, {
    required String decision,
    required String initialReason,
  }) async {
    final result = await showDialog<_CandidateReviewData>(
      context: context,
      builder: (dialogContext) => _CandidateReviewDialog(
        evidence: candidate.evidence,
        initialReason: initialReason,
      ),
    );
    if (result != null && context.mounted) {
      await onReview(
        decision: decision,
        reasonCode: result.reason,
        comment: result.comment,
        evidenceVerdicts: result.evidenceVerdicts,
      );
    }
  }

  Future<void> _markSeller(
    BuildContext context, {
    required String relation,
  }) async {
    final controller = TextEditingController();
    final reason = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          relation == 'own'
              ? 'Пометить как наш магазин'
              : 'Пометить как связанного',
        ),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: 'Проверенный идентификатор / причина',
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
              if (value.length >= 3) Navigator.of(dialogContext).pop(value);
            },
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (reason != null && context.mounted) {
      await onSellerReview?.call(relation: relation, reason: reason);
    }
  }
}

class _CandidatePrice extends StatelessWidget {
  const _CandidatePrice({required this.candidate, required this.statusColor});

  final FitmentCandidate candidate;
  final Color statusColor;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (candidate.referencePrice != null)
          Text(
            '${candidate.referencePrice!.toStringAsFixed(2)} ${candidate.currency}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              decoration: TextDecoration.lineThrough,
            ),
          ),
        Text(
          '${candidate.price.toStringAsFixed(2)} ${candidate.currency}',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        if (candidate.normalizedUnitPrice != null)
          Text(
            candidate.priceUnitCertainty == null
                ? '${candidate.normalizedUnitPrice!.toStringAsFixed(2)} / шт · точность не измерена'
                : '${candidate.normalizedUnitPrice!.toStringAsFixed(2)} / шт · ${(candidate.priceUnitCertainty! * 100).toStringAsFixed(0)}%',
            style: Theme.of(context).textTheme.bodySmall,
          )
        else
          Text(
            'unit ${candidate.priceUnitStatus}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        Text(
          candidate.statusLabel,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: statusColor,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _CandidateReviewData {
  const _CandidateReviewData({
    required this.reason,
    required this.comment,
    required this.evidenceVerdicts,
  });

  final String reason;
  final String comment;
  final Map<String, String> evidenceVerdicts;
}

class _CandidateReviewDialog extends StatefulWidget {
  const _CandidateReviewDialog({
    required this.evidence,
    required this.initialReason,
  });

  final List<FitmentEvidence> evidence;
  final String initialReason;

  @override
  State<_CandidateReviewDialog> createState() => _CandidateReviewDialogState();
}

class _CandidateReviewDialogState extends State<_CandidateReviewDialog> {
  final _comment = TextEditingController();
  final Map<String, String> _verdicts = {};
  late String _reason = widget.initialReason;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const reasons = {
      'human_fitment_confirmed': 'Совместимость подтверждена',
      'incorrect_oe': 'Неверный OE',
      'incorrect_cross': 'Неверный кросс',
      'wrong_side': 'Неверная сторона',
      'wrong_axle': 'Неверная ось',
      'wrong_generation': 'Неверное поколение',
      'wrong_quantity': 'Неверное количество',
      'source_error': 'Ошибка источника',
      'additional_evidence_required': 'Нужно больше evidence',
    };
    return AlertDialog(
      title: const Text('Сохранить решение'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: reasons.containsKey(_reason)
                    ? _reason
                    : reasons.keys.first,
                items: reasons.entries
                    .map(
                      (entry) => DropdownMenuItem(
                        value: entry.key,
                        child: Text(entry.value),
                      ),
                    )
                    .toList(growable: false),
                onChanged: (value) =>
                    setState(() => _reason = value ?? _reason),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _comment,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Комментарий / проверенный источник',
                ),
              ),
              if (widget.evidence.isNotEmpty) ...[
                const SizedBox(height: 12),
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text('Evidence labels (не выбрано = не обучать)'),
                ),
                ...widget.evidence.map(
                  (evidence) => DropdownButtonFormField<String>(
                    initialValue: _verdicts[evidence.id] ?? 'unlabeled',
                    decoration: InputDecoration(
                      labelText: '${evidence.feature} · ${evidence.sourceType}',
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: 'unlabeled',
                        child: Text('Не размечать'),
                      ),
                      DropdownMenuItem(
                        value: 'confirmed',
                        child: Text('Доказательство верно'),
                      ),
                      DropdownMenuItem(
                        value: 'rejected',
                        child: Text('Доказательство ошибочно'),
                      ),
                    ],
                    onChanged: (value) => setState(() {
                      if (value == null || value == 'unlabeled') {
                        _verdicts.remove(evidence.id);
                      } else {
                        _verdicts[evidence.id] = value;
                      }
                    }),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(
            _CandidateReviewData(
              reason: _reason,
              comment: _comment.text.trim(),
              evidenceVerdicts: Map.unmodifiable(_verdicts),
            ),
          ),
          child: const Text('Сохранить'),
        ),
      ],
    );
  }
}

class _EvidenceDisclosure extends StatelessWidget {
  const _EvidenceDisclosure({required this.evidence});

  final List<FitmentEvidence> evidence;

  @override
  Widget build(BuildContext context) {
    final groups = evidence.map((item) => item.correlationGroup).toSet().length;
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(bottom: 6),
      dense: true,
      title: Text(
        'Evidence: ${evidence.length} claims · $groups provenance groups',
        style: Theme.of(context).textTheme.bodySmall,
      ),
      children: evidence
          .map((item) => _EvidenceRow(evidence: item))
          .toList(growable: false),
    );
  }
}

class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow({required this.evidence});

  final FitmentEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final uri = Uri.tryParse(evidence.sourceUrl ?? '');
    final canOpen =
        uri != null &&
        (uri.scheme == 'http' || uri.scheme == 'https') &&
        uri.host.isNotEmpty;
    final color = evidence.contradicts ? colors.negative : colors.muted;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            evidence.contradicts
                ? Icons.warning_amber_rounded
                : Icons.fact_check_outlined,
            size: 16,
            color: color,
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${evidence.feature} · ${evidence.sourceType} · Tier ${evidence.sourceTier} · W=${evidence.effectiveWeight.toStringAsFixed(3)}',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: color),
                ),
                if (evidence.rawFragment?.trim().isNotEmpty == true)
                  Text(
                    evidence.rawFragment!.trim(),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
          ),
          if (canOpen)
            IconButton(
              tooltip: 'Открыть источник',
              visualDensity: VisualDensity.compact,
              onPressed: () =>
                  launchUrl(uri, mode: LaunchMode.externalApplication),
              icon: const Icon(Icons.open_in_new_rounded, size: 16),
            ),
        ],
      ),
    );
  }
}
