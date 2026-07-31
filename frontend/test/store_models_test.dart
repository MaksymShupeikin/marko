import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/presentation_formatters.dart';
import 'package:marko_client/features/stores/store_models.dart';

void main() {
  test('parses store and product API models', () {
    final store = StoreSummary.fromJson({
      'id': 'store-id',
      'marketplace': 'prom',
      'external_id': '2847093',
      'name': 'kemp',
      'url': 'https://prom.ua/ua/c2847093-kemp.html',
      'kind': 'owned',
      'product_count': 12,
      'last_synced_at': '2026-07-13T12:00:00Z',
    });
    final product = StoreProduct.fromJson({
      'id': 'product-id',
      'name': 'Product',
      'url': 'https://prom.ua/ua/p1-product.html',
      'sku': 'SKU-1',
      'brand': 'Brand',
      'current_price': '123.45',
      'currency': 'UAH',
      'is_available': true,
      'image_url': 'https://images.prom.ua/product.jpg',
    });

    expect(store.productCount, 12);
    expect(store.lastSyncedAt, isNotNull);
    expect(store.displayName, 'kemp');
    expect(product.price, DecimalValue.parse('123.45'));
    expect(product.isAvailable, isTrue);
    expect(product.imageUrl, 'https://images.prom.ua/product.jpg');
    expect(product.priceLabel, '123.45 UAH');
    expect(product.details, 'Brand · SKU SKU-1 · В наличии');
  });

  test('renders store sync timestamps in the shared human-readable order', () {
    final store = StoreSummary.fromJson({
      'id': 'store-id',
      'external_id': '2847093',
      'name': 'KEMP',
      'url': 'https://prom.ua/ua/c2847093-kemp.html',
      'kind': 'owned',
      'product_count': 12,
      'last_synced_at': '2026-07-13T04:05:00',
    });

    expect(store.syncDescription, 'обновлён 13.07.2026 04:05');
  });

  test('preserves the complete scraper telemetry contract', () {
    final run = SyncRun.fromJson({
      'id': 'run-1',
      'workspace_id': 'workspace-1',
      'store_id': 'store-1',
      'kind': 'store_sync',
      'status': 'running',
      'progress_current': 230,
      'progress_total': 300,
      'error': null,
      'scrape_item_version': 'v2',
      'scrape_state': 'persisting',
      'scrape_deduplicated_submissions': 1,
      'scrape_task_executions': 2,
      'scrape_task_redeliveries': 1,
      'scrape_max_task_executions': 4,
      'scrape_deadline_at': '2026-07-30T12:00:00Z',
      'scrape_owner_task_id': 'internal-task-id',
      'scrape_lease_expires_at': '2026-07-30T11:45:00Z',
      'scrape_checkpoint': {'page': 12},
      'scrape_catalog_pages': 12,
      'scrape_products_extracted': 240,
      'scrape_products_persisted': 230,
      'scrape_duplicate_products': 10,
      'scrape_database_writes': 230,
      'scrape_raw_evidence_bytes': 20480,
      'scrape_structured_completeness': '0.875',
      'scrape_evidence_coverage': '0.91',
      'started_at': '2026-07-30T11:00:00Z',
      'finished_at': null,
      'created_at': '2026-07-30T10:59:00Z',
    });

    expect(run.id, 'run-1');
    expect(run.workspaceId, 'workspace-1');
    expect(run.scrapeState, 'persisting');
    expect(run.taskExecutions, 2);
    expect(run.taskRedeliveries, 1);
    expect(run.maxTaskExecutions, 4);
    expect(run.checkpoint, {'page': 12});
    expect(run.catalogPages, 12);
    expect(run.productsExtracted, 240);
    expect(run.productsPersisted, 230);
    expect(run.duplicateProducts, 10);
    expect(run.databaseWrites, 230);
    expect(run.rawEvidenceBytes, 20480);
    expect(run.structuredCompleteness, 0.875);
    expect(run.evidenceCoverage, 0.91);
    expect(run.deadlineAt, isNotNull);
    expect(run.leaseExpiresAt, isNotNull);
    expect(run.startedAt, isNotNull);
    expect(run.finishedAt, isNull);
  });
}
