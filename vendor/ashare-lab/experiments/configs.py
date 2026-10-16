"""实验参数；未列出的策略参数沿用 LowVolTrend 默认值。"""

from itertools import product
import json
from pathlib import Path


EXPERIMENTS = {
    "smoke": [
        {"start": "2016-01-01", "end": "2016-12-31"},
        {"benchmark": "000906.SH", "start": "2016-01-01", "end": "2016-12-31"},
    ],
    "ablation_is": [
        {"select": select, "timing_index": timing, "start": "2012-01-01", "end": "2019-12-31"}
        for select, timing in product(("all", "lowvol"), (None, "000906.SH"))
    ] + [{"benchmark": "000906.SH", "start": "2012-01-01", "end": "2019-12-31"}],
    # 规格列出的笛卡尔积为 54 个组合（文中标注的 108 与维度不一致）。
    "grid_is": [
        {"vol_window": w, "top_n": n, "ma_window": length, "low_exposure": exposure,
         "start": "2012-01-01", "end": "2019-12-31"}
        for w, n, length, exposure in product((60, 120, 250), (30, 50, 100), (60, 120, 200), (0, 0.3))
    ],
}

# 样本内选定参数（见 docs/05-研究记录.md）：W=250, N=50, L=60, e_low=0.3
CHOSEN = {"vol_window": 250, "top_n": 50, "ma_window": 60, "low_exposure": 0.3}
DEFAULT = {}  # 事先拍定的默认值 W=120, N=50, L=120, e_low=0
IS = {"start": "2012-01-01", "end": "2019-12-31"}
OOS = {"start": "2020-01-01", "end": "2026-09-30"}
FULL = {"start": "2012-01-01", "end": "2026-09-30"}


def _set(period):
    return [
        {**CHOSEN, **period},
        {**DEFAULT, **period},
        {**CHOSEN, "timing_index": None, **period},
        {**CHOSEN, "select": "all", **period},
        {**CHOSEN, "select": "all", "timing_index": None, **period},
        {"benchmark": "000906.SH", **period},
    ]


EXPERIMENTS.update({
    "robust_is": (
        [{**CHOSEN, **IS, "cost": {"slippage": s}} for s in (0.0, 0.002, 0.003)]
        + [{**CHOSEN, **IS, "rebalance": "mid_month"}]
        + [{**CHOSEN, **IS, "select": "random", "seed": k} for k in range(200)]
    ),
    "final_is": _set(IS),
    "final_oos": _set(OOS),
    "final_full": _set(FULL),
})


def _b1_set(period):
    frozen = {"vol_window": 250, "top_n": 50, "timing_index": None, **period}
    return [
        {**frozen},
        {**frozen, "select": "all"},
        {**frozen, "strategy": "industry_lowvol", "mode": "neutral", "weighting": "count"},
        {**frozen, "strategy": "industry_lowvol", "mode": "neutral", "weighting": "cap"},
        {**frozen, "strategy": "industry_lowvol", "mode": "tilt"},
        {"benchmark": "000906.SH", **period},
    ]


EXPERIMENTS.update({"b1_is": _b1_set(IS), "b1_oos": _b1_set(OOS), "b1_full": _b1_set(FULL)})


def _b3_set(period):
    """事先固定 B3 参数，不依赖 B2 选参结果。"""
    variants = [
        ("b3_lowvol", ["lowvol"], {}),
        ("b3_quality", ["quality"], {}),
        ("b3_value", ["value"], {}),
        ("b3_lv_q", ["lowvol", "quality"], {}),
        ("b3_lv_v", ["lowvol", "value"], {}),
        ("b3_lv_q_v", ["lowvol", "quality", "value"], {}),
        ("b3_lv_q_v_buf", ["lowvol", "quality", "value"], {"keep_rank": 100}),
        ("b3_lv_q_v_naive", ["lowvol", "quality", "value"], {"factors": "naive"}),
        ("b3_lv_q_v_buf_vt", ["lowvol", "quality", "value"],
         {"keep_rank": 100, "vol_target": {"target_vol": 0.16, "window": 60, "step": 0.1}}),
    ]
    base = {"vol_window": 250, "top_n": 50, "timing_index": None}
    return [
        {"strategy": "score", "factors": "pit", "top_n": 50,
         "label": label, "groups": groups, **extra, **period}
        for label, groups, extra in variants
    ] + [
        {**base, **period},
        {"strategy": "vol_target", "base_strategy": "lowvol", "base": base,
         "target_vol": 0.16, "window": 60, "step": 0.1, **period},
        {"benchmark": "000906.SH", **period},
    ]


