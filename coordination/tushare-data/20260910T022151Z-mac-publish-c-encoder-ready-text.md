# Manifest C-chunk serialization ready

Owner text_contracts; newbranch codex/tushare-publish-serialization from8193d14. Candidate3e3a640 committed/pushed; oldbbc818a staged candidate NOT included. Seven files: pipeline newserialize_manifest_file+publish finalwrite only,7newtests, boundedbenchmark,2oldfault/weakref injection updates,doc/evidence. No tick/register_documents/stock_context/config/source/DB/production edits. AST outside publish/newhelper identical. Parent may cherry-pick3e3a640 directly.

Same stdlibC encoder chunks asjson.dumps; avoid global''.join and fullUTF8 bytes copies by encoding/writing/hash eachchunk to temporary then fsync/rename standardSHA manifest, atomicCURRENT unchanged. Existingseal corrupt/symlink rejected; partialsoftfailuresclean ownedtemp; noopskip. No newdependency ormodulecopylist. Cchunklist/sourcegraph remainO(n), hugeatomicstrings stillpossible; not a160s SLA promise.

Python3.10.19 exact79 relevanttests passed1.604s; Ruff/diffcheck pass.18freshprocess benchmark (250kfile refs,750kchildren,62.5kgaps≈102MB,3runspermode/kind) allold/newSHAequal. ChineseBMP longestwholeencode/hash/write/fsync0.403259→0.354860s(-12.0%), RSS736886784→443842560; nonBMP0.424019→0.367434(-13.3%), RSS956760064→459931648; ASCII longestonly3.1% improvement, RSS623886336→432324608. Report/tmp/tushare-manifest-c-chunks-benchmark-20260910.json; fullreproscriptandhash+summaryin docs/tushare-manifest-serialization.evidence.json. These localmetadata-onlymeasurements are not productionthroughput assertions.

Recommend controlledintegration+actualstage/CURRENT/fixedMac verification, noactivationflagneeded; stillretainotherpublishtimeoutcauses and nohistory削减. Parentrequestedbefore10:22localdelivery; commitreported10:21:11local.
