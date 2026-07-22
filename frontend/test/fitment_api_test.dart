import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/fitment/fitment_api.dart';

void main() {
  test('loads workspace fitment candidates for one catalog item', () async {
    final api = FitmentApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/fitment/products/catalog-1/candidates',
          );
          expect(request.url.queryParameters['limit'], '250');
          return http.Response(
            jsonEncode({
              'items': <dynamic>[],
              'total': 0,
              'analysis_id': null,
              'limit': 250,
              'offset': 0,
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final page = await api.listCandidates('catalog-1');

    expect(page.items, isEmpty);
    expect(page.analysisId, isNull);
  });

  test('records a human fitment decision with an idempotency key', () async {
    final api = FitmentApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/fitment/candidates/assessment-1/review',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['decision'], 'mark_candidate_incompatible');
          expect(body['reason_code'], 'wrong_side');
          expect(body['comment'], 'Левая деталь');
          expect((body['idempotency_key'] as String).length, 64);
          return http.Response('{}', 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.reviewCandidate(
      'assessment-1',
      decision: 'mark_candidate_incompatible',
      reasonCode: 'wrong_side',
      comment: 'Левая деталь',
    );
  });

  test(
    'treats a missing latest recommendation as an empty review state',
    () async {
      final api = FitmentApi(
        ApiClient(
          client: MockClient((request) async {
            expect(
              request.url.path,
              '/api/v1/fitment/products/catalog-1/recommendation',
            );
            return http.Response(jsonEncode({'detail': 'not found'}), 404);
          }),
          baseUrl: 'http://api.test',
        ),
      );

      expect(await api.getRecommendation('catalog-1'), isNull);
    },
  );

  test(
    'records recommendation review without requesting publication',
    () async {
      final api = FitmentApi(
        ApiClient(
          client: MockClient((request) async {
            expect(
              request.url.path,
              '/api/v1/fitment/recommendations/rec-1/accept',
            );
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['approved_price'], 920.0);
            expect(body['accept_with_modification'], isTrue);
            expect(body['allow_below_floor'], isTrue);
            expect(body['below_floor_warning_confirmed'], isTrue);
            expect(body.containsKey('publish'), isFalse);
            expect(body.containsKey('automatic_price_change_allowed'), isFalse);
            return http.Response('{}', 201);
          }),
          baseUrl: 'http://api.test',
        ),
      );

      await api.reviewRecommendation(
        'rec-1',
        operation: 'accept',
        reasonCode: 'other',
        approvedPrice: 920,
        allowBelowFloor: true,
        belowFloorWarningConfirmed: true,
      );
    },
  );
}
