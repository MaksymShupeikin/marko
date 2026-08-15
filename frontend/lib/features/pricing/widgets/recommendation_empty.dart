part of '../recommendations_page.dart';

/// Empty list, explained.
///
/// An empty list has two very different causes and the operator has to be able
/// to tell them apart: the run produced nothing, or the selected tab happens to
/// be empty while the work sits under another one. Telling the second case to
/// "connect your stores" sends the operator to fix something that is not broken.
class _EmptyRecommendations extends StatelessWidget {
  const _EmptyRecommendations({
    required this.onOpenCatalog,
    required this.counts,
    required this.queue,
    required this.onShowEverything,
    required this.onShowReview,
  });

  final VoidCallback? onOpenCatalog;
  final RecommendationActionCounts counts;
  final String queue;
  final VoidCallback onShowEverything;
  final VoidCallback onShowReview;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final hiddenByFilter = counts.total > 0 && queue != 'all';
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        children: [
          Icon(
            hiddenByFilter
                ? Icons.filter_alt_off_rounded
                : Icons.price_check_rounded,
            size: 38,
            color: colors.brand,
          ),
          const SizedBox(height: 14),
          Text(
            hiddenByFilter
                ? context.localized(
                    ru: 'В этой вкладке пусто',
                    uk: 'У цій вкладці порожньо',
                  )
                : context.localized(
                    ru: 'Пока нет рекомендаций',
                    uk: 'Рекомендацій поки немає',
                  ),
            style: Theme.of(context).textTheme.titleLarge,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 7),
          Text(
            hiddenByFilter
                ? context.localized(
                    ru: 'В расчёте есть позиции (${counts.total}), но ни одна не попала в эту вкладку.',
                    uk: 'У розрахунку є позиції (${counts.total}), але жодна не потрапила до цієї вкладки.',
                  )
                : context.localized(
                    ru: 'Запустите расчёт по нужному импорту каталога в блоке выше.',
                    uk: 'Запустіть розрахунок за потрібним імпортом каталогу в блоці вище.',
                  ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 18),
          if (hiddenByFilter)
            Wrap(
              spacing: 10,
              runSpacing: 10,
              alignment: WrapAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: onShowEverything,
                  icon: const Icon(Icons.list_rounded, size: 18),
                  label: Text(
                    context.localized(
                      ru: 'Показать все (${counts.total})',
                      uk: 'Показати всі (${counts.total})',
                    ),
                  ),
                ),
                if (counts.review > 0 && queue != 'review')
                  OutlinedButton.icon(
                    onPressed: onShowReview,
                    icon: const Icon(Icons.fact_check_outlined, size: 18),
                    label: Text(
                      context.localized(
                        ru: 'Проверить вручную (${counts.review})',
                        uk: 'Перевірити вручну (${counts.review})',
                      ),
                    ),
                  ),
              ],
            )
          else if (onOpenCatalog != null)
            FilledButton.icon(
              onPressed: onOpenCatalog,
              icon: const Icon(Icons.upload_file_rounded, size: 18),
              label: Text(
                context.localized(
                  ru: 'Открыть каталог',
                  uk: 'Відкрити каталог',
                ),
              ),
            ),
        ],
      ),
    );
  }
}
