import '../../core/presentation_formatters.dart';

class AttentionSummary {
  const AttentionSummary({
    required this.total,
    required this.overpriced,
    required this.underpriced,
    required this.inMarket,
    required this.reviewRequired,
    required this.noData,
    required this.processing,
    required this.updatedAt,
  });

  factory AttentionSummary.fromJson(Map<String, dynamic> json) {
    int count(String key) => (json[key] as num?)?.toInt() ?? 0;
    return AttentionSummary(
      total: count('total'),
      overpriced: count('overpriced'),
      underpriced: count('underpriced'),
      inMarket: count('in_market'),
      reviewRequired: count('review_required'),
      noData: count('no_data'),
      processing: count('processing'),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
    );
  }

  final int total;
  final int overpriced;
  final int underpriced;
  final int inMarket;
  final int reviewRequired;
  final int noData;
  final int processing;
  final DateTime? updatedAt;
}

class AttentionProduct {
  AttentionProduct({
    required this.productId,
    required this.recommendationId,
    required this.name,
    required this.sku,
    required this.oe,
    required this.brand,
    required this.sourceKind,
    required this.sourceId,
    required this.status,
    required this.severity,
    required Object? ourPrice,
    required Object? marketLow,
    required Object? marketHigh,
    required Object? suggestedPrice,
    required this.currency,
    required Object? differencePercent,
    required Object confidence,
    required this.evidenceCount,
    required this.reasonCodes,
    required this.marketCheckedAt,
    required this.updatedAt,
  }) : ourPrice = DecimalValue.tryParse(ourPrice),
       marketLow = DecimalValue.tryParse(marketLow),
       marketHigh = DecimalValue.tryParse(marketHigh),
       suggestedPrice = DecimalValue.tryParse(suggestedPrice),
       differencePercent = DecimalValue.tryParse(differencePercent),
       confidence = DecimalValue.from(confidence);

  factory AttentionProduct.fromJson(Map<String, dynamic> json) {
    return AttentionProduct(
      productId: json['product_id'] as String,
      recommendationId: json['recommendation_id'] as String?,
      name: json['name'] as String,
      sku: json['sku'] as String?,
      oe: json['oe'] as String?,
      brand: json['brand'] as String?,
      sourceKind: json['source_kind'] as String,
      sourceId: json['source_id'] as String,
      status: json['status'] as String,
      severity: (json['severity'] as num?)?.toInt() ?? 0,
      ourPrice: json['our_price'],
      marketLow: json['market_low'],
      marketHigh: json['market_high'],
      suggestedPrice: json['suggested_price'],
      currency: json['currency'] as String? ?? 'UAH',
      differencePercent: json['difference_percent'],
      confidence: json['confidence'] ?? '0',
      evidenceCount: (json['evidence_count'] as num?)?.toInt() ?? 0,
      reasonCodes: (json['reason_codes'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      marketCheckedAt: json['market_checked_at'] == null
          ? null
          : DateTime.parse(json['market_checked_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }

  final String productId;
  final String? recommendationId;
  final String name;
  final String? sku;
  final String? oe;
  final String? brand;
  final String sourceKind;
  final String sourceId;
  final String status;
  final int severity;
  final DecimalValue? ourPrice;
  final DecimalValue? marketLow;
  final DecimalValue? marketHigh;
  final DecimalValue? suggestedPrice;
  final String currency;
  final DecimalValue? differencePercent;
  final DecimalValue confidence;
  final int evidenceCount;
  final List<String> reasonCodes;
  final DateTime? marketCheckedAt;
  final DateTime updatedAt;
}

class AttentionPageResult {
  const AttentionPageResult({
    required this.items,
    required this.total,
    required this.limit,
    required this.offset,
  });

  factory AttentionPageResult.fromJson(Map<String, dynamic> json) {
    return AttentionPageResult(
      items: (json['items'] as List<dynamic>)
          .map(
            (item) => AttentionProduct.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      total: (json['total'] as num?)?.toInt() ?? 0,
      limit: (json['limit'] as num?)?.toInt() ?? 50,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }

  final List<AttentionProduct> items;
  final int total;
  final int limit;
  final int offset;

  bool get hasMore => items.length < total;
}
