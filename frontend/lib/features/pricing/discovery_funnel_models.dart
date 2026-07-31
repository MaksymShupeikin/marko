class DiscoveryGateMetric {
  const DiscoveryGateMetric({
    required this.reached,
    required this.terminal,
    required this.survived,
    required this.conditionalPassRate,
    required this.survivalCeilingRatio,
    required this.singleGateUnlockUpperBoundRatio,
  });

  factory DiscoveryGateMetric.fromJson(Map<String, dynamic> json) {
    return DiscoveryGateMetric(
      reached: (json['reached'] as num?)?.toInt() ?? 0,
      terminal: (json['terminal'] as num?)?.toInt() ?? 0,
      survived: (json['survived'] as num?)?.toInt() ?? 0,
      conditionalPassRate: double.tryParse(
        json['conditional_pass_rate']?.toString() ?? '',
      ),
      survivalCeilingRatio: double.tryParse(
        json['survival_ceiling_ratio']?.toString() ?? '',
      ),
      singleGateUnlockUpperBoundRatio: double.tryParse(
        json['single_gate_unlock_upper_bound_ratio']?.toString() ?? '',
      ),
    );
  }

  final int reached;
  final int terminal;
  final int survived;
  final double? conditionalPassRate;
  final double? survivalCeilingRatio;
  final double? singleGateUnlockUpperBoundRatio;
}

class DiscoveryCategoryFunnel {
  const DiscoveryCategoryFunnel({
    required this.category,
    required this.runs,
    required this.totalCandidates,
  });

  factory DiscoveryCategoryFunnel.fromJson(Map<String, dynamic> json) {
    return DiscoveryCategoryFunnel(
      category: json['category']?.toString() ?? 'UNKNOWN',
      runs: (json['runs'] as num?)?.toInt() ?? 0,
      totalCandidates: (json['total_candidates'] as num?)?.toInt() ?? 0,
    );
  }

  final String category;
  final int runs;
  final int totalCandidates;
}

class DiscoveryFunnelSnapshot {
  const DiscoveryFunnelSnapshot({
    required this.correlationId,
    required this.sampledRuns,
    required this.totalCandidates,
    required this.statusCounts,
    required this.coverage,
    required this.gates,
    required this.categories,
  });

  factory DiscoveryFunnelSnapshot.fromJson(Map<String, dynamic> json) {
    final rawGates =
        (json['gates'] as Map<String, dynamic>?) ?? const <String, dynamic>{};
    final rawCategories =
        (json['categories'] as List<dynamic>?) ?? const <dynamic>[];
    return DiscoveryFunnelSnapshot(
      correlationId: json['correlation_id']?.toString(),
      sampledRuns: (json['sampled_runs'] as num?)?.toInt() ?? 0,
      totalCandidates: (json['total_candidates'] as num?)?.toInt() ?? 0,
      statusCounts: Map<String, int>.fromEntries(
        ((json['status_counts'] as Map<String, dynamic>?) ??
                const <String, dynamic>{})
            .entries
            .map(
              (entry) =>
                  MapEntry(entry.key, (entry.value as num?)?.toInt() ?? 0),
            ),
      ),
      coverage:
          (json['coverage'] as Map<String, dynamic>?) ??
          const <String, dynamic>{},
      gates: Map<String, DiscoveryGateMetric>.fromEntries(
        rawGates.entries.map(
          (entry) => MapEntry(
            entry.key,
            DiscoveryGateMetric.fromJson(entry.value as Map<String, dynamic>),
          ),
        ),
      ),
      categories: rawCategories
          .map(
            (value) =>
                DiscoveryCategoryFunnel.fromJson(value as Map<String, dynamic>),
          )
          .toList(growable: false),
    );
  }

  final String? correlationId;
  final int sampledRuns;
  final int totalCandidates;
  final Map<String, int> statusCounts;
  final Map<String, dynamic> coverage;
  final Map<String, DiscoveryGateMetric> gates;
  final List<DiscoveryCategoryFunnel> categories;

  double? get retrievalCoverageRatio =>
      double.tryParse(coverage['retrieval_coverage_ratio']?.toString() ?? '');
}
