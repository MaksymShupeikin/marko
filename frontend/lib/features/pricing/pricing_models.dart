import '../../core/presentation_formatters.dart';
import 'pricing_reason_labels.dart';

double? _decimal(dynamic value) =>
    value == null ? null : double.tryParse(value.toString());

int _requiredInt(Map<String, dynamic> json, String field) {
  final value = json[field];
  if (value is num) return value.toInt();
  throw FormatException('Pricing response requires numeric $field');
}

List<String> _requiredStringList(Map<String, dynamic> json, String field) {
  final value = json[field];
  if (value is! List<dynamic>) {
    throw FormatException('Pricing response requires list $field');
  }
  return value.map((item) => item.toString()).toList(growable: false);
}

class PricingRecommendation {
  PricingRecommendation({
    required this.id,
    required this.runId,
    required this.catalogSnapshotId,
    required this.catalogItemId,
    required this.sku,
    required this.oe,
    required this.name,
    required this.category,
    required this.stockStatus,
    required this.contextSnapshot,
    required this.calculationTrace,
    required this.action,
    required Object currentPrice,
    required Object? fairPrice,
    required Object? recommendedPrice,
    required Object? lowerBound,
    required Object? upperBound,
    required this.confidence,
    required this.confidenceGrade,
    required this.weakestFactor,
    required this.competitorCount,
    required this.rawCompetitorCount,
    required this.uniqueSellerCount,
    required this.cleanCompetitorCount,
    required this.targetMarketCount,
    required this.kempReferenceCount,
    required this.ownedStoreCount,
    required this.rejectedCount,
    required this.effectiveCompetitorCount,
    required this.dispersion,
    required this.outlierMethod,
    required this.outlierCount,
    required this.sensitivity,
    required this.actionGatesPassed,
    required this.automaticEligible,
    required this.verifiedSellerCount,
    required this.comparabilityPolicyId,
    required this.comparabilityPolicyHash,
    required this.hardGateTrace,
    required this.robustDiagnostic,
    required Object priorityScore,
    required this.priorityScoreType,
    required this.reviewPriority,
    required Object? absoluteRecommendedChange,
    required this.percentageRecommendedChange,
    required this.reasonCodes,
    required this.factorScores,
    required this.excludedObservations,
    required this.policyVersion,
    required this.parserVersion,
    required this.classifierVersion,
    required this.coefficientVersion,
    required this.calibrationDatasetHash,
    required this.currency,
    required Object priceTick,
    required this.priceTickScale,
    required this.priceTickVersion,
    required this.computedAt,
  }) : currentPrice = DecimalValue.from(currentPrice),
       fairPrice = DecimalValue.tryParse(fairPrice),
       recommendedPrice = DecimalValue.tryParse(recommendedPrice),
       lowerBound = DecimalValue.tryParse(lowerBound),
       upperBound = DecimalValue.tryParse(upperBound),
       priorityScore = DecimalValue.from(priorityScore),
       absoluteRecommendedChange = DecimalValue.tryParse(
         absoluteRecommendedChange,
       ),
       priceTick = DecimalValue.from(priceTick);

