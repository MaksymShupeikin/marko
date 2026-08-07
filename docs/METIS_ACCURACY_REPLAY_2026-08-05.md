# Metis accuracy replay — 2026-08-05

## Scope

Read-only replay of persisted `catalog_discovery_offers` that were previously
stored as `PRICING_EVIDENCE`.  The replay did not update PostgreSQL, delete
offers, or change a catalog price.  It applied the current deterministic
candidate gates (`deterministic-candidate-gates-v2-semantic-domain`) and the
shared semantic safety gate (`semantic-features-v40-damaged-condition`,
`semantic-pricing-gate-v12-structured-identity-admission`).

The current persisted-market boundary is v12. It closes a material admission
bug found after the v9 replay: the market helper used to replace every
non-pricing candidate-selection outcome with `PRICING_EVIDENCE`. A verified
OE could therefore bypass a category block, used/remanufactured condition,
dismantler seller, package/variant mismatch, or applicability conflict. Only
strategy-only outcomes (`OWN_BRAND`, `TIER_UNKNOWN`, and
`PREMIUM_NOT_CALIBRATED`) may be normalized for the semantic snapshot; all
identity and condition hard stops are preserved. The version bump invalidates
older persisted semantic snapshots until they are freshly collected or
re-enriched under v12.

The v12 boundary additionally requires an explicit identity-admission trace in
the snapshot. An ordinary title/description token may remain `VERIFIED` for
discovery and manual review, but it cannot authorize automatic pricing without
structured, retained-detail, confirmed-cross, or authoritative Prom grouping
evidence. The version bump invalidates v11 snapshots after this fix.

The calculation adapter enforces the same rule, not only calibration:
observations without a current `PRICING_EVIDENCE/OK` snapshot are converted to
`SEMANTIC_GATE_NOT_CURRENT` and excluded from the target cohort (and from the
KEMP reference lane) unless an explicit legacy replay is being rendered. This
prevents an old `automatic_eligible=true` scalar from reviving an offer after a
new safety rule is deployed.

The v12 semantic gate retains the v6/v7 precision boundaries for ordinary
search/discovery hits: a typed seed part with an untyped candidate remains
manual-review only; an OE found only in free-form description is not automatic
identity evidence; and a title stuffed with multiple OE-like numbers is held
for review.  The Prom Motors source adapter may bypass only these three
identity-context restrictions when its marketplace grouping is explicitly
authoritative; semantic contradictions still fail closed.

The v12 boundary additionally holds ordinary search hits with an explicit
vehicle make/model/generation conflict for manual review.  Verified exact/cross
OE evidence or an authoritative Prom part-code grouping may bypass those
vehicle-application conflicts, while engine and year conflicts remain
review-only.  A typed semantic family must now also be present on both sides
for automatic candidate admission.

The persisted gate is now bound to the candidate's immutable source locator.
When the ORM observation has `source_listing_id` and `raw_capture_id`, the
calibration, pricing, and OE-reenrichment boundaries require both values in
`candidate_snapshot.source_locator` to match.  A current `PRICING_EVIDENCE/OK`
JSON object copied from another listing or capture therefore fails closed as
`SEMANTIC_GATE_NOT_CURRENT`; it cannot be reused to manufacture a priceable
observation.  This is an integrity/false-admission safeguard, not a new market
precision estimate.

The replay used the configured tier-agnostic selection mode only to isolate
identity/domain behavior.  It is not a production precision estimate: the
rows have no independent human labels and most were collected under older
selection rules.  Because this archive contains offer rows but not the
frozen seed-side package/unit fields, the optional v7 completeness admission
was measured separately in the persisted path rather than pretending those
fields were present in this historical replay.

The same semantic gate is now also applied in the main
`market_collection._persist_payload_observations` path.  A persisted market
observation therefore cannot retain `comparability_hard_gate_result=PASS` or
`automatic_eligible=true` when this gate returns a semantic review/config
failure.  The candidate remains stored for operator review with its gate
reason in the review snapshot; no catalog price is changed.

The pricing engine now applies the persisted `ComparisonEvidence` hard gate to
the KEMP reference lane as well.  A KEMP-labelled observation with missing or
conflicting comparability evidence is excluded from the diagnostic reference
set instead of becoming an evidence bypass.  The explicit legacy-replay path
remains replayable, but it cannot grant new automatic authority.

