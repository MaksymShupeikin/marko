import '../../core/formatters.dart';

/// Весь каталог чи його частина.
enum RepriceScope {
  full('full', 'Весь каталог'),
  partial('partial', 'Частина каталогу');

  const RepriceScope(this.value, this.label);

  final String value;
  final String label;
}

/// З початку чи далі з місця, де зупинилися.
enum RepriceMode {
  fresh('fresh', 'З початку'),
  resume('resume', 'Продовжити');

  const RepriceMode(this.value, this.label);

  final String value;
  final String label;
}

enum RepricePolicy {
  aggressive('aggressive', 'Агресивно', 'Дешевше за 90% схожих пропозицій'),
  balanced('balanced', 'Баланс', 'Дешевше за 75% схожих пропозицій'),
  holdMargin('hold_margin', 'Тримати маржу', 'Близько до медіани ринку');

  const RepricePolicy(this.value, this.label, this.hint);

  final String value;
  final String label;
  final String hint;
}

/// Три відповіді, які не можна змішувати: ціну змінено, ціна вже правильна,
/// і ми не змогли порахувати. Останні дві — протилежні твердження.
enum RepriceOutcome {
  changed('changed', 'Змінено'),
  unchanged('unchanged', 'Без змін'),
  noRecommendation('no_recommendation', 'Не пораховано');

  const RepriceOutcome(this.value, this.label);

  final String value;
  final String label;

  static RepriceOutcome? parse(String? value) {
    for (final outcome in RepriceOutcome.values) {
      if (outcome.value == value) return outcome;
    }
    return null;
  }
}

/// Каталог, відносно якого рахували: склад товарів, а не їхні ціни.
class CatalogSignature {
  const CatalogSignature({
    required this.signature,
    required this.itemCount,
    required this.storeIds,
  });

  factory CatalogSignature.fromJson(Map<String, dynamic> json) {
    return CatalogSignature(
      signature: json['signature'] as String? ?? '',
      itemCount: (json['item_count'] as num?)?.toInt() ?? 0,
      storeIds: [
        for (final value in (json['store_ids'] as List? ?? [])) '$value',
      ],
    );
  }

  final String signature;
  final int itemCount;
  final List<String> storeIds;

  /// Підпис цілком людині ні про що не каже — у списку показуємо початок.
  String get shortSignature =>
      signature.length <= 8 ? signature : signature.substring(0, 8);
}

class RepricePreview {
  const RepricePreview({
    required this.catalog,
    required this.matching,
    required this.covered,
    required this.remaining,
    required this.checksLeft,
    required this.signatureChanged,
  });

  factory RepricePreview.fromJson(Map<String, dynamic> json) {
    return RepricePreview(
      catalog: CatalogSignature.fromJson(
        json['catalog'] as Map<String, dynamic>? ?? const {},
      ),
      matching: (json['matching'] as num?)?.toInt() ?? 0,
      covered: (json['covered'] as num?)?.toInt() ?? 0,
      remaining: (json['remaining'] as num?)?.toInt() ?? 0,
      checksLeft: (json['checks_left'] as num?)?.toInt(),
      signatureChanged: json['signature_changed'] as bool? ?? false,
    );
  }

  final CatalogSignature catalog;
  final int matching;
  final int covered;
  final int remaining;

  /// `null` — повний доступ, ліміту перевірок немає.
  final int? checksLeft;

  /// Склад каталогу змінився з часу останнього прогону.
  final bool signatureChanged;
}

class RepriceRun {
  const RepriceRun({
    required this.id,
    required this.scope,
    required this.mode,
    required this.policy,
    required this.catalog,
    required this.catalogIsCurrent,
    required this.status,
    required this.progressCurrent,
    required this.progressTotal,
    required this.error,
    required this.changedCount,
    required this.unchangedCount,
    required this.skippedCount,
    required this.failedCount,
    required this.createdAt,
  });

  factory RepriceRun.fromJson(Map<String, dynamic> json) {
    return RepriceRun(
      id: json['id'] as String,
      scope: json['scope'] as String? ?? 'partial',
      mode: json['mode'] as String? ?? 'fresh',
      policy: json['policy'] as String? ?? 'balanced',
      catalog: CatalogSignature.fromJson(
        json['catalog'] as Map<String, dynamic>? ?? const {},
      ),
      catalogIsCurrent: json['catalog_is_current'] as bool? ?? true,
      status: json['status'] as String? ?? 'queued',
      progressCurrent: (json['progress_current'] as num?)?.toInt() ?? 0,
      progressTotal: (json['progress_total'] as num?)?.toInt(),
      error: json['error'] as String?,
      changedCount: (json['changed_count'] as num?)?.toInt() ?? 0,
      unchangedCount: (json['unchanged_count'] as num?)?.toInt() ?? 0,
      skippedCount: (json['skipped_count'] as num?)?.toInt() ?? 0,
      failedCount: (json['failed_count'] as num?)?.toInt() ?? 0,
      createdAt:
          DateTime.tryParse(json['created_at'] as String? ?? '')?.toLocal() ??
          DateTime.now(),
    );
  }