  factory PricingRecommendation.fromJson(Map<String, dynamic> json) {
    final rawFactors = json['factor_scores'] as Map<String, dynamic>? ?? {};
    final rawPriceTick = json['price_tick'];
    final priceTickVersion = json['price_tick_version']?.toString() ?? 'legacy';
    final competitorCount = _requiredInt(json, 'competitor_count');
    final reasonCodes = _requiredStringList(json, 'reason_codes');
    return PricingRecommendation(
      id: json['id'] as String,
      runId: json['pricing_run_id'] as String,
      catalogSnapshotId:
          json['catalog_snapshot_id']?.toString() ?? 'legacy-snapshot',
      catalogItemId: json['catalog_item_id'] as String,
      sku: json['sku'] as String,
      oe: json['oe_norm'] as String,
      name: json['name'] as String,
      category: json['category'] as String,
      stockStatus: json['stock_status'] as String,
      contextSnapshot:
          json['context_snapshot'] as Map<String, dynamic>? ?? const {},
      calculationTrace:
          json['calculation_trace'] as Map<String, dynamic>? ?? const {},
      action: json['action'] as String,
      currentPrice: json['current_price'] ?? 0,
      fairPrice: json['fair_price'],
      recommendedPrice: json['recommended_price'],
      lowerBound: json['lower_bound'],
      upperBound: json['upper_bound'],
      confidence: _decimal(json['confidence']) ?? 0,
      confidenceGrade: json['confidence_grade'] as String,
      weakestFactor: json['weakest_factor'] as String?,
      competitorCount: competitorCount,
      rawCompetitorCount:
          (json['raw_competitor_count'] as num?)?.toInt() ?? competitorCount,
      uniqueSellerCount:
          (json['unique_seller_count'] as num?)?.toInt() ?? competitorCount,
      cleanCompetitorCount:
          (json['clean_competitor_count'] as num?)?.toInt() ?? competitorCount,
      targetMarketCount:
          (json['target_market_count'] as num?)?.toInt() ??
          (json['clean_competitor_count'] as num?)?.toInt() ??
          0,
      kempReferenceCount: (json['kemp_reference_count'] as num?)?.toInt() ?? 0,
      ownedStoreCount: (json['owned_store_count'] as num?)?.toInt() ?? 0,
      rejectedCount: (json['rejected_count'] as num?)?.toInt() ?? 0,
      effectiveCompetitorCount:
          _decimal(json['effective_competitor_count']) ??
          competitorCount.toDouble(),
      dispersion: _decimal(json['dispersion']),
      outlierMethod: json['outlier_method']?.toString() ?? 'none',
      outlierCount: (json['outlier_count'] as num?)?.toInt() ?? 0,
      sensitivity: _decimal(json['sensitivity']),
      actionGatesPassed: json['action_gates_passed'] as bool? ?? false,
      automaticEligible: json['automatic_eligible'] as bool? ?? false,
      verifiedSellerCount:
          (json['verified_seller_count'] as num?)?.toInt() ?? 0,
      comparabilityPolicyId: json['comparability_policy_id']?.toString(),
      comparabilityPolicyHash: json['comparability_policy_hash']?.toString(),
      hardGateTrace:
          json['hard_gate_trace'] as Map<String, dynamic>? ?? const {},
      robustDiagnostic: json['robust_diagnostic'] as Map<String, dynamic>?,
      priorityScore: json['priority_score'] ?? 0,
      priorityScoreType: json['priority_score_type'] as String,
      reviewPriority: _decimal(json['review_priority']) ?? 0,
      absoluteRecommendedChange: json['absolute_recommended_change'],
      percentageRecommendedChange: _decimal(
        json['percentage_recommended_change'],
      ),
      reasonCodes: reasonCodes,
      factorScores: rawFactors.map(
        (key, value) => MapEntry(key, _decimal(value) ?? 0),
      ),
      excludedObservations:
          (json['excluded_observations'] as List<dynamic>? ?? const [])
              .whereType<Map<String, dynamic>>()
              .toList(growable: false),
      policyVersion: json['policy_version']?.toString() ?? 'legacy',
      parserVersion: json['parser_version']?.toString() ?? 'legacy',
      classifierVersion: json['classifier_version']?.toString() ?? 'legacy',
      coefficientVersion: json['coefficient_version']?.toString(),
      calibrationDatasetHash: json['calibration_dataset_hash']?.toString(),
      currency: json['currency']?.toString() ?? 'UAH',
      priceTick: rawPriceTick ?? 1,
      // PostgreSQL NUMERIC(14,4) serializes the integer tick as `1.0000`.
      // Its named contract, not storage padding, defines UI precision.
      priceTickScale: priceTickVersion == 'uah-integer-v1'
          ? 0
          : decimalScale(rawPriceTick, fallback: 0),
      priceTickVersion: priceTickVersion,
      computedAt: DateTime.parse(json['computed_at'] as String),
    );
  }