The persisted observation flag is also cohort-scoped: owned storefronts,
KEMP-reference rows, used listings, and explicit manual/tier exclusions are
never marked `automatic_eligible=true`, even when their raw fields are
complete.  They remain available for diagnostics but cannot be mistaken for
target-market pricing evidence.  The calibration selector has one explicit
exception for a fully verified `KEMP_REFERENCE` row: it may serve as the
reference anchor for a tier coefficient, while the engine still excludes it
from the target-market median and recommendation cohort.  This keeps the two
sets disjoint without making calibration impossible.

Calibration now also checks the immutable `candidate_snapshot.semantic_gate`
trace itself (`PRICING_EVIDENCE` + `OK`); scalar `automatic_eligible` and
`comparability_hard_gate_result` fields alone cannot manufacture a coefficient.
Legacy rows without that trace remain review-only until a fresh,
provenance-bound collection produces the missing semantic evidence.

## Measured result

| Previous persisted status | Replay status | Rows |
|---|---:|---:|
| `PRICING_EVIDENCE` | `PRICING_EVIDENCE` | 3,859 |
| `PRICING_EVIDENCE` | `REFERENCE_ONLY` | 2,855 |
| `PRICING_EVIDENCE` | `REJECTED` | 1,759 |
| **Total replayed** |  | **8,473** |

The new priceable share is `3,859 / 8,473 = 0.4554`.  The reduction is
deliberate: a candidate that cannot clear the domain/identity/semantic safety
boundary remains visible for review but cannot affect a recommendation.

The main demotion/rejection reasons were:

| Reason | Rows |
|---|---:|
| `WEAK_NUMERIC_IDENTITY` | 984 |
| `CATEGORY_DOMAIN_UNCONFIRMED` | 78 |
| `CATEGORY_NOT_AUTOPARTS` | 435 |
| `SEMANTIC_CONFLICT` | 518 |
| `SEMANTIC_UNCONFIRMED` | 438 |
| `SEMANTIC_AMBIGUOUS_REVIEW` | 28 |
| `SEMANTIC_FITMENT_CONFLICT_REVIEW` | 414 |
| `SEMANTIC_SUBTYPE_UNCONFIRMED` | 61 |
| `OEM_STUFFED_REVIEW` | 334 |
| `OEM_NOT_FOUND` | 1,324 |

The replay also includes the follow-up taxonomy hardening: explicit
`generic_cooling_fan_motor` versus `engine_cooling_fan` pairs are held as
semantic conflicts; Ukrainian/Russian wheel-bearing wording is classified as
`wheel_bearing` instead of a generic bearing; and known ambiguous subtype
pairs (for example sliding-door bracket versus roller) remain visible but are
held as `SEMANTIC_AMBIGUOUS_REVIEW`. A candidate that proves only the broad
part family while the seed asserts a concrete subtype is now held as
`SEMANTIC_SUBTYPE_UNCONFIRMED`. Explicit engine or year-interval conflicts are
held as `SEMANTIC_FITMENT_CONFLICT_REVIEW`; ordinary-search vehicle
make/model/generation conflicts use the same manual-review boundary, while
verified OE evidence may pass them as a legitimate shared application. These
are deterministic safety-boundary effects, not price updates.

## Concrete false-positive classes covered

- numeric collisions with vitamins, knives, photo backdrops, clothing and
  well-water pumps;
- a filter returned for a power-steering pulley;
- a mirror or wiper blade returned for a radiator/gas spring;
- radiator expansion tanks returned for a radiator assembly;
- explicit package/unit conflicts (for example one seal versus a set of eight);
- short numeric identifiers whose candidate title contains no recoverable part
  family evidence.
- a temperature sensor versus a sensor connector when the marketplace copied
  the same OE;
- a window-control module versus a window switch when the marketplace copied
  the same OE.
- a damaged/bent offer that repeats the exact OE but is not a usable price.

