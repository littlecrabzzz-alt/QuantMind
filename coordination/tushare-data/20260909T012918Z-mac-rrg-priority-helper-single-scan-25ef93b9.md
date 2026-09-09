# RRG priority helper performance review delta

- Parent review addressed only/tmphelper; no production execution. Supersedes helper SHA in20260909T012312Z-mac-rrg-priority-helper-candidate-8887a013.md.
- `/tmp/tushare-rrg-priority-window-candidate-20260909.py` SHA256 `c20ec97aaa5bd84c6eae619e1b745a53b7bc526bb3997812df42dcfcff090b73`.
- Replaced111 repeated epoch/API/date JSON target scans with one indexed structured target scan plus in-memory(epoch,api,date) exact-params map. `jobs_group_pending(state,group_name,...)` prefix selected with all observed states, preservingdone/empty/blocked/etc while usinggroup index. Separate state discovery is covered by existingstate index; postmutation rows still primary-key reads. No scope/priority/epoch/audit/rollback semantics changed.
- Original temporary realPipeline fixture passed unchanged:87inserted,22promoted,repeat0; old nonpriority row fields/config/planning/otherjob/attempts preserved, forbiddenplanningwrite denied and rolledback. py_compilepassed. Parent will execute as actualbusinesscontainer/tmpfile so__file__SHAvalid; thisagentdidnotrunproduction.