EXPERIMENTS.update({"b3_is": _b3_set(IS), "b3_oos": _b3_set(OOS), "b3_full": _b3_set(FULL)})


B2_BASES = {
    "lowvol": {"vol_window": 250, "top_n": 50, "timing_index": None},
    "industry_lowvol": {"vol_window": 250, "top_n": 50, "timing_index": None,
                        "mode": "neutral", "weighting": "count"},
}
for label, period in (("is", IS), ("oos", OOS)):
    EXPERIMENTS[f"b2_grid_{label}"] = [
        {"strategy": "vol_target", "base_strategy": base, "base": parameters,
         "target_vol": target, "window": window, "step": 0.1, **period}
        for (base, parameters), target, window in product(
            B2_BASES.items(), (0.08, 0.10, 0.12, 0.14, 0.16), (10, 20, 40, 60))
    ]

# --choose 产出后才登记最终实验，避免暗中使用预设参数。
_choice_path = Path(__file__).resolve().parents[1] / "reports/b2/b2_choice.json"
if _choice_path.exists():
    _choice = json.loads(_choice_path.read_text())
    _vt = {"target_vol": _choice["target_vol"], "window": _choice["window"], "step": 0.1}
    for label, period in (("is", IS), ("oos", OOS), ("full", FULL)):
        EXPERIMENTS[f"b2_final_{label}"] = [
            {"strategy": base, **parameters, **period}
            for base, parameters in B2_BASES.items()
        ] + [
            {"strategy": "vol_target", "base_strategy": base, "base": parameters,
             **_vt, **period} for base, parameters in B2_BASES.items()
        ] + [{**CHOSEN, **period}, {"benchmark": "000906.SH", **period}]
    EXPERIMENTS["b2_robust"] = [
        {"strategy": "vol_target", "base_strategy": "lowvol", "base": B2_BASES["lowvol"],
         **_vt, **variant, **period}
        for variant, period in product(
            ({"step": 0.05}, {"step": 0.2}, {"cost": {"slippage": 0.002}}), (IS, OOS))
    ]


# B5 候选沿用 B2/B3 的固定参数；资金和冲击参数只作用于撮合。
B5_STRATEGIES = {
    "lowvol_vt": {"strategy": "vol_target", "base_strategy": "lowvol",
                  "base": B2_BASES["lowvol"],
                  "target_vol": 0.16, "window": 60, "step": 0.1},
    "b3_buf_vt": {"strategy": "score", "factors": "pit", "top_n": 50,
                  "label": "b3_lv_q_v_buf_vt", "groups": ["lowvol", "quality", "value"],
                  "keep_rank": 100,
                  "vol_target": {"target_vol": 0.16, "window": 60, "step": 0.1}},
    "lowvol": {"strategy": "lowvol", **B2_BASES["lowvol"]},
}
B5_COST = {"slippage": 0.0005, "impact_k": 1.0, "max_participation": 0.1}
for label, period in (("full", FULL), ("oos", OOS)):
    EXPERIMENTS[f"b5_capacity_{label}"] = [
        {**parameters, **period, "initial_cash": cash, "cost": B5_COST,
         "name": f"{strategy}__cash{cash:.0e}"}
        for (strategy, parameters), cash in product(
            B5_STRATEGIES.items(), (1e7, 1e8, 1e9, 1e10))
    ]
EXPERIMENTS["b5_sens"] = [
    {**B5_STRATEGIES[strategy], **FULL, "initial_cash": 1e9,
     "cost": {**B5_COST, key: value}, "name": f"{strategy}__{key}{value:g}"}
    for strategy, (key, value) in product(
        ("lowvol_vt", "b3_buf_vt"),
        (("impact_k", 0.5), ("impact_k", 2.0),
         ("max_participation", 0.05), ("max_participation", 0.2)))
]
EXPERIMENTS["b5_ref"] = [
    {**B5_STRATEGIES[strategy], **period, "initial_cash": 1e7,
     "name": f"{strategy}__{label}"}
    for (label, period), strategy in product(
        (("FULL", FULL), ("OOS", OOS)), ("lowvol_vt", "b3_buf_vt"))
]


