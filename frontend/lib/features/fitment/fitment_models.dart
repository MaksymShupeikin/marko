double _decimal(dynamic value) =>
    value == null ? 0 : double.tryParse(value.toString()) ?? 0;

class FitmentEvidence {
  const FitmentEvidence({
    required this.id,
    required this.feature,
    required this.value,
    required this.sourceType,
    required this.sourceTier,
    required this.sourceReliability,
    required this.extractionConfidence,
    required this.directness,
    required this.independenceFactor,
    required this.freshnessFactor,
    required this.correlationGroup,
    required this.polarity,
    required this.statementStatus,
    required this.sourceUrl,
    required this.rawFragment,
    required this.retrievedAt,
  });

  factory FitmentEvidence.fromJson(Map<String, dynamic> json) {
    return FitmentEvidence(
      id: json['id']?.toString() ?? '',
      feature: json['feature']?.toString() ?? 'unknown',
      value: _decimal(json['evidence_value']),
      sourceType: json['source_type']?.toString() ?? 'unknown',
      sourceTier: json['source_tier']?.toString() ?? 'E',
      sourceReliability: _decimal(json['source_reliability']),
      extractionConfidence: _decimal(json['extraction_confidence']),
      directness: _decimal(json['directness'] ?? 1),
      independenceFactor: _decimal(json['independence_factor']),
      freshnessFactor: _decimal(json['freshness_factor']),
      correlationGroup: json['correlation_group']?.toString() ?? 'unknown',
      polarity: json['polarity']?.toString() ?? 'unknown',
      statementStatus: json['statement_status']?.toString() ?? 'UNKNOWN',
      sourceUrl: json['source_url']?.toString(),
      rawFragment: json['raw_fragment']?.toString(),
      retrievedAt: DateTime.tryParse(json['retrieved_at']?.toString() ?? ''),
    );
  }

  final String id;
  final String feature;
  final double value;
  final String sourceType;
  final String sourceTier;
  final double sourceReliability;
  final double extractionConfidence;
  final double directness;
  final double independenceFactor;
  final double freshnessFactor;
  final String correlationGroup;
  final String polarity;
  final String statementStatus;
  final String? sourceUrl;
  final String? rawFragment;
  final DateTime? retrievedAt;

  double get effectiveWeight =>
      sourceReliability *
      extractionConfidence *
      directness *
      independenceFactor *
      freshnessFactor;

  bool get contradicts => value < 0 || polarity == 'contradicts';
}

class FitmentCandidate {
  const FitmentCandidate({
    required this.id,
    required this.observationId,
    required this.sellerId,
    required this.sellerName,
    required this.title,
    required this.brand,
    required this.url,
    required this.price,
    required this.referencePrice,
    required this.currency,
    required this.identity,
    required this.commercialContext,
    required this.compatibilityStatus,
    required this.compatibilityProbability,
    required this.coverage,
    required this.hardRejections,
    required this.reasonCodes,
    required this.missingCriticalFields,
    required this.authoritativeConfirmation,
    required this.requiresManualReview,
    required this.evidenceIds,
    required this.evidenceClaimIds,
    required this.evidence,
    required this.priceComparabilityStatus,
    required this.priceEligible,
    required this.competitorWeight,
    required this.normalizedUnitPrice,
    required this.priceUnitStatus,
    required this.priceUnitCertainty,
    required this.priceReasonCodes,
    required this.automaticPriceChangeAllowed,
  });

