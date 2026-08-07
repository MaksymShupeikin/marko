# Offline PartSouq parser spike

Purpose: test whether a formal part description could safely recover missing
OE identity from PartSouq without integrating another source into Marko.

## What is included

- `formal_part_query.schema.json`: strict experimental shape for a semantic
  reviewer such as Luna. It separates the normalized name, vehicle, position,
  side, known identifiers and missing evidence.
- `examples/luna_formal_name_only_caliper.json`: a formal projection of one
  real unresolved catalog description. It deliberately contains no invented
  OE number and therefore remains ineligible for a PartSouq request.
- `partsouq_spike.py`: an offline HTML identity parser and a fail-closed query
  planner. It contains no HTTP client.
- `fixtures/search_9091520004.synthetic.html`: a small synthetic fixture based
  on PartSouq's own public FAQ example.
- `test_partsouq_spike.py`: unit tests for part-number/VIN lookup eligibility,
  name-only refusal, substitution parsing and seller deduplication.
- `RESULTS.md`: source-access evidence and the 40-row catalog measurement.

## Run

```bash
cd experiments/partsouq_parser_spike
python3 -m unittest -v

cd ../../backend
PYTHONPATH=src .venv/bin/python ../experiments/partsouq_parser_spike/measure_catalog.py
```

## Boundary

This experiment does not authorize scraping. Before any live integration,
obtain a documented API/data license or written permission from the provider,
replace the synthetic fixture with an approved pinned response, and add source
provenance, cache identity, rate limits, redelivery tests and manual labels.
