import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import 'store_models.dart';
import 'stores_controller.dart';

class StoresPage extends ConsumerStatefulWidget {
  const StoresPage({super.key});

  @override
  ConsumerState<StoresPage> createState() => _StoresPageState();
}

class _StoresPageState extends ConsumerState<StoresPage> {
  final _urlController = TextEditingController();

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncState = ref.watch(storesControllerProvider);
    final controller = ref.read(storesControllerProvider.notifier);

    return GestureDetector(
      onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
      child: asyncState.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) =>
            _RetryView(message: error.toString(), onRetry: controller.refresh),
        data: (state) => RefreshIndicator(
          onRefresh: controller.refresh,
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
            children: [
              Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1120),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const _PageHeading(),
                      const SizedBox(height: 24),
                      _AddStorePanel(
                        urlController: _urlController,
                        busy: state.isSubmitting,
                        onSubmit: () async {
                          final accepted = await controller.addStore(
                            _urlController.text,
                          );
                          if (accepted && mounted) _urlController.clear();
                        },
                      ),
                      if (state.activeSync != null) ...[
                        const SizedBox(height: 14),
                        _SyncPanel(
                          sync: state.activeSync!,
                          job: state.activeJob,
                        ),
                      ],
                      if (state.error != null) ...[
                        const SizedBox(height: 14),
                        MarkoInlineMessage(
                          message: state.error!,
                          tone: MarkoMessageTone.error,
                          action: TextButton(
                            onPressed: controller.dismissError,
                            child: const Text('Закрыть'),
                          ),
                        ),
                      ],
                      const SizedBox(height: 30),
                      _StoresHeading(
                        count: state.stores.length,
                        onRefresh: controller.refresh,
                      ),
                      const SizedBox(height: 12),
                      if (state.stores.isEmpty)
                        const _EmptyStores()
                      else
                        MarkoPanel(
                          padding: EdgeInsets.zero,
                          child: Column(
                            children: [
                              for (
                                var index = 0;
                                index < state.stores.length;
                                index++
                              ) ...[
                                _StoreRow(
                                  store: state.stores[index],
                                  syncDisabled:
                                      state.isSubmitting || state.hasActiveJob,
                                  onOpen: () => context.pushNamed(
                                    'store-products',
                                    pathParameters: {
                                      'storeId': state.stores[index].id,
                                    },
                                  ),
                                  onSync: () =>
                                      controller.syncStore(state.stores[index]),
                                ),
                                if (index < state.stores.length - 1)
                                  const Divider(),
                              ],
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PageHeading extends StatelessWidget {
  const _PageHeading();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Магазины Prom',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 7),
        Text(
          'Подключайте каталоги и управляйте их синхронизацией.',
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
        ),
      ],
    );
  }
}

class _AddStorePanel extends StatelessWidget {
  const _AddStorePanel({
    required this.urlController,
    required this.busy,
    required this.onSubmit,
  });

  final TextEditingController urlController;
  final bool busy;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: colors.brandSoft,
                  borderRadius: BorderRadius.circular(9),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.add_business_outlined,
                  size: 19,
                  color: colors.brand,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Подключить магазин',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Вставьте публичную ссылку на магазин prom.ua.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          LayoutBuilder(
            builder: (context, constraints) {
              final field = TextField(
                controller: urlController,
                enabled: !busy,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(
                  labelText: 'Ссылка на магазин',
                  hintText: 'https://prom.ua/ua/c2847093-kemp.html',
                  prefixIcon: Icon(Icons.link_rounded, size: 20),
                ),
                onSubmitted: (_) => busy ? null : onSubmit(),
              );
              final button = MarkoButton(
                label: 'Подключить',
                onPressed: busy ? null : onSubmit,
                icon: Icons.add_rounded,
                loading: busy,
                expand: constraints.maxWidth < 650,
              );
              if (constraints.maxWidth < 650) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [field, const SizedBox(height: 12), button],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(child: field),
                  const SizedBox(width: 12),
                  button,
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _SyncPanel extends StatelessWidget {
  const _SyncPanel({required this.sync, required this.job});

  final StoreSync sync;
  final SyncRun? job;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final status = job?.status ?? sync.status;
    final failed = status == 'failed';
    final completed = status == 'completed';
    final foreground = failed
        ? colors.negative
        : completed
        ? colors.positive
        : colors.brand;
    final background = failed
        ? colors.negativeSoft
        : completed
        ? colors.positiveSoft
        : colors.brandSoft;

    return MarkoPanel(
      color: background,
      borderColor: background,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                failed
                    ? Icons.error_outline_rounded
                    : completed
                    ? Icons.check_circle_outline_rounded
                    : Icons.sync_rounded,
                size: 19,
                color: foreground,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Импорт каталога: ${job?.statusLabel ?? status}',
                  style: Theme.of(
                    context,
                  ).textTheme.titleMedium?.copyWith(color: foreground),
                ),
              ),
              Text(
                '${job?.progressCurrent ?? 0} товаров',
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(color: foreground),
              ),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: job?.progress,
            color: foreground,
            backgroundColor: colors.surface.withValues(alpha: 0.7),
          ),
          if (job?.error != null) ...[
            const SizedBox(height: 10),
            Text(
              job!.error!,
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

class _StoresHeading extends StatelessWidget {
  const _StoresHeading({required this.count, required this.onRefresh});

  final int count;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      children: [
        Text('Подключённые', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(width: 9),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: colors.surfaceMuted,
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            count.toString(),
            style: Theme.of(context).textTheme.labelMedium,
          ),
        ),
        const Spacer(),
        IconButton(
          tooltip: 'Обновить список',
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh_rounded, size: 19),
        ),
      ],
    );
  }
}

class _StoreRow extends StatelessWidget {
  const _StoreRow({
    required this.store,
    required this.syncDisabled,
    required this.onOpen,
    required this.onSync,
  });

  final StoreSummary store;
  final bool syncDisabled;
  final VoidCallback onOpen;
  final VoidCallback onSync;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          child: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: colors.surfaceMuted,
                  borderRadius: BorderRadius.circular(10),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.storefront_outlined,
                  size: 20,
                  color: colors.ink,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      store.displayName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 3),
                    Text(
                      store.syncDescription,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                decoration: BoxDecoration(
                  color: colors.surfaceMuted,
                  borderRadius: BorderRadius.circular(7),
                ),
                child: Text(
                  '${store.productCount} товаров',
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: colors.ink),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                tooltip: 'Синхронизировать',
                onPressed: syncDisabled ? null : onSync,
                icon: const Icon(Icons.sync_rounded, size: 19),
              ),
              Icon(Icons.chevron_right_rounded, color: colors.muted, size: 20),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyStores extends StatelessWidget {
  const _EmptyStores();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 34),
      child: Column(
        children: [
          Icon(Icons.storefront_outlined, color: colors.muted, size: 28),
          const SizedBox(height: 12),
          Text(
            'Магазинов пока нет',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            'Добавьте первый магазин по ссылке выше.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _RetryView extends StatelessWidget {
  const _RetryView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Column(
            children: [
              MarkoInlineMessage(
                message: message,
                tone: MarkoMessageTone.error,
              ),
              const SizedBox(height: 14),
              MarkoButton(label: 'Повторить', onPressed: onRetry),
            ],
          ),
        ),
      ),
    );
  }
}