C6_PERIOD = {"start": "2015-01-01", "end": "2026-09-30"}
EXPERIMENTS["c6"] = [
    {"strategy": "raw_score", "score_file": "reports/c6/scores.parquet",
     "column": f"{metric}_pct_W{window}", "label": f"{metric}_pct_W{window}_N{top_n}",
     "top_n": top_n, **C6_PERIOD}
    for metric, window, top_n in product(("pe", "pb"), (36, 60), (10, 20, 50, 100))
] + [
    {"strategy": "raw_score", "score_file": "reports/c6/scores.parquet",
     "column": column, "label": f"{column}_N50", "top_n": 50, **C6_PERIOD}
    for column in ("ep_xs", "bp_xs")
] + [
    {"select": "all", "timing_index": None, "name": "all_eq", **C6_PERIOD},
    {"vol_window": 250, "top_n": 50, "timing_index": None, **C6_PERIOD},
    {"benchmark": "000906.SH", **C6_PERIOD},
]


# CSCV 审计沿用原始候选与默认成本，仅延长到全区间。
EXPERIMENTS["pbo_ma_grid"] = [
    {**config, **FULL} for config in EXPERIMENTS["grid_is"]
]
EXPERIMENTS["pbo_vt_grid"] = [
    {**config, **FULL} for config in EXPERIMENTS["b2_grid_is"]
    if config["base_strategy"] == "lowvol"
]


# 社区第 1 条：量价背离（打分来自 experiments/b_line/c1_pvdiv.py scores）。
EXPERIMENTS["c1"] = [
    {"strategy": "raw_score", "score_file": "reports/c1/scores.parquet", "column": column,
     "label": f"{column}_N50", "top_n": 50, **FULL}
    for column in ("pv_div", "pv_div_neu")
] + [
    {"select": "all", "timing_index": None, "name": "all_eq", **FULL},
    {"vol_window": 250, "top_n": 50, "timing_index": None, **FULL},
    {"benchmark": "000906.SH", **FULL},
]


# 固定变体检验减仓时点；全部从同一全区间回测切片。
VTCUT_VARIANTS = {
    "none": None,
    "base": {},
    "delay1": {"cut_delay": 1},
    "delay3": {"cut_delay": 3},
    "delay5": {"cut_delay": 5},
    "half": {"cut_scale": 0.5},
    "win120": {"window": 120},
    "downside": {"downside": True},
}
EXPERIMENTS["vtcut"] = []
for base, variants in product(("lowvol", "b3"), VTCUT_VARIANTS.items()):
    variant, extra = variants
    vt = {"target_vol": 0.16, "window": 60, "step": 0.1, **(extra or {})}
    if base == "lowvol":
        config = ({"strategy": "lowvol", **B2_BASES["lowvol"]} if extra is None else
                  {"strategy": "vol_target", "base_strategy": "lowvol",
                   "base": B2_BASES["lowvol"], **vt})
    else:
        config = {"strategy": "score", "factors": "pit", "top_n": 50,
                  "label": "b3_lv_q_v_buf", "groups": ["lowvol", "quality", "value"],
                  "keep_rank": 100}
        if extra is not None:
            config["vol_target"] = vt
    EXPERIMENTS["vtcut"].append({**config, **FULL, "name": f"{base}__{variant}"})


# 扩展研究 S4：事先固定的参数网格，全区间一次回测，IS/OOS 均为切片。
S4_GRID = [
    {"strategy": "vol_target", "base_strategy": "lowvol",
     "base": {"vol_window": w, "top_n": 50, "timing_index": None},
     "target_vol": s, "window": length, "step": 0.1, **FULL}
    for w, s, length in product((120, 250), (0.12, 0.14, 0.16), (20, 60))
]
EXPERIMENTS["s4_full"] = S4_GRID + [
    {"vol_window": w, "top_n": 50, "timing_index": None, **FULL} for w in (120, 250)
] + [{"benchmark": "000906.SH", **FULL}]
