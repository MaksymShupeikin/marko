part of '../recommendations_page.dart';

class RecommendationEvidenceDetails extends StatelessWidget {
  const RecommendationEvidenceDetails({required this.evidence, super.key});

  final RecommendationEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.bodySmall;
    final extracted = evidence.extractedOeNorms.isEmpty
        ? '—'
        : evidence.extractedOeNorms.join(', ');
    final calibrationExclusions = evidence.calibrationExclusionCodes.isEmpty
        ? '—'
        : evidence.calibrationExclusionCodes.join(', ');
    final reenriched = evidence.oeReenrichedAt == null
        ? '—'
        : formatLocalDateTime(evidence.oeReenrichedAt!);
    final availability = switch (evidence.isAvailable) {
      true => context.localized(ru: 'в наличии', uk: 'у наявності'),
      false => context.localized(ru: 'нет в наличии', uk: 'немає в наявності'),
      null => context.localized(ru: 'неизвестно', uk: 'невідомо'),
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: MarkoTheme.of(context).surfaceMuted.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(7),
      ),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'OE: status=${evidence.oeVerificationStatus} · '
              'search=${_emptyAsDash(evidence.searchOeNorm)} · '
              'extracted=$extracted · '
              'verified=${evidence.verifiedMatchedOeNorm ?? '—'} · '
              'identity=${evidence.comparisonIdentityKey ?? '—'}',
              style: style,
            ),
            Text(
              '${context.localized(ru: 'Provenance', uk: 'Походження')}: '
              'seller=${_emptyAsDash(evidence.sellerId)} · '
              'OE extractor=${_emptyAsDash(evidence.oeExtractorVersion)} · '
              'source method=${_emptyAsDash(evidence.sourceConfidenceMethodVersion)} · '
              're-enriched=$reenriched · '
              'error=${evidence.oeReenrichmentErrorCode ?? '—'}',
              style: style,
            ),
            Text(
              'OE evidence: ${_safeJson(evidence.oeEvidenceSummary)}',
              style: style,
            ),
            Text(
              '${context.localized(ru: 'Флаги', uk: 'Прапорці')}: '
              '$availability · used=${evidence.isUsed} · '
              'KEMP=${evidence.isKemp} · owned=${evidence.isOwned}',
              style: style,
            ),
            Text(
              'Hard gate: ${evidence.comparabilityHardGateResult} · '
              'calibration exclusions=$calibrationExclusions',
              style: style,
            ),
            Text(
              'Source factors: ${_safeJson(evidence.sourceConfidenceFactors)} · '
              'outcomes=${_safeJson(evidence.offerOutcomeCounts)}',
              style: style,
            ),
            Text(
              'Policy: id=${evidence.comparabilityPolicyId ?? '—'} · '
              'hash=${evidence.comparabilityPolicyHash ?? '—'}',
              style: style,
            ),
          ],
        ),
      ),
    );
  }
}

String _emptyAsDash(String value) => value.trim().isEmpty ? '—' : value;

String _safeJson(Object value) {
  try {
    return jsonEncode(value);
  } on Object {
    return '<unavailable>';
  }
}
