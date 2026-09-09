# Planning cadence and held cache replay — start

Owner structured, isolated branch codex/tushare-planning-interval from eed2c88. Own tick only, a dedicated planning interval test and short doc. Default-off persistent cadence will separate initialize+planning from acquire; publication keeps priority. No production changes, source requests or policy/cursor resets.

Independent cache review branch codex/tushare-discovery-cache-current-review holds 28cdec5+4c65ddc (rebased b78953f+08a54f6). Fixed data-8015e6889e3aa1976a9c64047c993569fabd866982f7935dcfe79ebfcbb985b2: 32790 discovery observations, 30909 eligible raw files/1151118880 bytes, verified all observation SHA and selected raw SHA. Fixture /tmp/tushare-discovery-current-review/prepare-report.json. Local Docker network-none 1GiB/.75CPU replay, synthetic 176MiB parent; amd64 emulation is not production timing. Cache review is separate from cadence and remains unapproved for production.