  final String id;
  final String scope;
  final String mode;
  final String policy;
  final CatalogSignature catalog;

  /// Чи збігається каталог прогону з нинішнім складом каталогу.
  final bool catalogIsCurrent;
  final String status;
  final int progressCurrent;
  final int? progressTotal;
  final String? error;
  final int changedCount;
  final int unchangedCount;
  final int skippedCount;
  final int failedCount;
  final DateTime createdAt;

  bool get isFinished =>
      status == 'completed' || status == 'failed' || status == 'cancelled';

  bool get isRunning => !isFinished;

  String get statusLabel => switch (status) {
    'queued' => 'у черзі',
    'running' => 'виконується',
    'completed' => 'готово',
    'failed' => 'помилка',
    'cancelled' => 'скасовано',
    _ => status,
  };

  String get scopeLabel =>
      scope == 'full' ? 'весь каталог' : 'частина каталогу';

  String get modeLabel => mode == 'resume' ? 'продовження' : 'з початку';

  String get createdAtLabel => formatDateTimeUk(createdAt);

  double? get progress {
    final total = progressTotal;
    if (total != null && total > 0) return progressCurrent / total;
    return status == 'completed' ? 1 : null;
  }

  int get total => changedCount + unchangedCount + skippedCount + failedCount;
}

class RepriceItem {
  const RepriceItem({
    required this.listingId,
    required this.name,
    required this.sku,
    required this.brand,
    required this.storeName,
    required this.imageUrl,
    required this.url,
    required this.currency,
    required this.outcome,
    required this.reason,
    required this.oldPrice,
    required this.newPrice,
    required this.deltaPercent,
    required this.priceChangedSince,
    required this.zone,
    required this.tier,
    required this.offersTotal,
    required this.dismissed,
  });

  factory RepriceItem.fromJson(Map<String, dynamic> json) {
    double? price(String key) {
      final value = json[key];
      if (value == null) return null;
      return double.tryParse('$value');
    }

    return RepriceItem(
      listingId: json['listing_id'] as String,
      name: json['name'] as String? ?? '',
      sku: json['sku'] as String?,
      brand: json['brand'] as String?,
      storeName: json['store_name'] as String?,
      imageUrl: json['image_url'] as String?,
      url: json['url'] as String? ?? '',
      currency: json['currency'] as String? ?? 'UAH',
      outcome: RepriceOutcome.parse(json['outcome'] as String?),
      reason: json['reason'] as String?,
      oldPrice: price('old_price'),
      newPrice: price('new_price'),
      deltaPercent: price('delta_pct'),
      priceChangedSince: json['price_changed_since'] as bool? ?? false,
      zone: json['zone'] as String?,
      tier: json['tier'] as String?,
      offersTotal: (json['offers_total'] as num?)?.toInt() ?? 0,
      dismissed: json['dismissed'] as bool? ?? false,
    );
  }

  final String listingId;
  final String name;
  final String? sku;
  final String? brand;
  final String? storeName;
  final String? imageUrl;
  final String url;
  final String currency;
  final RepriceOutcome? outcome;

  /// Чому не пораховано. Для `noRecommendation` завжди заповнена.
  final String? reason;
  final double? oldPrice;
  final double? newPrice;
  final double? deltaPercent;

  /// Ціна товару поїхала вже після розрахунку — рядок застарів.
  final bool priceChangedSince;
  final String? zone;
  final String? tier;
  final int offersTotal;
  final bool dismissed;

  String get zoneLabel => switch (zone) {
    'underpriced' => 'нижче ринку',
    'value' => 'дешевий сегмент',
    'mainstream' => 'середина ринку',
    'premium' => 'дорогий сегмент',
    'outlier_high' => 'вище всіх',
    _ => '',
  };

  RepriceItem copyWith({bool? dismissed}) => RepriceItem(
    listingId: listingId,
    name: name,
    sku: sku,
    brand: brand,
    storeName: storeName,
    imageUrl: imageUrl,
    url: url,
    currency: currency,
    outcome: outcome,
    reason: reason,
    oldPrice: oldPrice,
    newPrice: newPrice,
    deltaPercent: deltaPercent,
    priceChangedSince: priceChangedSince,
    zone: zone,
    tier: tier,
    offersTotal: offersTotal,
    dismissed: dismissed ?? this.dismissed,
  );
}

class RepriceItemPage {
  const RepriceItemPage({
    required this.items,
    required this.total,
    required this.offset,
  });

  factory RepriceItemPage.fromJson(Map<String, dynamic> json) {
    return RepriceItemPage(
      items: [
        for (final item in (json['items'] as List? ?? []))
          RepriceItem.fromJson(item as Map<String, dynamic>),
      ],
      total: (json['total'] as num?)?.toInt() ?? 0,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }

  static const empty = RepriceItemPage(items: [], total: 0, offset: 0);

  final List<RepriceItem> items;
  final int total;
  final int offset;
}