  final String id;
  final String runId;
  final String catalogSnapshotId;
  final String catalogItemId;
  final String sku;
  final String oe;
  final String name;
  final String category;
  final String stockStatus;
  final Map<String, dynamic> contextSnapshot;
  final Map<String, dynamic> calculationTrace;
  final String action;
  final DecimalValue currentPrice;
  final DecimalValue? fairPrice;
  final DecimalValue? recommendedPrice;
  final DecimalValue? lowerBound;
  final DecimalValue? upperBound;
  final double confidence;
  final String confidenceGrade;
  final String? weakestFactor;
  final int competitorCount;
  final int rawCompetitorCount;
  final int uniqueSellerCount;
  final int cleanCompetitorCount;
  final int targetMarketCount;
  final int kempReferenceCount;
  final int ownedStoreCount;
  final int rejectedCount;
  final double effectiveCompetitorCount;
  final double? dispersion;
  final String outlierMethod;
  final int outlierCount;
  final double? sensitivity;
  final bool actionGatesPassed;
  final bool automaticEligible;
  final int verifiedSellerCount;
  final String? comparabilityPolicyId;
  final String? comparabilityPolicyHash;
  final Map<String, dynamic> hardGateTrace;
  final Map<String, dynamic>? robustDiagnostic;
  final DecimalValue priorityScore;
  final String priorityScoreType;
  final double reviewPriority;
  final DecimalValue? absoluteRecommendedChange;
  final double? percentageRecommendedChange;
  final List<String> reasonCodes;
  final Map<String, double> factorScores;
  final List<Map<String, dynamic>> excludedObservations;
  final String policyVersion;
  final String parserVersion;
  final String classifierVersion;
  final String? coefficientVersion;
  final String? calibrationDatasetHash;
  final String currency;
  final DecimalValue priceTick;
  final int priceTickScale;
  final String priceTickVersion;
  final DateTime computedAt;

  Map<String, Map<String, dynamic>> get normalizedOffersById {
    final raw = calculationTrace['normalized_offers'];
    if (raw is! List) return const {};
    final result = <String, Map<String, dynamic>>{};
    for (final value in raw) {
      if (value is! Map<String, dynamic>) continue;
      final id = value['observation_id']?.toString();
      if (id != null && id.isNotEmpty) result[id] = value;
    }
    return result;
  }

  Map<String, dynamic>? get customerPricingPolicy {
    final raw = calculationTrace['customer_pricing_policy'];
    return raw is Map ? Map<String, dynamic>.from(raw) : null;
  }

  int get customerExcludedImplausibleCount =>
      int.tryParse(
        customerPricingPolicy?['excluded_implausible_count']?.toString() ?? '',
      ) ??
      0;

  DecimalValue? get customerPlausibilityFloor =>
      DecimalValue.tryParse(customerPricingPolicy?['plausibility_floor']);

  Map<String, dynamic>? get advisoryDecision {
    final raw = calculationTrace['advisory_decision'];
    return raw is Map ? Map<String, dynamic>.from(raw) : null;
  }

  String? get advisoryAction => advisoryDecision?['action']?.toString();

  DecimalValue? get advisoryRecommendedPrice =>
      DecimalValue.tryParse(advisoryDecision?['recommended_price']);

  DecimalValue? get advisoryMarketMinimum =>
      DecimalValue.tryParse(advisoryDecision?['minimum_comparable_price']);

  DecimalValue? get advisoryTargetBandLow =>
      DecimalValue.tryParse(advisoryDecision?['target_band_low']);

  DecimalValue? get advisoryTargetBandHigh =>
      DecimalValue.tryParse(advisoryDecision?['target_band_high']);

  bool get hasAdvisoryPrice =>
      advisoryDecision?['automatic_price_application'] == false &&
      advisoryRecommendedPrice != null &&
      {'RAISE', 'LOWER'}.contains(advisoryAction);

  bool get isRaise => action == 'RAISE';
  bool get isLower => action == 'LOWER';
  bool get needsReview =>
      action == 'MANUAL_REVIEW' || action == 'INSUFFICIENT_DATA';

