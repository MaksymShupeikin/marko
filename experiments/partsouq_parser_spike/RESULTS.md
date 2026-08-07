# PartSouq parser spike — measured result

This is an isolated research artifact. It is not imported by `backend/`, is not
in a worker image and performs no network requests.

## Source-access result

- 7zap was rejected as a parser target. Its published Terms of Service prohibit
  bots, scripts, scrapers, automated extraction and storage of Service Content.
- PartSouq's `robots.txt` only disallowed `/cdn-cgi/`, but one bounded request to
  `https://partsouq.com/en/search/all?q=9091520004` returned HTTP 403. No attempt
  was made to bypass that control.
- The parser therefore accepts only HTML lawfully saved and supplied by an
  operator. The included fixture is synthetic and tests the visible semantic
  shape; it is not a copied PartSouq page and does not prove the current DOM.

## Catalog measurement

Read-only parse and deterministic identity reparse of
`backend/data/kemp_prom_catalog.xlsx`, sheet `Export Products Sheet`:

- 4,901 source rows accounted for;
- 40 rows remain `UNRESOLVED`;
- 39/40 have a product brand value;
- 35/40 have at least one extracted vehicle make;
- 30/40 have at least one extracted vehicle model;
- 40/40 have a description;
- none has a trusted OE/MPN/cross after the identity reparse;
- the import contract has no customer VIN/frame field for these rows.

The names can help a human narrow the search. They cannot produce a supported
PartSouq global lookup: PartSouq documents global search by part number or
VIN/frame, while name search is described inside an already selected vehicle
catalog. A Luna-generated formal name therefore improves presentation but does
not create the missing identity evidence.

## Spike decision

`build_query_plan` permits only a trusted part number or VIN/frame. A name-only
query returns `UNSUPPORTED_NAME_ONLY` with no URL. Parsed substitution numbers
remain external candidates; they are not automatically promoted to confirmed
OE or pricing admission. An identifier invented or inferred by Luna carries
`MODEL_INFERRED` provenance and is also ineligible for a lookup: the model may
copy evidence into the formal record, but it cannot manufacture its own search
key and then use the search result as circular confirmation.
