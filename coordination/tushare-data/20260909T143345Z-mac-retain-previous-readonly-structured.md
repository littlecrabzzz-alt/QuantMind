# Publish predecessor retention: bounded read-only diagnosis

Structured; read parent6b18287 committed code only, no runtime implementation/production/config changes. Root supplied 2026-09-09T14:29:38Z publish_only SoftTimeLimitExceeded170s: publish166.58s, retain_previous95.1659s (57.1%), serialize20.6745s, coverage/closure19.5979s (three stages81.3%). CURRENT was changing and worker running; this single failed task does not prove sustained total publication failure. No cloud calls were needed in this diagnosis.

Confirmed code duplication:
- Pipeline.publish read_current (2679+) already manifest_at reads/hashes/decodes previous. files=dict(previous.files) already inherits all old references.
- retain_previous (2932+) calls archive.retain_release (487+), which _manifest_document (414+) again reads/hashes/decodes the same complete manifest; _expected_files (427+) validates and builds a second complete files mapping. Publisher again walks/merges those already inherited entries.
- retain_release includes unbounded .archive.lock flock. The present 95-second aggregate does not distinguish lock wait, JSON/validation CPU, file IO, memory pressure or reclaim.
- The returned retained full-map local survives until after serialize_manifest, even though it is no longer needed after the merge. Clearing previous alone (2951) does not free that map and its independently decoded path strings.
- json_bytes (intake29) builds json.dumps text then UTF-8 bytes. Source/archive hardlinks avoid duplicate disk blocks but retain SHA passes and full JSON allocation.

Minimal implementation direction for a subsequent owned task: (1) add a few retain substages to separate manifest read/decode, expectation validation, lock wait, alias/record and merge; (2) publisher-only verified predecessor fast path reuses its previously verified document, preserves full expected-file metadata validation, avoids another full JSON decode/new inherited-files map, and returns only archive additions because publish already has the predecessor closure; preserve general/legacy-probe API behavior; (3) release retained temporary containers immediately after merge before serialization. Do not relax hardlink/path/SHA validation or skip old releases to improve timings. No schema/framework or new background service is needed.

Fixed-mirror access was only tiny Mac CURRENT plus stat of its one manifest: data-4cd678b24c40b90e03597a19671539747847055eafd6b6548355357c2e195909, 135123885 bytes. No large live/fixed manifest body scanned. This is local fixed-state evidence, not current cloud manifest size.

Isolated synthetic retention fixtures: 1k/10k/50k references; 0.175/1.750/8.750 MB manifests; cProfile-instrumented retention0.00845/0.05791/0.27619s. At50k, expectation validation/new-map0.24529s, repeated manifest read/decode0.01660s, record/link0.01306s (nested stages overlap). Exact archive bytes+same inode+idempotent retry and prior reference closure verified. This confirms redundant work but does NOT explain95s on cloud: source size/worker cgroup pressure or lock wait remain unmeasured. No extrapolated cloud time prediction.

Regression requirements: byte-exact old/new release and no-op; latest-only clean Mac restores all older raw/obs/Parquet/doc histories and archived release IDs; legacy probe20-file/known-dataset identity preserved; unknown-history gaps stay; malformed metadata/path/symlink/same-size tamper fails closed; interrupts after alias/record/manifest retry without self-archive-only releases; explicit lock-wait timing; one predecessor decode/no extra inherited-file mapping and short lifetime in a large temporary fixture. Existing archive/publish-equivalence/publish-timing22 tests passed0.427s with PYTHONPATH=scripts Python3.10.

Evidence:
- /tmp/tushare-retain-readonly-diagnosis.json SHA e39c6e17ed7df71bb4e41f3f7eb2b1ce99cce007f167e4effacbdc4cc76c4ea8
- /tmp/tushare-retain-readonly-diagnosis.py SHA 2305d4245adf81f57368a1095aa0071d9ddb631a54f820e43243173610778728 (temporary synthetic profile re-run entry)
- /tmp/tushare-retain-existing-tests.log SHA f7b02333763e66ea4a746ff21076c97cdbc062605e7885581c0526558e5269b1

Optional minimal live evidence if root wants attribution before changing retain: exact failed/completed stage list for this task and two existing completed statuses; a worker-child RSS+cgroup memory.current/max/events sample and archive-lock owner/wait during a slow retain. No full scan or upstream collection necessary. Discovery cache candidate remains separately pending review/default off; no production claim added here. Read-only task complete.
