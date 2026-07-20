import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../pricing/pricing_models.dart';
import 'catalog_controller.dart';
import 'catalog_models.dart';

class CatalogPage extends ConsumerWidget {
  const CatalogPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(catalogControllerProvider);
    return asyncState.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: MarkoInlineMessage(
          message: error.toString(),
          tone: MarkoMessageTone.error,
          action: TextButton(
            onPressed: () => ref.invalidate(catalogControllerProvider),
            child: const Text('Повторить'),
          ),
        ),
      ),
      data: (state) => _CatalogContent(
        state: state,
        onPickFile: () => _pickFile(ref),
        onStartRun: (item) =>
            ref.read(catalogControllerProvider.notifier).startRun(item),
      ),
    );
  }

  Future<void> _pickFile(WidgetRef ref) async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['xlsx'],
      withData: true,
      allowMultiple: false,
    );
    final file = result?.files.single;
    final bytes = file?.bytes;
    if (file == null || bytes == null) return;
    await ref.read(catalogControllerProvider.notifier).upload(file.name, bytes);
  }
}

class _CatalogContent extends StatelessWidget {
  const _CatalogContent({
    required this.state,
    required this.onPickFile,
    required this.onStartRun,
  });

  final CatalogState state;
  final VoidCallback onPickFile;
  final ValueChanged<CatalogImport> onStartRun;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  alignment: WrapAlignment.spaceBetween,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: 18,
                  runSpacing: 14,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Каталог Prom.ua',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 7),
                        Text(
                          'Загрузите экспорт Prom.ua или рабочий XLSX «Ввод Юрия».',
                          style: Theme.of(
                            context,
                          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                        ),
                      ],
                    ),
                    FilledButton.icon(
                      onPressed: state.isUploading ? null : onPickFile,
                      icon: state.isUploading
                          ? const SizedBox.square(
                              dimension: 17,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.upload_file_rounded, size: 18),
                      label: Text(
                        state.isUploading ? 'Импортируем…' : 'Загрузить XLSX',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 20),
                const MarkoInlineMessage(
                  message:
                      'Обязательны: OE/OEM, название, категория и цена. Статус, возраст запаса и продажи можно заполнить в ячейках. До 25 MB.',
                ),
                if (state.error != null) ...[
                  const SizedBox(height: 12),
                  MarkoInlineMessage(
                    message: state.error!,
                    tone: MarkoMessageTone.error,
                  ),
                ],
                if (state.activeRun != null) ...[
                  const SizedBox(height: 16),
                  _RunProgress(run: state.activeRun!),
                ],
                const SizedBox(height: 24),
                Text(
                  'История импортов',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                if (state.imports.isEmpty)
                  MarkoPanel(
                    child: Text(
                      'Ещё нет загруженных каталогов.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  )
                else
                  ...state.imports.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: _ImportRow(
                        item: item,
                        runBusy: state.activeRun?.isFinished == false,
                        onStart: () => onStartRun(item),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ImportRow extends StatelessWidget {
  const _ImportRow({
    required this.item,
    required this.runBusy,
    required this.onStart,
  });

  final CatalogImport item;
  final bool runBusy;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final hasErrors = item.rejectedRows > 0;
    return MarkoPanel(
      padding: const EdgeInsets.all(17),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: hasErrors ? colors.warningSoft : colors.positiveSoft,
                  borderRadius: BorderRadius.circular(9),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.table_view_outlined,
                  color: hasErrors ? colors.warning : colors.positive,
                  size: 20,
                ),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.filename,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${item.importedRows} загружено · ${item.rejectedRows} отклонено · ${item.statusLabel}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                onPressed: item.canRun && !runBusy ? onStart : null,
                icon: const Icon(Icons.play_arrow_rounded, size: 18),
                label: const Text('Запустить расчёт'),
              ),
            ],
          ),
          if (item.errors.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Divider(),
            const SizedBox(height: 6),
            ...item.errors
                .take(3)
                .map(
                  (error) => Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      'Строка ${error['row'] ?? '?'}: ${error['message'] ?? error['code'] ?? 'ошибка'}',
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.warning),
                    ),
                  ),
                ),
            if (item.errors.length > 3)
              Text(
                'И ещё ${item.errors.length - 3} ошибок',
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ],
      ),
    );
  }
}

class _RunProgress extends StatelessWidget {
  const _RunProgress({required this.run});

  final PricingRunSummary run;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final failed = run.status == 'failed';
    final done = run.isFinished && !failed;
    final foreground = failed
        ? colors.negative
        : done
        ? colors.positive
        : colors.brand;
    return MarkoPanel(
      color: failed
          ? colors.negativeSoft
          : done
          ? colors.positiveSoft
          : colors.brandSoft,
      borderColor: Colors.transparent,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                failed
                    ? Icons.error_outline_rounded
                    : done
                    ? Icons.check_circle_outline_rounded
                    : Icons.analytics_outlined,
                color: foreground,
                size: 20,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  done
                      ? 'Расчёт завершён'
                      : failed
                      ? 'Расчёт остановлен с ошибкой'
                      : 'Собираем рынок и считаем цены',
                  style: Theme.of(
                    context,
                  ).textTheme.titleMedium?.copyWith(color: foreground),
                ),
              ),
              Text(
                '${run.completedItems}/${run.totalItems}',
                style: Theme.of(
                  context,
                ).textTheme.labelLarge?.copyWith(color: foreground),
              ),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(value: run.progress, color: foreground),
          if (run.manualReviewItems > 0 || run.failedItems > 0) ...[
            const SizedBox(height: 8),
            Text(
              'Ручная проверка: ${run.manualReviewItems} · ошибки: ${run.failedItems}',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: foreground),
            ),
          ],
        ],
      ),
    );
  }
}
