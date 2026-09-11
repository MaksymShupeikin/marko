// Демо-точка входу лише для локального перегляду вікна переоцінки:
//
//   flutter run -d chrome -t lib/demo_repricing.dart
//
// Справжній main.dart піднімає Firebase, тож без налаштованого входу вікно
// не побачити взагалі. Тут авторизації немає, а бекенд підставний — той
// самий MockClient, що у віджет-тестах. У збірку застосунку цей файл не
// потрапляє: він окрема ціль, а не частина main.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'core/api_client.dart';
import 'core/app_theme.dart';
import 'features/repricing/repricing_api.dart';
import 'features/repricing/repricing_page.dart';

Map<String, dynamic> _catalog() => {
  'signature': 'c80cfe885018a1b2',
  'item_count': 4901,
  'store_ids': ['store-1'],
};

Map<String, dynamic> _run(String id) => {
  'id': id,
  'sync_run_id': 'sync-$id',
  'scope': 'partial',
  'mode': 'fresh',
  'policy': 'balanced',
  'engine': 'legacy_min_minus',
  'requested_count': 6,
  'catalog': _catalog(),
  'catalog_is_current': true,
  'status': 'completed',
  'progress_current': 6,
  'progress_total': 6,
  'error': null,
  'changed_count': 3,
  'unchanged_count': 1,
  'skipped_count': 2,
  'failed_count': 0,
  'created_at': '2026-09-11T09:15:00Z',
  'started_at': '2026-09-11T09:15:01Z',
  'finished_at': '2026-09-11T09:18:00Z',
};

Map<String, dynamic> _item({
  required String id,
  required String name,
  required String sku,
  required String? outcome,
  String? reason,
  num? oldPrice,
  num? newPrice,
  num? deltaPct,
  String? zone,
  bool drift = false,
  int offers = 12,
}) => {
  'listing_id': id,
  'position': 0,
  'name': name,
  'sku': sku,
  'brand': 'KEMP',
  'store_name': 'Автозапчастини Київ',
  'image_url': null,
  'url': 'https://kemp.prom.ua/p$id.html',
  'currency': 'UAH',
  'status': 'done',
  'outcome': outcome,
  'reason': reason,
  'old_price': oldPrice,
  'new_price': newPrice,
  'delta_abs': null,
  'delta_pct': deltaPct,
  'price_changed_since': drift,
  'zone': zone,
  'tier': null,
  'method': 'legacy_min_minus',
  'confidence': null,
  'offers_total': offers,
  'evidence': null,
  'dismissed': false,
};

ApiClient _demoClient() => ApiClient(
  client: MockClient((request) async {
    final path = request.url.path;
    String body;
    if (path == '/api/v1/reprice/reconciliation') {
      body = jsonEncode({
        'signature_changed': true,
        'previous_signature': 'old12345',
        'kept': 4514,
        'gone': 87,
        'fresh': 340,
      });
    } else if (path == '/api/v1/reprice/preview') {
      body = jsonEncode({
        'catalog': _catalog(),
        'matching': 4901,
        'covered': 387,
        'remaining': 4514,
        'checks_left': 30,
        'last_run_signature': 'old12345',
        'signature_changed': true,
      });
    } else if (path == '/api/v1/reprice/runs' && request.method == 'GET') {
      body = jsonEncode({
        'items': [_run('run-1'), _run('run-0')],
        'total': 2,
        'limit': 20,
        'offset': 0,
      });
    } else if (path.endsWith('/items')) {
      body = jsonEncode({
        'items': [
          _item(
            id: 'a',
            name: 'Амортизатор передній Citroen C4 / Peugeot 307 02- газ',
            sku: '312937',
            outcome: 'changed',
            oldPrice: 1950,
            newPrice: 1780,
            deltaPct: -8.7,
            zone: 'premium',
            offers: 34,
          ),
          _item(
            id: 'b',
            name: 'Амортизатор передній Ford Mondeo III 2000-2007',
            sku: '312783',
            outcome: 'changed',
            oldPrice: 1162,
            newPrice: 1336,
            deltaPct: 15.0,
            zone: 'underpriced',
            offers: 51,
            drift: true,
          ),
          _item(
            id: 'c',
            name: 'Фільтр масляний MANN W 914/2',
            sku: 'W9142',
            outcome: 'unchanged',
            oldPrice: 305,
            newPrice: 305,
            zone: 'mainstream',
            offers: 19,
          ),
          _item(
            id: 'd',
            name: 'Прокладка впускного колектора Peugeot 206 1.4',
            sku: '0348K1',
            outcome: 'no_recommendation',
            reason: 'Тонкий ринок: менше трьох підтверджених цін',
            oldPrice: 480,
            zone: 'mainstream',
            offers: 2,
          ),
          _item(
            id: 'e',
            name: 'Насос паливний VAG 06E145100R',
            sku: '06E145100R',
            outcome: 'no_recommendation',
            reason:
                'Рекомендація нижча за 40% медіани ринку — схоже на хибний мінімум',
            oldPrice: 3900,
            zone: 'premium',
            offers: 13,
          ),
        ],
        'total': 6,
        'limit': 60,
        'offset': 0,
      });
    } else {
      body = jsonEncode(_run('run-1'));
    }
    return http.Response(
      body,
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }),
  baseUrl: 'http://demo.local',
);

void main() {
  runApp(
    ProviderScope(
      overrides: [
        repricingApiProvider.overrideWithValue(RepricingApi(_demoClient())),
      ],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        home: const RepricingPage(),
      ),
    ),
  );
}
