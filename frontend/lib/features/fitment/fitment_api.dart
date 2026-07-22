import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'fitment_models.dart';

class FitmentApi {
  const FitmentApi(this._client);

  final ApiClient _client;

  Future<FitmentCandidatePage> listCandidates(String catalogItemId) async {
    final payload = await _client.getJson(
      '/api/v1/fitment/products/$catalogItemId/candidates',
      queryParameters: const {'limit': '250'},
    );
    return FitmentCandidatePage.fromJson(payload as Map<String, dynamic>);
  }

  Future<void> reviewCandidate(
    String assessmentId, {
    required String decision,
    required String reasonCode,
    String? comment,
    Map<String, String> evidenceVerdicts = const {},
  }) async {
    final idempotencyKey = _idempotencyKey('$assessmentId:$decision');
    await _client.postJson(
      '/api/v1/fitment/candidates/$assessmentId/review',
      body: {
        'idempotency_key': idempotencyKey,
        'decision': decision,
        'reason_code': reasonCode,
        if (comment != null && comment.trim().isNotEmpty)
          'comment': comment.trim(),
        'evidence_verdicts': evidenceVerdicts.entries
            .map(
              (entry) => {
                'evidence_claim_id': entry.key,
                'verdict': entry.value,
              },
            )
            .toList(growable: false),
      },
    );
  }

  Future<FitmentMarketRecommendation?> getRecommendation(
    String catalogItemId,
  ) async {
    try {
      final payload = await _client.getJson(
        '/api/v1/fitment/products/$catalogItemId/recommendation',
      );
      return FitmentMarketRecommendation.fromJson(
        Map<String, dynamic>.from(payload as Map),
      );
    } on ApiException catch (error) {
      if (error.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<FitmentMarketRecommendation> generateRecommendation(
    String catalogItemId, {
    required String analysisId,
    String strategy = 'balanced',
  }) async {
    final payload = await _client.postJson(
      '/api/v1/fitment/products/$catalogItemId/recommendations',
      body: {
        'idempotency_key': _idempotencyKey(
          '$catalogItemId:$analysisId:$strategy',
        ),
        'analysis_id': analysisId,
        'strategy': strategy,
      },
    );
    return FitmentMarketRecommendation.fromJson(
      Map<String, dynamic>.from(payload as Map),
    );
  }

  Future<void> reviewRecommendation(
    String recommendationId, {
    required String operation,
    required String reasonCode,
    double? approvedPrice,
    String? comment,
    bool allowBelowFloor = false,
    bool belowFloorWarningConfirmed = false,
  }) async {
    if (!{'accept', 'reject', 'defer', 'research'}.contains(operation)) {
      throw ArgumentError.value(operation, 'operation');
    }
    await _client.postJson(
      '/api/v1/fitment/recommendations/$recommendationId/$operation',
      body: {
        'idempotency_key': _idempotencyKey(
          '$recommendationId:$operation:${approvedPrice ?? ''}',
        ),
        'approved_price': ?approvedPrice,
        'reason_code': reasonCode,
        if (comment != null && comment.trim().isNotEmpty)
          'comment': comment.trim(),
        'accept_with_modification':
            operation == 'accept' && approvedPrice != null,
        'allow_below_floor': allowBelowFloor,
        'below_floor_warning_confirmed': belowFloorWarningConfirmed,
      },
    );
  }

  Future<void> markSellerRelation(
    FitmentCandidate candidate, {
    required String relation,
    required String reason,
  }) async {
    if (!{'own', 'related'}.contains(relation)) {
      throw ArgumentError.value(relation, 'relation');
    }
    await _client.postJson(
      '/api/v1/fitment/sellers/${Uri.encodeComponent(candidate.sellerId)}/mark-$relation',
      body: {
        'idempotency_key': _idempotencyKey(
          '${candidate.sellerId}:$relation:$reason',
        ),
        'seller_name': candidate.sellerName,
        'confidence': relation == 'own' ? 1 : 0.9,
        'evidence': [
          {
            'type': 'human_operator_decision',
            'observation_id': candidate.observationId,
            'assessment_id': candidate.id,
          },
        ],
        'reason': reason,
      },
    );
  }

  String _idempotencyKey(String scope) {
    final nonce = DateTime.now().microsecondsSinceEpoch;
    return sha256.convert(utf8.encode('$scope:$nonce')).toString();
  }
}

final fitmentApiProvider = Provider<FitmentApi>((ref) {
  return FitmentApi(ref.watch(apiClientProvider));
});