  String get priorityLabel => switch (priorityScoreType) {
    'gross_uplift_opportunity' =>
      '${formatMoney(priorityScore, currency: currency, priceTick: priceTick, fractionDigits: priceTickScale)}/мес. с учётом confidence',
    'clearance_priority' =>
      '${formatMoney(priorityScore, currency: currency, priceTick: priceTick, fractionDigits: priceTickScale)} замороженного капитала',
    'retail_exposure_proxy' =>
      '${priorityScore.toStringAsFixed(2)} · stock exposure proxy',
    'gap_confidence_proxy' =>
      '${priorityScore.toStringAsFixed(3)} · gap/confidence proxy',
    _ => '—',
  };

  String get actionLabel => switch (action) {
    'RAISE' => 'Поднять цену',
    'LOWER' => 'Снизить цену',
    'HOLD' => 'Оставить',
    'MANUAL_REVIEW' => 'Проверить вручную',
    'INSUFFICIENT_DATA' => 'Мало данных',
    _ => action,
  };

  String get reasonSummary {
    if (reasonCodes.isEmpty) return 'Расчёт завершён';
    return summarizeLimited(
      reasonCodes.map(reasonLabel),
      limit: 2,
      separator: ' · ',
      overflowLabel: (hidden) => 'и ещё $hidden',
    );
  }

  static String reasonLabel(String code) => pricingReasonLabelRu(code);
}

class RecommendationActionCounts {
  const RecommendationActionCounts({
    this.raise = 0,
    this.lower = 0,
    this.review = 0,
    this.hold = 0,
  });

  factory RecommendationActionCounts.fromJson(Map<String, dynamic> json) {
    int count(String key) => (json[key] as num?)?.toInt() ?? 0;
    return RecommendationActionCounts(
      raise: count('raise'),
      lower: count('lower'),
      review: count('review'),
      hold: count('hold'),
    );
  }

  final int raise;
  final int lower;
  final int review;
  final int hold;
}

class RecommendationPage {
  const RecommendationPage({
    required this.items,
    required this.total,
    required this.runId,
    this.limit = 50,
    this.offset = 0,
    this.actionCounts = const RecommendationActionCounts(),
  });

  factory RecommendationPage.fromJson(Map<String, dynamic> json) {
    final rawCounts = json['action_counts'];
    if (rawCounts is! Map) {
      throw const FormatException('Recommendation page requires action_counts');
    }
    return RecommendationPage(
      items: (json['items'] as List<dynamic>)
          .map(
            (item) =>
                PricingRecommendation.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
      runId: json['run_id'] as String?,
      limit: (json['limit'] as num?)?.toInt() ?? 50,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
      actionCounts: RecommendationActionCounts.fromJson(
        Map<String, dynamic>.from(rawCounts),
      ),
    );
  }

  final List<PricingRecommendation> items;
  final int total;
  final String? runId;
  final int limit;
  final int offset;
  final RecommendationActionCounts actionCounts;

  bool get hasMore => offset + items.length < total;
}

class RecommendationReplay {
  const RecommendationReplay({
    required this.recommendationId,
    required this.contractVersion,
    required this.calculatedAt,
    required this.exactMatch,
    required this.mismatches,
    required this.replayed,
  });

  factory RecommendationReplay.fromJson(Map<String, dynamic> json) {
    return RecommendationReplay(
      recommendationId: json['recommendation_id'] as String,
      contractVersion: json['replay_contract_version'] as String,
      calculatedAt: DateTime.parse(json['calculated_at'] as String),
      exactMatch: json['exact_match'] as bool,
      mismatches: (json['mismatches'] as Map<String, dynamic>? ?? const {}).map(
        (key, value) => MapEntry(key, Map<String, dynamic>.from(value as Map)),
      ),
      replayed:
          json['replayed'] as Map<String, dynamic>? ??
          const <String, dynamic>{},
    );
  }