  factory FitmentCandidate.fromJson(Map<String, dynamic> json) {
    List<String> strings(String key) =>
        (json[key] as List<dynamic>? ?? const [])
            .map((item) => item.toString())
            .toList(growable: false);
    return FitmentCandidate(
      id: json['id'].toString(),
      observationId: json['market_observation_id'].toString(),
      sellerId: json['seller_id']?.toString() ?? '',
      sellerName: json['seller_name']?.toString() ?? 'Unknown seller',
      title: json['title']?.toString() ?? '',
      brand: json['brand']?.toString(),
      url: json['url']?.toString() ?? '',
      price: _decimal(json['price']),
      referencePrice: json['reference_price'] == null
          ? null
          : _decimal(json['reference_price']),
      currency: json['currency']?.toString() ?? 'UAH',
      identity: json['candidate_identity'] as Map<String, dynamic>? ?? const {},
      commercialContext:
          json['candidate_commercial_context'] as Map<String, dynamic>? ??
          const {},
      compatibilityStatus:
          json['compatibility_status']?.toString() ?? 'uncertain',
      compatibilityProbability: _decimal(json['compatibility_probability']),
      coverage: _decimal(json['coverage']),
      hardRejections: strings('hard_rejections'),
      reasonCodes: strings('reason_codes'),
      missingCriticalFields: strings('missing_critical_fields'),
      authoritativeConfirmation:
          json['authoritative_confirmation'] as bool? ?? false,
      requiresManualReview: json['requires_manual_review'] as bool? ?? true,
      evidenceIds: strings('evidence_ids'),
      evidenceClaimIds: strings('evidence_claim_ids'),
      evidence: (json['evidence'] as List<dynamic>? ?? const [])
          .map(
            (item) => FitmentEvidence.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList(growable: false),
      priceComparabilityStatus:
          json['price_comparability_status']?.toString() ?? 'manual_review',
      priceEligible: json['price_eligible'] as bool? ?? false,
      competitorWeight: _decimal(json['competitor_weight']),
      normalizedUnitPrice: json['normalized_unit_price'] == null
          ? null
          : _decimal(json['normalized_unit_price']),
      priceUnitStatus: json['price_unit_status']?.toString() ?? 'unknown',
      priceUnitCertainty: _decimal(json['price_unit_certainty'] ?? 0.3),
      priceReasonCodes: strings('price_reason_codes'),
      automaticPriceChangeAllowed:
          json['automatic_price_change_allowed'] as bool? ?? false,
    );
  }

  final String id;
  final String observationId;
  final String sellerId;
  final String sellerName;
  final String title;
  final String? brand;
  final String url;
  final double price;
  final double? referencePrice;
  final String currency;
  final Map<String, dynamic> identity;
  final Map<String, dynamic> commercialContext;
  final String compatibilityStatus;
  final double compatibilityProbability;
  final double coverage;
  final List<String> hardRejections;
  final List<String> reasonCodes;
  final List<String> missingCriticalFields;
  final bool authoritativeConfirmation;
  final bool requiresManualReview;
  final List<String> evidenceIds;
  final List<String> evidenceClaimIds;
  final List<FitmentEvidence> evidence;
  final String priceComparabilityStatus;
  final bool priceEligible;
  final double competitorWeight;
  final double? normalizedUnitPrice;
  final String priceUnitStatus;
  final double priceUnitCertainty;
  final List<String> priceReasonCodes;
  final bool automaticPriceChangeAllowed;

  String get statusLabel => switch (compatibilityStatus) {
    'confirmed_compatible' => 'Совместим',
    'likely_compatible' => 'Вероятный аналог',
    'not_compatible' => 'Не совместим',
    _ => 'Требует проверки',
  };

  String get positionLabel {
    final side = identity['side']?.toString();
    final axle = identity['axle']?.toString();
    return [
      if (axle != null && axle.isNotEmpty) axle,
      if (side != null && side.isNotEmpty) side,
    ].join(' / ');
  }

  String get tier => commercialContext['tier']?.toString() ?? 'unknown';
  String get sellerRelation =>
      commercialContext['seller_relation']?.toString() ?? 'unknown';

  int get independentSourceCount =>
      evidence.map((item) => item.correlationGroup).toSet().length;
}

class FitmentCandidatePage {
  const FitmentCandidatePage({
    required this.items,
    required this.total,
    required this.analysisId,
  });

