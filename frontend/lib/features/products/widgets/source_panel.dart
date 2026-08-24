import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_button.dart';
import '../products_controller.dart';

Future<bool> pickAndImportCatalog(WidgetRef ref) async {
  final file = await FilePicker.pickFile(
    type: FileType.custom,
    allowedExtensions: const ['xlsx'],
  );
  if (file == null) return false;
  final bytes = await file.readAsBytes();
  if (bytes.isEmpty) return false;
  final imported = await ref
      .read(catalogImportProvider.notifier)
      .importFile(file.name, bytes);
  if (imported) {
    await ref.read(productsControllerProvider.notifier).refresh();
  }
  return imported;
}

/// The two ways products get into the catalog: an Excel export or a Prom.ua
/// store. Same modal as the OEM lookup, so both overlays behave alike.
Future<void> showCatalogImport(BuildContext context) => showMarkoModal(
  context,
  title: 'Імпорт каталогу',
  child: CatalogSourceCards(onDone: () => Navigator.of(context).pop()),
);

/// The two source tiles, used by the import modal and by the empty-catalog
/// onboarding screen.
class CatalogSourceCards extends ConsumerStatefulWidget {
  const CatalogSourceCards({this.onDone, super.key});

  /// Called once products actually landed; the modal uses it to close.
  final VoidCallback? onDone;

  @override
  ConsumerState<CatalogSourceCards> createState() => _SourceGridState();
}

class _SourceGridState extends ConsumerState<CatalogSourceCards> {
  final _urlController = TextEditingController();

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final importState = ref.watch(catalogImportProvider).value;
    final busy = importState?.isSubmitting ?? false;
    final fileLoading = importState?.isSubmittingFile ?? false;
    final promLoading = importState?.isSubmittingProm ?? false;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SourceTile(
          accent: colors.excelAccent,
          logo: 'assets/logos/excel.webp',
          monoLogo: true,
          title: 'XLSX вивантаження',
          subtitle: 'Візьмемо назву, ціну, бренд та всі номери запчастини',
          child: _FileDrop(
            busy: busy,
            loading: fileLoading,
            inline: false,
            onPick: _importFile,
          ),
        ),
        const SizedBox(height: MarkoSpace.md),
        _SourceTile(
          accent: colors.promAccent,
          logo: 'assets/logos/prom.webp',
          title: 'Магазин Prom.ua',
          subtitle: 'Каталог за посиланням на магазин',
          child: _PromForm(
            controller: _urlController,
            busy: busy,
            loading: promLoading,
            inline: false,
            onSubmit: _connectStore,
          ),
        ),
      ],
    );
  }

  /// Both sources report success the same way: the progress and the summary
  /// live on the page behind them.
  Future<void> _importFile() async {
    if (await pickAndImportCatalog(ref) && mounted) widget.onDone?.call();
  }

  Future<void> _connectStore() async {
    final imported = await ref
        .read(catalogImportProvider.notifier)
        .addStore(_urlController.text);
    if (imported && mounted) widget.onDone?.call();
  }
}

/// What the import left behind: the summary, the running sync, the error.
class SourcePanel extends ConsumerWidget {
  const SourcePanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final importState = ref.watch(catalogImportProvider).value;
    final notifier = ref.read(catalogImportProvider.notifier);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (importState?.lastImport != null)
          MarkoInlineMessage(
            message: importState!.lastImport!.summary,
            tone: MarkoMessageTone.success,
            action: TextButton(
              onPressed: notifier.dismissImport,
              child: const Text('Зрозуміло'),
            ),
          ),
        // Поступ синхронізації показує плаваюча капсула над каталогом.
        if (importState?.error != null) ...[
          const SizedBox(height: MarkoSpace.md),
          MarkoInlineMessage(
            message: importState!.error!,
            tone: MarkoMessageTone.error,
            action: TextButton(
              onPressed: notifier.dismissError,
              child: const Text('Сховати'),
            ),
          ),
        ],
      ],
    );
  }
}

/// Contents of the drop box: what we accept and the two ways to hand it over.
class _FileDrop extends StatelessWidget {
  const _FileDrop({
    required this.busy,
    required this.loading,
    required this.inline,
    required this.onPick,
  });

  final bool busy;
  final bool loading;

  /// Desktop can drag a file in; touch only ever taps.
  final bool inline;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final button = MarkoButton(
      label: loading ? 'Завантажуємо...' : 'Обрати файл',
      onPressed: busy ? null : onPick,
      icon: HeroIcons.folderOpen,
      loading: loading,
      expand: !inline,
    );

