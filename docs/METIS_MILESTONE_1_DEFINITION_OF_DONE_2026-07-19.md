# METIS Milestone 1 — Definition of Done

Date: 2026-07-19  
Owner: Metis  
Status: normative pilot contract  
Commercial positioning: market-positioning and decision-prioritization report, not an autonomous profit optimizer

## 1. Customer outcome

Milestone 1 is done when Yuri receives a reproducible per-position report that
separates three states:

1. `ACTIONABLE` — the evidence contract is satisfied and a price/action may be
   shown;
2. `REVIEW_REQUIRED` — evidence exists, but a match, tier, condition, or
   availability label still needs an operator;
3. `INSUFFICIENT_DATA` — no recommendation is emitted.

The report may prioritize listings and explain market position. It must not
claim demand elasticity, stock optimization, margin optimization, or guaranteed
revenue uplift because those inputs and causal evidence are outside Milestone 1.

## 2. Required customer inputs

| Input | Required state |
|---|---|
| Yuri catalogue/export | Stable listing ID, title, own OE, category, brand, own price, currency, public URL |
| Owned identities | Every owned Prom `seller_id` and storefront URL; owned seller is excluded by identity, not by brand |
| Market scope | Country, currency, product condition, included/excluded seller policy |
| Tier policy | Customer-approved brand/tier dictionary with approver, version, and effective date |
| Review labels | Independent `MATCH/NOT_MATCH/UNCERTAIN`, tier, condition, and availability labels for the validation sample |
| Commercial constraints | Minimum margin/floor/ceiling only if they are intended to constrain recommendations |

No field may be silently inferred when its absence can change a price action.

## 3. Included deliverables

- exact-OE discovery with normalized OE and raw evidence provenance;
- independent-seller counting using stable `seller_id`, with normalized seller
  name only as a fallback;
- owned-seller exclusion while retaining independent KEMP listings as a
  separate same-tier signal;
- availability and used/refurbished fail-closed filtering;
- robust market-dispersion statistics for evidence that passes the matching
  contract;
- per-position evidence count, confidence state, reason codes, and abstention;
- pinned inputs, hashes, offline replay, and a human-review workbook;
- one reviewed pilot result and one deterministic rerun after accepted label
  corrections.

## 4. Explicitly excluded

- cross/OE analog expansion as an automatic pricing input before independent
  match and tier validation;
- inventory, turnover, conversion, advertising, demand-elasticity, or margin
  optimization without the corresponding customer data;
- automatic approval of LLM-generated brand/tier labels;
- production SLA, continuous monitoring, support subscription, and recurring
  reruns unless separately contracted;
- a claim that more discovery candidates equal commercial lift.

## 5. Acceptance criteria

| ID | Criterion | Required evidence |
|---|---|---|
| DOD-01 | 100% of accepted input positions end in `ACTIONABLE`, `REVIEW_REQUIRED`, or `INSUFFICIENT_DATA`; no silent drop | input/output reconciliation |
| DOD-02 | Owned seller offers are absent from market calculations; independent KEMP offers remain distinguishable | seller-ID audit |
| DOD-03 | A confident recommendation requires at least two independent, available, non-used valid sellers | automated gate test and reviewed sample |
| DOD-04 | Exact-match precision is measured on independent labels and is at least 0.98; the labeled sample size and Wilson interval are reported | completed offer review |
| DOD-05 | Tier-aware pricing remains disabled until tier precision is measured on approved labels and reaches the customer-approved threshold | approved tier policy and completed tier review |
| DOD-06 | Every cross-derived row carries link provenance and remains `pricing_eligible=false` until match, category, and tier labels pass | replay output and tests |
| DOD-07 | No audited erroneous upward recommendation is emitted; an unresolved case abstains | recommendation audit |
| DOD-08 | Repeated execution over the same pinned inputs produces identical decision datasets and performs zero network requests | manifests and SHA-256 comparison |
| DOD-09 | The report states coverage, match precision, tier precision, confident-recommendation share, and erroneous-upward count without replacing unknowns by zero | report/workbook inspection |
| DOD-10 | Backend lint and the complete automated test suite pass | `ruff` and `pytest` output |

Criterion DOD-04 is a pilot quality threshold, not a claim that the current
unlabeled 30-OE sample already meets it. DOD-05 deliberately leaves the tier
threshold customer-approved because the current runtime has no approved
non-KEMP tier dictionary.

## 6. Commercial completion rule

Milestone 1 may be accepted and invoiced only for the deliverables above. A
cross-expansion module is a separate commercial item only after the same-set A/B
review proves a useful lift in valid independent sellers or actionable
positions, while match precision and unsafe recommendation rate stay within the
approved thresholds.

