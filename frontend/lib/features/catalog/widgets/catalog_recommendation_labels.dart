import 'package:flutter/widgets.dart';

import '../../../core/app_language.dart';

/// Explains why the pricing engine stayed silent for a given reason code.
/// Returns null for codes that are not silence reasons.
String? catalogSilenceLabel(BuildContext context, String code) {
  return switch (code) {
    'PRICE_ALREADY_AT_OR_ABOVE_TARGET' => context.localized(
      ru: 'Рекомендация не выдаётся: вы уже в рынке.',
      uk: 'Рекомендація не видається: ви вже в ринку.',
    ),
    'CHANGE_BELOW_SIGNIFICANCE_THRESHOLD' => context.localized(
      ru: 'Рекомендация не выдаётся: изменение ниже порога значимости.',
      uk: 'Рекомендація не видається: зміна нижча за поріг значущості.',
    ),
    'STALE_NOT_BELOW_CHEAPEST_COMPETITOR' => context.localized(
      ru:
          'Рекомендация не выдаётся: товар лежалый и не дешевле самого '
          'дешёвого конкурента.',
      uk:
          'Рекомендація не видається: товар залежаний і не дешевший за '
          'найдешевшого конкурента.',
    ),
    'LOW_CONFIDENCE_BASIS' => context.localized(
      ru: 'Расчёт показан, но база слишком разнородна для рекомендации.',
      uk: 'Розрахунок показано, але база надто різнорідна для рекомендації.',
    ),
    'TOO_FEW_PRICING_EVIDENCE' => context.localized(
      ru: 'Рекомендация не выдаётся: меньше трёх приведённых цен.',
      uk: 'Рекомендація не видається: менше трьох приведених цін.',
    ),
    'ROUNDING_REMOVED_THE_CHANGE' => context.localized(
      ru: 'Рекомендация не выдаётся: после округления изменения не осталось.',
      uk: 'Рекомендація не видається: після округлення зміни не залишилось.',
    ),
    _ => null,
  };
}