    if (!inline) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          button,
          const SizedBox(height: MarkoSpace.sm),
          Text(
            'XLSX або CSV до 50 МБ',
            textAlign: TextAlign.center,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.faint),
          ),
        ],
      );
    }

    return Row(
      children: [
        Flexible(
          child: Text(
            'Перетягніть файл',
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ),
        const Spacer(),
        Text(
          'або',
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.faint),
        ),
        const Spacer(),
        button,
      ],
    );
  }
}

class _PromForm extends StatelessWidget {
  const _PromForm({
    required this.controller,
    required this.busy,
    required this.loading,
    required this.inline,
    required this.onSubmit,
  });

  final TextEditingController controller;
  final bool busy;
  final bool loading;

  /// Desktop puts the button next to the field; mobile stacks them.
  final bool inline;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final field = MarkoTextField(
      controller: controller,
      enabled: !busy,
      keyboardType: TextInputType.url,
      labelText: 'Посилання на магазин',
      hintText: 'https://prom.ua/ua/c2847093-kemp.html',
      prefixIcon: HeroIcons.link,
      onSubmitted: (_) => busy ? null : onSubmit(),
    );
    final button = MarkoButton(
      label: 'Імпортувати каталог',
      onPressed: busy ? null : onSubmit,
      icon: HeroIcons.arrowDownTray,
      loading: loading,
      expand: !inline,
    );

    if (inline) {
      return Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Expanded(child: field),
          const SizedBox(width: MarkoSpace.sm),
          button,
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        field,
        const SizedBox(height: MarkoSpace.md),
        button,
      ],
    );
  }
}

/// One ingestion source as a tile: neon accent, its logo washed across the
/// background, and whatever form that source needs inside.
class _SourceTile extends StatefulWidget {
  const _SourceTile({
    required this.accent,
    required this.logo,
    required this.title,
    required this.subtitle,
    required this.child,
    this.monoLogo = false,
  });

  final Color accent;
  final String logo;

  /// Одноколірний гліф без полів — його фарбуємо акцентом джерела.
  final bool monoLogo;
  final String title;
  final String subtitle;
  final Widget child;

  @override
  State<_SourceTile> createState() => _SourceTileState();
}

class _SourceTileState extends State<_SourceTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final accent = widget.accent;
    final radius = BorderRadius.circular(colors.panelRadius);

    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeInOut,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radius,
          border: Border.all(
            color: _hovered ? accent.withValues(alpha: 0.55) : colors.border,
          ),
          boxShadow: [
            if (_hovered)
              BoxShadow(
                color: accent.withValues(alpha: 0.22),
                blurRadius: 24,
                spreadRadius: -6,
                offset: const Offset(0, 6),
              ),
            ...MarkoShadow.card,
          ],
        ),
        foregroundDecoration: BoxDecoration(
          borderRadius: radius,
          gradient: RadialGradient(
            center: Alignment.bottomRight,
            radius: 1.1,
            colors: [
              accent.withValues(alpha: _hovered ? 0.14 : 0.07),
              accent.withValues(alpha: 0),
            ],
          ),
          backgroundBlendMode: BlendMode.srcOver,
        ),
        child: Stack(
          children: [
            Positioned(
              right: -16,
              bottom: -16,
              child: IgnorePointer(
                child: Opacity(
                  opacity: _hovered ? 0.16 : 0.08,
                  child: Image.asset(
                    widget.logo,
                    width: 140,
                    height: 140,
                    fit: BoxFit.contain,
                    color: widget.monoLogo ? accent : null,
                    filterQuality: FilterQuality.medium,
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(MarkoSpace.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      // Гліф іде від краю до краю, тому живе в полях на
                      // підкладці; готовий логотип сам займає весь чіп.
                      Container(
                        width: 28,
                        height: 28,
                        clipBehavior: Clip.antiAlias,
                        padding: widget.monoLogo
                            ? const EdgeInsets.all(4)
                            : EdgeInsets.zero,
                        decoration: BoxDecoration(
                          color: widget.monoLogo
                              ? accent.withValues(alpha: 0.12)
                              : null,
                          borderRadius: BorderRadius.circular(MarkoRadius.sm),
                        ),
                        child: Image.asset(
                          widget.logo,
                          fit: BoxFit.contain,
                          color: widget.monoLogo ? accent : null,
                          filterQuality: FilterQuality.medium,
                        ),
                      ),
                      const SizedBox(width: MarkoSpace.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              widget.title,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: MarkoSpace.xxs),
                            Text(
                              widget.subtitle,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                    color: colors.faint,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: MarkoSpace.md),
                  widget.child,
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
