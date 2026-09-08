# Request identity provenance start

text_contracts owns only Pipeline.normalize and store._dataset function blocks plus new scripts/test_tushare_request_identity.py in isolated codex/tushare-text merged8249f6c. Parent owns all other pipeline/store functions and imports, registry/mirror integration. Preserve contract request_identity_fields in derived local provenance/identity; restore old observations from immutable request evidence or fail with explicit gap. No production access or existing Parquet writes.