  factory FitmentCandidatePage.fromJson(Map<String, dynamic> json) {
    return FitmentCandidatePage(
      items: (json['items'] as List<dynamic>? ?? const [])
          .map(
            (item) => FitmentCandidate.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList(growable: false),
      total: (json['total'] as num?)?.toInt() ?? 0,
      analysisId: json['analysis_id']?.toString(),
    );
  }

  final List<FitmentCandidate> items;
  final int total;
  final String? analysisId;
}

class FitmentMarketRecommendation {
  const FitmentMarketRecommendation({
    required this.id,
    required this.analysisId,
    required this.action,
    required this.strategy,
    required this.currentPrice,
    required this.recommendedPrice,
    required this.rangeMin,
    required this.rangeMax,
    required this.absoluteChange,
    required this.relativeChange,
    required this.marketAnchor,
    required this.approvedPriceFloor,
    required this.currency,
    required this.confidence,
    required this.confidenceFactors,
    required this.marketSummary,
    required this.priceStatistics,
    required this.reasonCodes,
    required this.warnings,
    required this.automaticPriceChangeAllowed,
    required this.createdAt,
  });

  factory FitmentMarketRecommendation.fromJson(Map<String, dynamic> json) {
    double? nullableDecimal(String key) =>
        json[key] == null ? null : _decimal(json[key]);
    List<String> strings(String key) =>
        (json[key] as List<dynamic>? ?? const [])
            .map((item) => item.toString())
            .toList(growable: false);
    return FitmentMarketRecommendation(
      id: json['id']?.toString() ?? '',
      analysisId: json['analysis_id']?.toString() ?? '',
      action: json['action']?.toString() ?? 'insufficient_evidence',
      strategy: json['strategy']?.toString() ?? 'balanced',
      currentPrice: _decimal(json['current_price']),
      recommendedPrice: nullableDecimal('recommended_price'),
      rangeMin: nullableDecimal('recommended_range_min'),
      rangeMax: nullableDecimal('recommended_range_max'),
      absoluteChange: nullableDecimal('absolute_change'),
      relativeChange: nullableDecimal('relative_change'),
      marketAnchor: nullableDecimal('market_anchor'),
      approvedPriceFloor: nullableDecimal('approved_price_floor'),
      currency: json['currency']?.toString() ?? 'UAH',
      confidence: _decimal(json['confidence']),
      confidenceFactors: Map<String, dynamic>.from(
        json['confidence_factors'] as Map? ?? {},
      ),
      marketSummary: Map<String, dynamic>.from(
        json['market_summary'] as Map? ?? {},
      ),
      priceStatistics: Map<String, dynamic>.from(
        json['price_statistics'] as Map? ?? {},
      ),
      reasonCodes: strings('reason_codes'),
      warnings: strings('warnings'),
      automaticPriceChangeAllowed:
          json['automatic_price_change_allowed'] as bool? ?? false,
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
    );
  }

  final String id;
  final String analysisId;
  final String action;
  final String strategy;
  final double currentPrice;
  final double? recommendedPrice;
  final double? rangeMin;
  final double? rangeMax;
  final double? absoluteChange;
  final double? relativeChange;
  final double? marketAnchor;
  final double? approvedPriceFloor;
  final String currency;
  final double confidence;
  final Map<String, dynamic> confidenceFactors;
  final Map<String, dynamic> marketSummary;
  final Map<String, dynamic> priceStatistics;
  final List<String> reasonCodes;
  final List<String> warnings;
  final bool automaticPriceChangeAllowed;
  final DateTime? createdAt;

  String get actionLabel => switch (action) {
    'consider_raise' => 'Рассмотреть повышение',
    'consider_reduce' => 'Рассмотреть снижение',
    'hold' => 'Оставить текущую цену',
    'manual_research_required' => 'Нужно исследование',
    _ => 'Недостаточно данных',
  };

  int get independentSellerGroups =>
      int.tryParse(
        marketSummary['independent_seller_groups']?.toString() ?? '',
      ) ??
      0;

  double get effectiveSampleSize =>
      _decimal(marketSummary['effective_sample_size']);
}

class FitmentReviewBundle {
  const FitmentReviewBundle({required this.page, required this.recommendation});

  final FitmentCandidatePage page;
  final FitmentMarketRecommendation? recommendation;
}
