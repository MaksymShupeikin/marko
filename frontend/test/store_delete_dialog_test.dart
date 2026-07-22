import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/stores/store_products_page.dart';

void main() {
  testWidgets('requires confirmation before deleting a store', (tester) async {
    bool? confirmed;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              confirmed = await showDialog<bool>(
                context: context,
                builder: (_) => const StoreDeleteDialog(storeName: 'Kemp'),
              );
            },
            child: const Text('Open'),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(find.text('Удалить магазин?'), findsOneWidget);
    expect(find.textContaining('Это действие нельзя отменить'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('confirm-store-delete')));
    await tester.pumpAndSettle();
    expect(confirmed, isTrue);
  });

  testWidgets('allows cancelling store deletion', (tester) async {
    bool? confirmed;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              confirmed = await showDialog<bool>(
                context: context,
                builder: (_) => const StoreDeleteDialog(storeName: 'Kemp'),
              );
            },
            child: const Text('Open'),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();

    expect(confirmed, isFalse);
  });
}
