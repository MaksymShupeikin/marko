double? _decimal(dynamic value) =>
    value == null ? null : double.tryParse(value.toString());

class PricingRecommendation {
  const PricingRecommendation({
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
    required this.currentPrice,
    required this.fairPrice,
    required this.recommendedPrice,
    required this.lowerBound,
    required this.upperBound,
    required this.confidence,
    required this.confidenceGrade,
    required this.weakestFactor,
    required this.competitorCount,
    required this.rawCompetitorCount,
    required this.uniqueSellerCount,
    required this.cleanCompetitorCount,
    required this.effectiveCompetitorCount,
    required this.dispersion,
    required this.outlierMethod,
    required this.outlierCount,
    required this.sensitivity,
    required this.actionGatesPassed,
    required this.costFloor,
    required this.costBasisInventoryValue,
    required this.priorityScore,
    required this.priorityScoreType,
    required this.reviewPriority,
    required this.reasonCodes,
    required this.factorScores,
    required this.excludedObservations,
    required this.policyVersion,
    required this.parserVersion,
    required this.classifierVersion,
    required this.coefficientVersion,
    required this.calibrationDatasetHash,
    required this.currency,
    required this.priceTick,
    required this.priceTickVersion,
    required this.computedAt,
  });

  factory PricingRecommendation.fromJson(Map<String, dynamic> json) {
    final rawFactors = json['factor_scores'] as Map<String, dynamic>? ?? {};
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
      currentPrice: _decimal(json['current_price']) ?? 0,
      fairPrice: _decimal(json['fair_price']),
      recommendedPrice: _decimal(json['recommended_price']),
      lowerBound: _decimal(json['lower_bound']),
      upperBound: _decimal(json['upper_bound']),
      confidence: _decimal(json['confidence']) ?? 0,
      confidenceGrade: json['confidence_grade'] as String,
      weakestFactor: json['weakest_factor'] as String?,
      competitorCount: (json['competitor_count'] as num).toInt(),
      rawCompetitorCount:
          (json['raw_competitor_count'] as num?)?.toInt() ??
          (json['competitor_count'] as num).toInt(),
      uniqueSellerCount:
          (json['unique_seller_count'] as num?)?.toInt() ??
          (json['competitor_count'] as num).toInt(),
      cleanCompetitorCount:
          (json['clean_competitor_count'] as num?)?.toInt() ??
          (json['competitor_count'] as num).toInt(),
      effectiveCompetitorCount:
          _decimal(json['effective_competitor_count']) ??
          (json['competitor_count'] as num).toDouble(),
      dispersion: _decimal(json['dispersion']),
      outlierMethod: json['outlier_method']?.toString() ?? 'none',
      outlierCount: (json['outlier_count'] as num?)?.toInt() ?? 0,
      sensitivity: _decimal(json['sensitivity']),
      actionGatesPassed: json['action_gates_passed'] as bool? ?? false,
      costFloor: _decimal(json['cost_floor']),
      costBasisInventoryValue: _decimal(json['cost_basis_inventory_value']),
      priorityScore: _decimal(json['priority_score']) ?? 0,
      priorityScoreType: json['priority_score_type'] as String,
      reviewPriority: _decimal(json['review_priority']) ?? 0,
      reasonCodes: (json['reason_codes'] as List<dynamic>)
          .map((item) => item.toString())
          .toList(growable: false),
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
      priceTick: _decimal(json['price_tick']) ?? 1,
      priceTickVersion: json['price_tick_version']?.toString() ?? 'legacy',
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
  final double currentPrice;
  final double? fairPrice;
  final double? recommendedPrice;
  final double? lowerBound;
  final double? upperBound;
  final double confidence;
  final String confidenceGrade;
  final String? weakestFactor;
  final int competitorCount;
  final int rawCompetitorCount;
  final int uniqueSellerCount;
  final int cleanCompetitorCount;
  final double effectiveCompetitorCount;
  final double? dispersion;
  final String outlierMethod;
  final int outlierCount;
  final double? sensitivity;
  final bool actionGatesPassed;
  final double? costFloor;
  final double? costBasisInventoryValue;
  final double priorityScore;
  final String priorityScoreType;
  final double reviewPriority;
  final List<String> reasonCodes;
  final Map<String, double> factorScores;
  final List<Map<String, dynamic>> excludedObservations;
  final String policyVersion;
  final String parserVersion;
  final String classifierVersion;
  final String? coefficientVersion;
  final String? calibrationDatasetHash;
  final String currency;
  final double priceTick;
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

  bool get isRaise => action == 'RAISE';
  bool get isLower => action == 'LOWER';
  bool get needsReview =>
      action == 'MANUAL_REVIEW' || action == 'INSUFFICIENT_DATA';

  String get priorityLabel => switch (priorityScoreType) {
    'gross_uplift_opportunity' =>
      '${priorityScore.toStringAsFixed(0)} ₴/мес. с учётом confidence',
    'clearance_priority' =>
      '${priorityScore.toStringAsFixed(0)} ₴ замороженного капитала',
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
    return reasonCodes.map(reasonLabel).take(2).join(' · ');
  }

  static String reasonLabel(String code) => switch (code) {
    'MARKET_SUPPORTS_RAISE' => 'рынок поддерживает повышение',
    'MARKET_NOT_ABOVE_RAISE_THRESHOLD' => 'рынок не выше текущей цены',
    'CLEARANCE_MARKDOWN' => 'цена для высвобождения капитала',
    'TOO_FEW_COMPETITORS' ||
    'TOO_FEW_COMPETITORS_FOR_ACTION' => 'мало валидных конкурентов',
    'LOW_CONFIDENCE' => 'низкая уверенность',
    'LOW_COVERAGE' => 'мало данных',
    'LOW_DISPERSION' => 'слишком большой разброс цен',
    'HIGH_DISPERSION' => 'слишком большой разброс цен',
    'LOW_FRESHNESS' => 'данные устарели',
    'LOW_MATCH' => 'слабое совпадение товаров',
    'LOW_TIER' => 'смешались уровни товара',
    'LOW_SOURCE' => 'низкая надёжность источника',
    'SEVERE_DATA_HEALTH_ISSUE' => 'критическая проблема данных',
    'BELOW_COST_ONLY_FOR_DEAD_STOCK' =>
      'цена ниже себестоимости доступна только для неликвида',
    'MISSING_FLOOR' || 'MISSING_COST' => 'нужна себестоимость',
    'LOW_EFFECTIVE_SAMPLE_SIZE' => 'мало независимых конкурентов',
    'ESTIMATOR_SENSITIVITY' => 'оценка неустойчива к очистке данных',
    'MISSING_BELOW_COST_AUTHORIZATION' =>
      'нет полного подтверждения продажи ниже себестоимости',
    'MANUAL_REVIEW_REQUIRED' => 'требуется ручная проверка',
    _ => code.toLowerCase().replaceAll('_', ' '),
  };
}

class RecommendationPage {
  const RecommendationPage({
    required this.items,
    required this.total,
    required this.runId,
  });

