import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
            padding: const EdgeInsets.all(24),
            children: [
              Text(
                'Магазины Prom',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 8),
              const Text(
                'Добавьте ссылку вида https://prom.ua/ua/c123456-store.html',
              ),
              const SizedBox(height: 20),
              _AddStoreCard(
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
                const SizedBox(height: 16),
                _SyncCard(sync: state.activeSync!, job: state.activeJob),
              ],
              if (state.error != null) ...[
                const SizedBox(height: 16),
                MaterialBanner(
                  content: Text(state.error!),
                  leading: const Icon(Icons.error_outline),
                  actions: [
                    TextButton(
                      onPressed: controller.dismissError,
                      child: const Text('Закрыть'),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: 24),
              Row(
                children: [
                  Text(
                    'Подключённые',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const Spacer(),
                  IconButton(
                    tooltip: 'Обновить список',
                    onPressed: controller.refresh,
                    icon: const Icon(Icons.refresh),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              if (state.stores.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      'Магазинов пока нет. Добавьте первый магазин выше.',
                    ),
                  ),
                )
              else
                ...state.stores.map(
                  (store) => Card(
                    child: ListTile(
                      leading: const CircleAvatar(
                        child: Icon(Icons.storefront),
                      ),
                      title: Text(store.displayName),
                      subtitle: Text(
                        '${store.productCount} товаров · ${store.syncDescription}',
                      ),
                      onTap: () => context.pushNamed(
                        'store-products',
                        pathParameters: {'storeId': store.id},
                      ),
                      trailing: IconButton(
                        tooltip: 'Синхронизировать',
                        onPressed: state.isSubmitting || state.hasActiveJob
                            ? null
                            : () => controller.syncStore(store),
                        icon: const Icon(Icons.sync),
                      ),
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

class _AddStoreCard extends StatelessWidget {
  const _AddStoreCard({
    required this.urlController,
    required this.busy,
    required this.onSubmit,
  });

  final TextEditingController urlController;
  final bool busy;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final field = TextField(
              controller: urlController,
              enabled: !busy,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Ссылка на магазин',
                hintText: 'https://prom.ua/ua/c2847093-kemp.html',
              ),
              onSubmitted: (_) => busy ? null : onSubmit(),
            );
            final button = FilledButton.icon(
              onPressed: busy ? null : onSubmit,
              icon: busy
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.add),
              label: const Text('Подключить'),
            );
            if (constraints.maxWidth < 650) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [field, const SizedBox(height: 12), button],
              );
            }
            return Row(
              children: [
                Expanded(child: field),
                const SizedBox(width: 12),
                button,
              ],
            );
          },
        ),
      ),
    );
  }
}

class _SyncCard extends StatelessWidget {
  const _SyncCard({required this.sync, required this.job});

  final StoreSync sync;
  final SyncRun? job;

  @override
  Widget build(BuildContext context) {
    final status = job?.status ?? sync.status;
    return Card(
      color: status == 'failed'
          ? Theme.of(context).colorScheme.errorContainer
          : null,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Импорт каталога: ${job?.statusLabel ?? status}'),
            const SizedBox(height: 10),
            LinearProgressIndicator(value: job?.progress),
            const SizedBox(height: 8),
            Text('Обработано товаров: ${job?.progressCurrent ?? 0}'),
            if (job?.error != null) ...[
              const SizedBox(height: 8),
              Text(job!.error!),
            ],
          ],
        ),
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
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('Повторить')),
          ],
        ),
      ),
    );
  }
}
