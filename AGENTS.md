# Marko + Metis repository instructions

## Mandatory end-of-response contract (Section 15.1)

Every substantive project response must end with the Section 15.1 footer. Use
the current task's real stage identity; never invent a stage number. If the
identity is unavailable, use `UNASSIGNED_CURRENT_STAGE`, record
`missing_stage_identity` under unknowns, and return `BLOCKED` when that missing
identity prevents a truthful gate.

The final blocks, in this exact order, are:

1. `STAGE_RESULT`
2. `BLOCKERS`
3. `NEXT_STAGE`
4. `STOP_GATE_<NORMALIZED_STAGE_ID> = PASS|FAIL|BLOCKED|NO_GO`
5. `MACHINE_READABLE_SUMMARY` containing one final fenced YAML document

The stop-gate is the last human-readable status line. A Section 16
`MACHINE_READABLE_SUMMARY` YAML document must follow it and must be the final
substantive block. Do not start or authorize `NEXT_STAGE` in the same response.
The primary status must use precedence `NO_GO > BLOCKED > FAIL > PASS`. Keep
current-stage success separate from production readiness: an audit can pass
while production remains blocked.

Before publishing a substantive response:

1. Create or update an `end_of_response` manifest using contract version
   `15.1`.
2. Validate it with the repository validator.
3. Render the canonical footer from that same manifest.
4. Create the Section 16 `1.1.0` manifest from the same evidence.
5. Validate the complete response against both manifests.
6. Repair every reported issue; do not publish a knowingly invalid result.

```bash
cd backend
uv run validate-response-footer --manifest ../docs/examples/end_of_response_prompt_15_013.yaml
uv run validate-response-footer --manifest MANIFEST.yaml --render
uv run validate-response-footer --manifest MANIFEST.yaml --footer RESPONSE.md
uv run validate-machine-summary --manifest MACHINE_SUMMARY.yaml
uv run validate-machine-summary \
  --manifest MACHINE_SUMMARY.yaml \
  --footer-manifest MANIFEST.yaml \
  --response RESPONSE.md
```

`NONE_VERIFIED` is allowed only after a complete blocker assessment. Unknown or
unassessed values must remain explicit. Production readiness requires separate
representative E5 evidence and closed hard gates.

The Section 15 normative implementation and validation matrix are in
`docs/PROMPT_15_012_END_OF_RESPONSE_CONTRACT.md`. The typed models, renderer,
cross-field validator, and CLI are in
`backend/src/marko/governance/response_footer.py` and
`backend/src/marko/governance/response_footer_cli.py`.

The Section 16 strict schema, arithmetic, YAML safety rules, reverse trace, and
combined-response validator are documented in
`docs/PROMPT_15_013_MACHINE_READABLE_SUMMARY.md` and implemented in
`backend/src/marko/governance/machine_summary_models.py`,
`backend/src/marko/governance/machine_summary.py`, and
`backend/src/marko/governance/machine_summary_cli.py`. Nothing may follow the
closing Section 16 YAML fence in the substantive response.