  factory RecommendationPage.fromJson(Map<String, dynamic> json) {
    return RecommendationPage(
      items: (json['items'] as List<dynamic>)
          .map(
            (item) =>
                PricingRecommendation.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
      runId: json['run_id'] as String?,
    );
  }

  final List<PricingRecommendation> items;
  final int total;
  final String? runId;
}

class RecommendationEvidence {
  const RecommendationEvidence({
    required this.observationId,
    required this.sellerName,
    required this.title,
    required this.brand,
    required this.url,
    required this.price,
    required this.currency,
    required this.matchConfidence,
    required this.sourceConfidence,
    required this.ageHours,
    required this.tier,
    required this.tierConfidence,
    required this.isDumping,
    required this.exclusionReason,
    required this.normalizedPrice,
    required this.multiplier,
    required this.coefficientModel,
    required this.coefficientVersion,
    required this.coefficientConfidence,
    required this.observedAt,
  });

  factory RecommendationEvidence.fromJson(Map<String, dynamic> json) {
    return RecommendationEvidence(
      observationId: json['observation_id'] as String,
      sellerName: json['seller_name'] as String,
      title: json['title'] as String,
      brand: json['brand'] as String?,
      url: json['url'] as String,
      price: _decimal(json['price']) ?? 0,
      currency: json['currency'] as String,
      matchConfidence: _decimal(json['match_confidence']) ?? 0,
      sourceConfidence: _decimal(json['source_confidence']) ?? 1,
      ageHours: _decimal(json['age_hours']) ?? 0,
      tier: json['tier'] as String,
      tierConfidence: _decimal(json['tier_confidence']) ?? 0,
      isDumping: json['is_dumping'] as bool,
      exclusionReason: json['exclusion_reason'] as String?,
      normalizedPrice:
          _decimal(json['normalized_price']) ?? (_decimal(json['price']) ?? 0),
      multiplier: _decimal(json['multiplier']) ?? 1,
      coefficientModel: json['coefficient_model']?.toString() ?? 'reference',
      coefficientVersion:
          json['coefficient_version']?.toString() ?? 'reference-tier-v1',
      coefficientConfidence: _decimal(json['coefficient_confidence']) ?? 1,
      observedAt: DateTime.parse(json['observed_at'] as String),
    );
  }

  final String observationId;
  final String sellerName;
  final String title;
  final String? brand;
  final String url;
  final double price;
  final String currency;
  final double matchConfidence;
  final double sourceConfidence;
  final double ageHours;
  final String tier;
  final double tierConfidence;
  final bool isDumping;
  final String? exclusionReason;
  final double normalizedPrice;
  final double multiplier;
  final String coefficientModel;
  final String coefficientVersion;
  final double coefficientConfidence;
  final DateTime observedAt;

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
}

class PricingRunSummary {
  const PricingRunSummary({
    required this.id,
    required this.importBatchId,
    required this.status,
    required this.coefficientModel,
    required this.coefficientVersion,
    required this.calibrationDatasetHash,
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
