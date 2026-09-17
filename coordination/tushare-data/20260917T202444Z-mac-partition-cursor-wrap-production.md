# Mac partition reconciliation cursor-wrap production acceptance

- Time: 2026-09-17T20:24:44Z
- Archive owner: Mac
- Code commit: `93371877895cabe2698db43ef585fc4d68ff9979`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and fix

The bounded partition reconciliation cursor selected only split rows after its saved row ID. When the cursor reached the table tail while each acquisition cycle appended a small number of new splits, those new rows kept the selection nonempty and prevented a wrap to old rows. Thirty-five `research_report` parents and two `irm_qa_sz` parents already met the SQL evidence conditions for closure but could remain `split_pending` indefinitely.

The reconciliation query now uses any unspent per-cycle budget to continue from the table head. The two ranges are disjoint, the existing `max_parents` and deadline bounds remain in force, and the saved cursor advances only past parents actually checked.

## Verification and deployment

- Added a regression that puts the cursor at the old tail, appends a new split, and proves the same bounded call processes both the appended split and an old ready split.
- All 14 partition closure tests passed.
- Python compilation and `git diff --check` passed.
- The installed pipeline SHA-256 matched the repository: `b2bd449c79fd44c72ace674848d2cc8f2cda9a69a658339343537115e8cce8fa`.
- LaunchAgent `com.quantmind.tushare-archive` resumed as PID 93936 and did not exit.

## Real cycle acceptance

The first complete production cycle with the new cursor ended at 2026-09-17T20:24:44.382825Z:

- Real Tushare requests: 347.
- Cycle elapsed: 101.074 seconds.
- Failed stage: none.
- Queue: done 231,107; empty 208,573; pending 2,877,307; blocked 874; permission-blocked 4,694; quality 509; resolved 4,212; split-pending 6,240.
- Documents processed: 240; document status `ok`.
- Worker stderr: empty.
- SQL-ready stale parents fell from 37 to 3 in one bounded pass: 34 of 35 `research_report` parents closed. The remaining `research_report` parent at split row 145 became ready during the same bounded pass; two `irm_qa_sz` parents at rows 6,034 and 9,468 remain ahead in the circular scan. They retain positive evidence and will be revisited by normal production cycles.

The Mac remains the only full Tushare archive writer. The cloud node remains restricted to the research cache.