  final String recommendationId;
  final String contractVersion;
  final DateTime calculatedAt;
  final bool exactMatch;
  final Map<String, Map<String, dynamic>> mismatches;
  final Map<String, dynamic> replayed;
}

class ComparabilityReview {
  const ComparabilityReview({
    required this.reviewId,
    required this.marketObservationId,
    required this.inputHash,
    required this.verdict,
    required this.matchLevel,
    required this.confidence,
    required this.rationale,
    required this.dimensionFindings,
    required this.hardStopConflicts,
    required this.decisionSource,
    required this.status,
    required this.provider,
    required this.modelId,
    required this.promptVersion,
    required this.reviewedAt,
    required this.cacheHitReviewId,
    required this.imageUrls,
    required this.providerResponseId,
    required this.errorCode,
    required this.errorDetail,
    required this.feedbackCount,
    required this.latestFeedbackId,
    required this.latestFeedbackDecision,
    required this.latestFeedbackReason,
    required this.pricingEligible,
  });

  factory ComparabilityReview.fromJson(Map<String, dynamic> json) {
    return ComparabilityReview(
      reviewId: json['review_id']?.toString() ?? '',
      marketObservationId: json['market_observation_id']?.toString() ?? '',
      inputHash: json['input_hash']?.toString() ?? '',
      verdict: json['verdict']?.toString() ?? 'INSUFFICIENT_DATA',
      matchLevel: json['match_level']?.toString() ?? 'SUSPICIOUS',
      confidence: _decimal(json['confidence']) ?? 0,
      rationale: json['rationale']?.toString() ?? '',
      dimensionFindings:
          (json['dimension_findings'] as List<dynamic>? ?? const [])
              .whereType<Map>()
              .map(Map<String, dynamic>.from)
              .toList(growable: false),
      hardStopConflicts:
          (json['hard_stop_conflicts'] as List<dynamic>? ?? const [])
              .whereType<Map>()
              .map(Map<String, dynamic>.from)
              .toList(growable: false),
      decisionSource: json['decision_source']?.toString() ?? 'UNKNOWN',
      status: json['status']?.toString() ?? 'UNKNOWN',
      provider: json['provider']?.toString() ?? '',
      modelId: json['model_id']?.toString() ?? '',
      promptVersion: json['prompt_version']?.toString() ?? '',
      reviewedAt:
          DateTime.tryParse(json['reviewed_at']?.toString() ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
      cacheHitReviewId: json['cache_hit_review_id']?.toString(),
      imageUrls: (json['image_urls'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      providerResponseId: json['provider_response_id']?.toString(),
      errorCode: json['error_code']?.toString(),
      errorDetail: json['error_detail']?.toString(),
      feedbackCount: (json['feedback_count'] as num?)?.toInt() ?? 0,
      latestFeedbackId: json['latest_feedback_id']?.toString(),
      latestFeedbackDecision: json['latest_feedback_decision']?.toString(),
      latestFeedbackReason: json['latest_feedback_reason']?.toString(),
      pricingEligible: json['pricing_eligible'] as bool? ?? false,
    );
  }

  final String reviewId;
  final String marketObservationId;
  final String inputHash;
  final String verdict;
  final String matchLevel;
  final double confidence;
  final String rationale;
  final List<Map<String, dynamic>> dimensionFindings;
  final List<Map<String, dynamic>> hardStopConflicts;
  final String decisionSource;
  final String status;
  final String provider;
  final String modelId;
  final String promptVersion;
  final DateTime reviewedAt;
  final String? cacheHitReviewId;
  final List<String> imageUrls;
  final String? providerResponseId;
  final String? errorCode;
  final String? errorDetail;
  final int feedbackCount;
  final String? latestFeedbackId;
  final String? latestFeedbackDecision;
  final String? latestFeedbackReason;
  final bool pricingEligible;
}

class RecommendationEvidence {
  RecommendationEvidence({
    required this.observationId,
    required this.sellerId,
    required this.sellerName,
    required this.title,
    required this.description,
    required this.descriptionAvailable,
    required this.conditionRaw,
    required this.conditionState,
    required this.conditionReasonCodes,
    required this.crossCandidates,
    required this.brand,
    required this.searchOeNorm,
    required this.extractedOeNorms,
    required this.verifiedMatchedOeNorm,
    required this.comparisonIdentityKey,
    required this.oeVerificationStatus,
    required this.oeEvidenceSummary,
    required this.oeExtractorVersion,
    required this.oeReenrichedAt,
    required this.oeReenrichmentErrorCode,
    required this.url,
    required this.urlAbsenceReason,
    required Object price,
    required this.currency,
    required this.currencyRaw,
    required this.currencyInferred,
    required this.isAvailable,
    required this.matchConfidence,
    required this.sourceConfidence,
    required this.sourceConfidenceFactors,
    required this.sourceConfidenceMethodVersion,
    required this.ageHours,
    required this.tier,
    required this.tierConfidence,
    required this.isUsed,
    required this.isKemp,
    required this.isOwned,
    required this.isDumping,
    required this.cohortRole,
    required this.targetEffect,
    required this.exclusionReason,
    required Object? normalizedPrice,
    required this.multiplier,
    required this.coefficientModel,
    required this.coefficientVersion,
    required this.coefficientConfidence,
    required this.observedAt,
    required this.automaticEligible,
    required this.comparabilityHardGateResult,
    required this.calibrationExclusionCodes,
    required this.offerOutcomeCounts,
    required this.comparabilityPolicyId,
    required this.comparabilityPolicyHash,
    required this.comparisonEvidence,
    this.candidateSnapshot = const <String, dynamic>{},
    this.llmReviewRequired = false,
    this.llmPricingEligible = false,
    this.llmReview,
  }) : price = DecimalValue.from(price),
       normalizedPrice = DecimalValue.tryParse(normalizedPrice);

  factory RecommendationEvidence.fromJson(Map<String, dynamic> json) {
    return RecommendationEvidence(
      observationId: json['observation_id'] as String,
      sellerId: json['seller_id']?.toString() ?? '',
      sellerName: json['seller_name'] as String,
      title: json['title'] as String,
      description: json['description'] as String?,
      descriptionAvailable: json['description_available'] as bool? ?? false,
      conditionRaw: json['condition_raw']?.toString(),
      conditionState: json['condition_state']?.toString() ?? 'UNKNOWN',
      conditionReasonCodes:
          (json['condition_reason_codes'] as List<dynamic>? ?? const [])
              .map((item) => item.toString())
              .toList(growable: false),
      crossCandidates: (json['cross_candidates'] as List<dynamic>? ?? const [])
          .whereType<Map>()
          .map(Map<String, dynamic>.from)
          .toList(growable: false),
      brand: json['brand'] as String?,
      searchOeNorm: json['search_oe_norm']?.toString() ?? '',
      extractedOeNorms:
          (json['extracted_oe_norms'] as List<dynamic>? ?? const [])
              .map((item) => item.toString())
              .toList(growable: false),
      verifiedMatchedOeNorm: json['verified_matched_oe_norm']?.toString(),
      comparisonIdentityKey: json['comparison_identity_key']?.toString(),
      oeVerificationStatus:
          json['oe_verification_status']?.toString() ?? 'UNKNOWN',
      oeEvidenceSummary:
          (json['oe_evidence_summary'] as List<dynamic>? ?? const [])
              .whereType<Map>()
              .map(Map<String, dynamic>.from)
              .toList(growable: false),
      oeExtractorVersion: json['oe_extractor_version']?.toString() ?? '',
      oeReenrichedAt: json['oe_reenriched_at'] == null
          ? null
          : DateTime.tryParse(json['oe_reenriched_at'].toString()),
      oeReenrichmentErrorCode: json['oe_reenrichment_error_code']?.toString(),
      url: json['url'] as String,
      urlAbsenceReason: json['url_absence_reason']?.toString(),
      price: json['price'] ?? 0,
      currency: json['currency'] as String,
      currencyRaw: json['currency_raw']?.toString(),
      currencyInferred: json['currency_inferred'] as bool? ?? false,
      isAvailable: json['is_available'] as bool?,
      matchConfidence: _decimal(json['match_confidence']) ?? 0,
      sourceConfidence: _decimal(json['source_confidence']),
      sourceConfidenceFactors:
          json['source_confidence_factors'] is Map<dynamic, dynamic>
          ? Map<String, dynamic>.from(
              json['source_confidence_factors'] as Map<dynamic, dynamic>,
            )
          : const <String, dynamic>{},
      sourceConfidenceMethodVersion:
          json['source_confidence_method_version']?.toString() ?? '',
      ageHours: _decimal(json['age_hours']),
      tier: json['tier'] as String,
      tierConfidence: _decimal(json['tier_confidence']) ?? 0,
      isUsed: json['is_used'] as bool? ?? false,
      isKemp: json['is_kemp'] as bool? ?? false,
      isOwned: json['is_owned'] as bool? ?? false,
      isDumping: json['is_dumping'] as bool,
      cohortRole: json['cohort_role']?.toString() ?? 'MANUAL_REVIEW',
      targetEffect: json['target_effect']?.toString() ?? 'NOT_IN_TARGET_MEDIAN',
      exclusionReason: json['exclusion_reason'] as String?,
      normalizedPrice: json['normalized_price'],
      multiplier: _decimal(json['multiplier']),
      coefficientModel: json['coefficient_model']?.toString(),
      coefficientVersion: json['coefficient_version']?.toString(),
      coefficientConfidence: _decimal(json['coefficient_confidence']),
      observedAt: DateTime.parse(json['observed_at'] as String),
      automaticEligible: json['automatic_eligible'] as bool? ?? false,
      comparabilityHardGateResult:
          json['comparability_hard_gate_result']?.toString() ??
          (json['comparison_evidence'] as Map?)?['hard_gate_result']
              ?.toString() ??
          'MANUAL_REVIEW',
      calibrationExclusionCodes:
          (json['calibration_exclusion_codes'] as List<dynamic>? ?? const [])
              .map((item) => item.toString())
              .toList(growable: false),
      offerOutcomeCounts: (json['offer_outcome_counts'] as Map? ?? const {})
          .map(
            (key, value) => MapEntry(
              key.toString(),
              value is num
                  ? value.toInt()
                  : int.tryParse(value.toString()) ?? 0,
            ),
          ),
      comparabilityPolicyId: json['comparability_policy_id']?.toString(),
      comparabilityPolicyHash: json['comparability_policy_hash']?.toString(),
      comparisonEvidence: json['comparison_evidence'] as Map<String, dynamic>?,
      candidateSnapshot: json['candidate_snapshot'] is Map<dynamic, dynamic>
          ? Map<String, dynamic>.from(
              json['candidate_snapshot'] as Map<dynamic, dynamic>,
            )
          : const <String, dynamic>{},
      llmReviewRequired: json['llm_review_required'] as bool? ?? false,
      llmPricingEligible: json['llm_pricing_eligible'] as bool? ?? false,
      llmReview: json['llm_review'] is Map<dynamic, dynamic>
          ? ComparabilityReview.fromJson(
              Map<String, dynamic>.from(
                json['llm_review'] as Map<dynamic, dynamic>,
              ),
            )
          : null,
    );
  }

  final String observationId;
  final String sellerId;
  final String sellerName;
  final String title;
  final String? description;
  final bool descriptionAvailable;
  final String? conditionRaw;
  final String conditionState;
  final List<String> conditionReasonCodes;
  final List<Map<String, dynamic>> crossCandidates;
  final String? brand;
  final String searchOeNorm;
  final List<String> extractedOeNorms;
  final String? verifiedMatchedOeNorm;
  final String? comparisonIdentityKey;
  final String oeVerificationStatus;
  final List<Map<String, dynamic>> oeEvidenceSummary;
  final String oeExtractorVersion;
  final DateTime? oeReenrichedAt;
  final String? oeReenrichmentErrorCode;
  final String url;
  final String? urlAbsenceReason;
  final DecimalValue price;
  final String currency;
  final String? currencyRaw;
  final bool currencyInferred;
  final bool? isAvailable;
  final double matchConfidence;
  final double? sourceConfidence;
  final Map<String, dynamic> sourceConfidenceFactors;
  final String sourceConfidenceMethodVersion;
  final double? ageHours;
  final String tier;
  final double tierConfidence;
  final bool isUsed;
  final bool isKemp;
  final bool isOwned;
  final bool isDumping;
  final String cohortRole;
  final String targetEffect;
  final String? exclusionReason;
  final DecimalValue? normalizedPrice;
  final double? multiplier;
  final String? coefficientModel;
  final String? coefficientVersion;
  final double? coefficientConfidence;
  final DateTime observedAt;
  final bool automaticEligible;
  final String comparabilityHardGateResult;
  final List<String> calibrationExclusionCodes;
  final Map<String, int> offerOutcomeCounts;
  final String? comparabilityPolicyId;
  final String? comparabilityPolicyHash;
  final Map<String, dynamic>? comparisonEvidence;
  final Map<String, dynamic> candidateSnapshot;
  final bool llmReviewRequired;
  final bool llmPricingEligible;
  final ComparabilityReview? llmReview;

  String get tierLabel => switch (tier) {
    'oem' => 'OEM',
    'oes' => 'OES',
    'aftermarket_a' => 'Aftermarket A',
    'aftermarket_b' => 'Aftermarket B',
    'budget' => 'Бюджет',
    'kemp' => 'KEMP',
    'used' => 'б/у',
    _ => 'не определён',
  };

  bool get affectsTargetMedian => targetEffect == 'IN_TARGET_MEDIAN';

  String get cohortLabel => switch (cohortRole) {
    'TARGET_MARKET' => 'Целевой рынок',
    'KEMP_REFERENCE' => 'KEMP reference',
    'OWNED_STORE' => 'Свой магазин',
    'USED_REJECTED' => 'Б/у — исключено',
    'DUMPING_DIAGNOSTIC' => 'KEMP dumping diagnostic',
    'HARD_REJECTED' => 'Отклонено',
    _ => 'Ручная проверка',
  };
}

class PricingRunSummary {
  const PricingRunSummary({
    required this.id,
    required this.importBatchId,
    required this.status,
    required this.coefficientModel,
    required this.coefficientVersion,
    required this.calibrationDatasetHash,
    required this.correlationId,
    required this.totalItems,
    required this.completedItems,
    required this.failedItems,
    required this.manualReviewItems,
    required this.error,
    required this.createdAt,
  });

  factory PricingRunSummary.fromJson(Map<String, dynamic> json) {
    return PricingRunSummary(
      id: json['id'] as String,
      importBatchId: json['import_batch_id'] as String,
      status: json['status'] as String,
      coefficientModel: json['coefficient_model']?.toString() ?? 'shrinkage',
      coefficientVersion: json['coefficient_version']?.toString(),
      calibrationDatasetHash: json['calibration_dataset_hash']?.toString(),
      correlationId:
          (json['calibration_accounting']
                  as Map<String, dynamic>?)?['correlation_id']
              ?.toString(),
      totalItems: (json['total_items'] as num).toInt(),
      completedItems: (json['completed_items'] as num).toInt(),
      failedItems: (json['failed_items'] as num).toInt(),
      manualReviewItems: (json['manual_review_items'] as num).toInt(),
      error: json['error'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  final String id;
  final String importBatchId;
  final String status;
  final String coefficientModel;
  final String? coefficientVersion;
  final String? calibrationDatasetHash;
  final String? correlationId;
  final int totalItems;
  final int completedItems;
  final int failedItems;
  final int manualReviewItems;
  final String? error;
  final DateTime createdAt;

  bool get isFinished =>
      const {'completed', 'partial', 'failed', 'cancelled'}.contains(status);

  double? get progress =>
      totalItems > 0 ? (completedItems + failedItems) / totalItems : null;
}