The persisted pricing path has one additional v12 fail-closed boundary:
package quantity and unit basis must be explicitly comparable, and a verified
cross-OE path must also resolve the category-specific analogue dimensions
declared by the semantic extractor (for example radiator geometry/ports/engine
or thermostat opening temperature/housing/engine).  Missing evidence produces
`SEMANTIC_PRICING_EVIDENCE_INCOMPLETE`; the offer remains visible for operator
review but cannot affect calibration or a recommendation.  The archived
discovery rows above do not contain the frozen seed fields required for this
new check, so their 3,859-row figure is a v6 baseline, not a v12 coverage claim.
The conservative v12 probe correctly admits no such row until the catalog seed
captures those unit facts.  The v12 gate also keeps any multi-valued sellable
assertion (for example left/right, multiple package counts, multiple pin
counts, or multiple complete geometry vectors) in
`SEMANTIC_AMBIGUOUS_VALUES_REVIEW`.  An authoritative OE without a typed part
family is likewise discovery-visible but not priceable.

The v12 admission boundary also promotes explicit conflicts in dimensions that
are required by the typed category, even where the generic extractor keeps the
dimension soft because marketplace wording is noisy. Thus a steering reservoir
with contradictory port counts, or a radiator with contradictory
category-required inlet/outlet facts, remains visible but is not priceable.
The same semantic gate version is required by calibration and OE re-enrichment;
an older or hand-constructed `PRICING_EVIDENCE/OK` trace cannot create a new
coefficient.

### Identity namespace correction (2026-08-06)

The persisted path now binds the customer query to an explicit identity
namespace: `OE`, `MPN`, `PART_NUMBER`, `CROSS` or `UNKNOWN`. `MPN_ONLY` rows
are no longer represented by the same raw `comparison_identity_key` as an OE
row. Exact MPN keys are namespaced (`MPN:<normalized>`), and an MPN candidate
may enter automatic pricing only when its own retained evidence contains a
native manufacturer-part-number, candidate-part-number, SKU or verified detail
page value. A field labelled `OE` alone is insufficient for an MPN seed.

`PART_NUMBER` and unknown seeds remain manual until an explicit OE or confirmed
one-hop cross establishes the identity. The semantic snapshot stores the
namespace version, seed/verified namespaces, verification status and the bound
identity key. Calculation, calibration and re-enrichment require this proof for
real persisted observations; legacy snapshots without it fail closed to manual
review. This removes a concrete false-admission path where a supplier article
such as `313452` could be relabelled as an OE and collide with an unrelated
market cohort.

### Owned-network and cross persistence correction (2026-08-06)

`persist_cross_links_for_run` now uses only the latest
`ObservationTierClassification`, requires `CatalogItem.identity_status` to be
`OE_CONFIRMED`, and excludes both `OWNED_STORE` classifications and seller IDs
registered as owned in the workspace. The previous broad observation query could
feed the four customer Prom storefronts into the description-cross stage; their
identical cards could then look like independent cross confirmations. Persisted
Path-2 edges additionally require at least two stable seller IDs. Display-name
differences alone remain diagnostic evidence and cannot widen automatic identity.

The confirmed-cross reader now requires an explicit
`validation_details.automatic_eligible=true` admission flag even for the
customer catalog identity snapshot lane. The snapshot method/source remains
authoritative, but a row that is only labelled `CONFIRMED` without the
immutable admission decision is ignored and must be regenerated. This closes
the source-level shortcut where a partially written identity row could widen
the one-hop graph.

The v40 component/condition probe over the 292 unlabeled historical rows holds
the two copied-OE component cases above as `REFERENCE_ONLY` with
`SEMANTIC_CONFLICT`. In the production completeness mode, none of those
historical rows is promoted because the archive does not contain the frozen
package/unit evidence. This is fail-closed safety evidence, not a precision
estimate: the rows still have no independent labels.

An enriched replay of 405 locked-review rows (including candidate condition,
package, fitment, characteristics and image references) likewise produced
`REFERENCE_ONLY` for all 405 rows under the production completeness contract:
223 were incomplete, 137 had semantic conflicts, 30 had fitment conflicts,
and the remainder were ambiguous/unconfirmed. This confirms that missing
commercial evidence cannot silently become pricing evidence; it does not mean
that all 405 offers are wrong.

The result is not a claim that every remaining `PRICING_EVIDENCE` row is
correct.  Independent labels and a representative 200-product shadow are
still required before reporting production precision/recall.  Automatic price
changes and publication are out of scope: the application remains
advisory-only, and an operator must make any price change manually.  No code
path in this change writes a recommendation into `CatalogItem.current_price`.
