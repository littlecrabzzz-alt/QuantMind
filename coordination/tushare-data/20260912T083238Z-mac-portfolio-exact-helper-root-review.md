# Tushare account-private portfolio exact helper root review

- Reviewed candidate: `e3b35cf2bf1ebff3a08fb63b0db3b625cf2cfe06`.
- Integrated on master as: `90233b54`.
- Scope remains code and tests only. Production portfolio reads remain disabled; no account-private upstream call or authority artifact was created.
- Root reran the 8 direct tests and Ruff checks successfully.
- The helper enforces one `p_list` request followed by at most 30 same-epoch `p_get` requests, 30 rpm, a 90-second deadline, exact release/config/code/task pins, and no fixed-release publication.
- Manifests and receipts remain create-only under the authority private directory with modes 0700/0600. Git and standard output retain only counts, states and hashes.
- A real run requires a controlled maintenance window: ordinary Tushare Beat/worker stopped, authority config backed up byte-for-byte, private reads enabled only for the pinned snapshot, then the original config restored before services restart. QuantDB and unrelated services are outside that window.
