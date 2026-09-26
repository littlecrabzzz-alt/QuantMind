"""Read a published release, build derived input, check real Qlib factors. No strategy run."""

import argparse
import hashlib
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", required=True)
parser.add_argument("--task-dir", required=True)
parser.add_argument("--report", required=True)
args = parser.parse_args()
os.environ["ENABLE_CRYPTO"] = "true"
os.environ["QM_QUANTBC_DATA_DIR"] = args.data_dir

from backend.scripts.quantbc_daily_sync import prepare_research_data
from backend.services.engine.data_platform.quantbc_hub import (
    QuantBCDataHub,
    load_quantbc_release_manifest,
    resolve_quantbc_release_dir,
)
from backend.services.engine.rd_agent.rd_loop_wrapper import RDLoopWrapper
from backend.services.engine.rd_agent.market_adapters.crypto import CryptoAdapter

release = resolve_quantbc_release_dir(args.data_dir)
manifest = load_quantbc_release_manifest(release, verify_files=True)
raw_hashes = {
    str(p.relative_to(release)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in release.rglob("*")
    if p.is_file()
}
prepared = prepare_research_data(release)
wrapper = RDLoopWrapper("crypto")
wrapper.adapter = CryptoAdapter(release)
task = Path(args.task_dir).resolve()
wrapper._ensure_data_file(str(task))
h5 = pd.read_hdf(
    task / "git_ignore_folder/factor_implementation_source_data/daily_pv.h5", "data"
)
start, end = (
    date.fromisoformat(manifest["data_start"]),
    date.fromisoformat(manifest["data_end"]),
)
raw = QuantBCDataHub(release).fetch_daily_kline_batch(manifest["symbols"], start, end)
assert len(h5) == len(raw) > 0
assert set(h5.index.get_level_values("instrument")) == {
    "bc_" + s for s in manifest["symbols"]
}
assert set(h5["$factor"]) == {1.0}
assert (task / "source_manifest.json").read_bytes() == (
    release / "manifest.json"
).read_bytes()

import qlib
from qlib.data import D

qlib.init(provider_uri=wrapper._crypto_provider_uri, region="cn")
instruments = ["bc_" + s for s in manifest["symbols"]]
expression = "$close/Ref($close,1)-1"
sample_start = max(start, end - timedelta(days=6))
features = D.features(
    instruments,
    ["$close", "$amount", expression],
    start_time=sample_start.isoformat(),
    end_time=end.isoformat(),
    freq="day",
)
assert len(features) == len(manifest["symbols"]) * ((end - sample_start).days + 1)
for symbol, group in raw.groupby("symbol"):
    expected = group.sort_values("trade_date").set_index("trade_date")
    expected["return"] = expected.close.pct_change()
    observed = features.xs("bc_" + symbol, level="instrument")
    selected = expected.loc[observed.index]
    np.testing.assert_allclose(observed["$close"], selected.close, rtol=2e-6)
    np.testing.assert_allclose(observed["$amount"], selected.amount, rtol=2e-6)
    np.testing.assert_allclose(
        observed[expression], selected["return"], rtol=2e-4, atol=2e-7, equal_nan=True
    )
assert raw_hashes == {
    str(p.relative_to(release)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in release.rglob("*")
    if p.is_file()
}
report = {
    "status": "PASS",
    "release_id": manifest["release_id"],
    "source_manifest_sha256": raw_hashes["manifest.json"],
    "symbols": manifest["symbols"],
    "data_start": str(start),
    "data_end": str(end),
    "raw_rows": len(raw),
    "h5_rows": len(h5),
    "qlib_sample_rows": len(features),
    "computed_factor": expression,
    "qlib_provider": wrapper._crypto_provider_uri,
    "derived": prepared,
    "raw_release_unchanged": True,
    "strategy_research_started": False,
    "trading_started": False,
}
Path(args.report).parent.mkdir(parents=True, exist_ok=True)
Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
