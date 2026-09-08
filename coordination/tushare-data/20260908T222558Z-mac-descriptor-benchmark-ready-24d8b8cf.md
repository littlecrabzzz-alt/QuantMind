# Two-level descriptor benchmark — no runtime implementation

text_contracts isolated codex/tushare-text. Previous candidates: c62cb54 manifest aliases (independently deployable), 5c521f1 flat3hex state buckets (hold for tradeoff). Parent authorized synthetic assessment only of next two-level layout. New script scripts/benchmark_tushare_document_descriptors.py has no network, DB or production access.

Evidence /tmp/quantmind-document-descriptor-benchmark-20260909.json. Synthetic316831 rows and362139 references (363 fixed mapping descriptors) match counts in existing assessment, not actual document payloads. Exact encoded JSON write totals include all changed state leaves, intermediate descriptor shards and root. No filesystem allocation, CPU/service throughput or compressed network estimates; root attempts/files lists empty, actual URLs/results differ.

| Scenario |2hex flat bytes|3hex flat bytes|3hex two-level bytes|
|---|---:|---:|---:|
|1state|679099|1094498|179053|
|30state|13901221|2004950|1865866|
|1000new|130948434|29517902|29498256|

Two-level vs existing2hex improvement ~73.6%/86.6%/77.5%. Single-update tradeoff of flat3hex is eliminated. Intermediate descriptor block ~59719B, root~88298B for single-update;30updates touched14 descriptor blocks,1000new all16. Known ceiling: root mapping-descriptor list still grows with history; large batches can rewrite all state leaves/16descriptor blocks; more files/inode overhead than2hex. This is a sizing result, not measured production savings.

Recommended smallest follow-up, NOT implemented: index schema_version3, state_prefix_chars3, state_descriptor_prefix_chars1, root.states holds16 first-hex descriptors. Each new descriptor shard can reuse current content-addressed schema2/kind/items list format and _document_shard checks (kind state_descriptors, <=256 leaf descriptors). States leaves remain schema2; mapping/attempt/file rowid1000 blocks stay unchanged. Reader schema1/2 retains old behavior (missing state-prefix defaults2); schema3 resolves firsthex descriptor then3hex leaf. Old readers rejectschema3 explicitly rather than silently losing state. Pin both layers in manifest closure; keep all old indexes/leaves/attempts/originals. Next implementation must verify both descriptor and leaf hash/length/membership, cache only page-required blocks, transactionally preserve dirty recovery, and retain CURRENT-only historical reads.

Validation: default316831 run plus small100-row nine-scenario sum checks and exact canonical leaf byte equivalence; Ruff/diff check pass. No extra runtime framework or schema migration yet. Parent decides later implementation/deployment; benchmark script independent commit on branch.
