"""Pure A-share technical factors, modelled chips and backup-quote contracts.

Official schema reviewed 2026-09-09. No runtime registration or upstream calls.
Supplier identifiers only occur at the outbound request boundary.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_structured_contracts import _contract, _parse

# Full official output table: field|type|default visibility|field semantics.
# Includes every adjustment variant and literal default parameter; no selected subset.
_OUTPUT_TABLES = {
    "stk_factor": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
close|float|Y|收盘价
open|float|Y|开盘价
high|float|Y|最高价
low|float|Y|最低价
pre_close|float|Y|昨收价
change|float|Y|涨跌额
pct_change|float|Y|涨跌幅
vol|float|Y|成交量 （手）
amount|float|Y|成交额 （千元）
adj_factor|float|Y|复权因子
open_hfq|float|Y|开盘价后复权
open_qfq|float|Y|开盘价前复权
close_hfq|float|Y|收盘价后复权
close_qfq|float|Y|收盘价前复权
high_hfq|float|Y|最高价后复权
high_qfq|float|Y|最高价前复权
low_hfq|float|Y|最低价后复权
low_qfq|float|Y|最低价前复权
pre_close_hfq|float|Y|昨收价后复权
pre_close_qfq|float|Y|昨收价前复权
macd_dif|float|Y|MACD_DIF (基于前复权价格计算，下同)
macd_dea|float|Y|MACD_DEA
macd|float|Y|MACD
kdj_k|float|Y|KDJ_K
kdj_d|float|Y|KDJ_D
kdj_j|float|Y|KDJ_J
rsi_6|float|Y|RSI_6
rsi_12|float|Y|RSI_12
rsi_24|float|Y|RSI_24
boll_upper|float|Y|BOLL_UPPER
boll_mid|float|Y|BOLL_MID
boll_lower|float|Y|BOLL_LOWER
cci|float|Y|CCI
""",
    "stk_factor_pro": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
open|float|Y|开盘价
open_hfq|float|Y|开盘价（后复权）
open_qfq|float|Y|开盘价（前复权）
high|float|Y|最高价
high_hfq|float|Y|最高价（后复权）
high_qfq|float|Y|最高价（前复权）
low|float|Y|最低价
low_hfq|float|Y|最低价（后复权）
low_qfq|float|Y|最低价（前复权）
close|float|Y|收盘价
close_hfq|float|Y|收盘价（后复权）
close_qfq|float|Y|收盘价（前复权）
pre_close|float|Y|昨收价(前复权)--为daily接口的pre_close,以当时复权因子计算值跟前一日close_qfq对不上，可不用
change|float|Y|涨跌额
pct_chg|float|Y|涨跌幅 （除权后的涨跌幅）
vol|float|Y|成交量 （手）
amount|float|Y|成交额 （千元）
turnover_rate|float|Y|换手率（%）
turnover_rate_f|float|Y|换手率（自由流通股）
volume_ratio|float|Y|量比
pe|float|Y|市盈率（总市值/净利润， 亏损的PE为空）
pe_ttm|float|Y|市盈率（TTM，亏损的PE为空）
pb|float|Y|市净率（总市值/净资产）
ps|float|Y|市销率
ps_ttm|float|Y|市销率（TTM）
dv_ratio|float|Y|股息率 （%）
dv_ttm|float|Y|股息率（TTM）（%）
total_share|float|Y|总股本 （万股）
float_share|float|Y|流通股本 （万股）
free_share|float|Y|自由流通股本 （万）
total_mv|float|Y|总市值 （万元）
circ_mv|float|Y|流通市值（万元）
adj_factor|float|Y|复权因子
asi_bfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asi_hfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asi_qfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asit_bfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asit_hfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asit_qfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
atr_bfq|float|Y|真实波动N日平均值-CLOSE, HIGH, LOW, N=20
atr_hfq|float|Y|真实波动N日平均值-CLOSE, HIGH, LOW, N=20
atr_qfq|float|Y|真实波动N日平均值-CLOSE, HIGH, LOW, N=20
bbi_bfq|float|Y|BBI多空指标-CLOSE, M1=3, M2=6, M3=12, M4=20
bbi_hfq|float|Y|BBI多空指标-CLOSE, M1=3, M2=6, M3=12, M4=21
bbi_qfq|float|Y|BBI多空指标-CLOSE, M1=3, M2=6, M3=12, M4=22
bias1_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias1_hfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias1_qfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias2_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias2_hfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias2_qfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias3_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias3_hfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias3_qfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
boll_lower_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_lower_hfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_lower_qfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_mid_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_mid_hfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_mid_qfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_upper_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_upper_hfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_upper_qfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
brar_ar_bfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_ar_hfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_ar_qfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_br_bfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_br_hfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_br_qfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
cci_bfq|float|Y|顺势指标又叫CCI指标-CLOSE, HIGH, LOW, N=14
cci_hfq|float|Y|顺势指标又叫CCI指标-CLOSE, HIGH, LOW, N=14
cci_qfq|float|Y|顺势指标又叫CCI指标-CLOSE, HIGH, LOW, N=14
cr_bfq|float|Y|CR价格动量指标-CLOSE, HIGH, LOW, N=20
cr_hfq|float|Y|CR价格动量指标-CLOSE, HIGH, LOW, N=20
cr_qfq|float|Y|CR价格动量指标-CLOSE, HIGH, LOW, N=20
dfma_dif_bfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_dif_hfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_dif_qfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_difma_bfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_difma_hfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_difma_qfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dmi_adx_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adx_hfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adx_qfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adxr_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adxr_hfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adxr_qfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_mdi_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_mdi_hfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_mdi_qfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_pdi_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_pdi_hfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_pdi_qfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
downdays|float|Y|连跌天数
updays|float|Y|连涨天数
dpo_bfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
dpo_hfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
dpo_qfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
madpo_bfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
madpo_hfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
madpo_qfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
ema_bfq_10|float|Y|指数移动平均-N=10
ema_bfq_20|float|Y|指数移动平均-N=20
ema_bfq_250|float|Y|指数移动平均-N=250
ema_bfq_30|float|Y|指数移动平均-N=30
ema_bfq_5|float|Y|指数移动平均-N=5
ema_bfq_60|float|Y|指数移动平均-N=60
ema_bfq_90|float|Y|指数移动平均-N=90
ema_hfq_10|float|Y|指数移动平均-N=10
ema_hfq_20|float|Y|指数移动平均-N=20
ema_hfq_250|float|Y|指数移动平均-N=250
ema_hfq_30|float|Y|指数移动平均-N=30
ema_hfq_5|float|Y|指数移动平均-N=5
ema_hfq_60|float|Y|指数移动平均-N=60
ema_hfq_90|float|Y|指数移动平均-N=90
ema_qfq_10|float|Y|指数移动平均-N=10
ema_qfq_20|float|Y|指数移动平均-N=20
ema_qfq_250|float|Y|指数移动平均-N=250
ema_qfq_30|float|Y|指数移动平均-N=30
ema_qfq_5|float|Y|指数移动平均-N=5
ema_qfq_60|float|Y|指数移动平均-N=60
ema_qfq_90|float|Y|指数移动平均-N=90
emv_bfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
emv_hfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
emv_qfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
maemv_bfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
maemv_hfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
maemv_qfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
expma_12_bfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_12_hfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_12_qfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_50_bfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_50_hfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_50_qfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
kdj_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_hfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_qfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_d_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_d_hfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_d_qfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_k_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_k_hfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_k_qfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
ktn_down_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_down_hfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_down_qfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_mid_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_mid_hfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_mid_qfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_upper_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_upper_hfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_upper_qfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
lowdays|float|Y|LOWRANGE(LOW)表示当前最低价是近多少周期内最低价的最小值
topdays|float|Y|TOPRANGE(HIGH)表示当前最高价是近多少周期内最高价的最大值
ma_bfq_10|float|Y|简单移动平均-N=10
ma_bfq_20|float|Y|简单移动平均-N=20
ma_bfq_250|float|Y|简单移动平均-N=250
ma_bfq_30|float|Y|简单移动平均-N=30
ma_bfq_5|float|Y|简单移动平均-N=5
ma_bfq_60|float|Y|简单移动平均-N=60
ma_bfq_90|float|Y|简单移动平均-N=90
ma_hfq_10|float|Y|简单移动平均-N=10
ma_hfq_20|float|Y|简单移动平均-N=20
ma_hfq_250|float|Y|简单移动平均-N=250
ma_hfq_30|float|Y|简单移动平均-N=30
ma_hfq_5|float|Y|简单移动平均-N=5
ma_hfq_60|float|Y|简单移动平均-N=60
ma_hfq_90|float|Y|简单移动平均-N=90
ma_qfq_10|float|Y|简单移动平均-N=10
ma_qfq_20|float|Y|简单移动平均-N=20
ma_qfq_250|float|Y|简单移动平均-N=250
ma_qfq_30|float|Y|简单移动平均-N=30
ma_qfq_5|float|Y|简单移动平均-N=5
ma_qfq_60|float|Y|简单移动平均-N=60
ma_qfq_90|float|Y|简单移动平均-N=90
macd_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_hfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_qfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dea_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dea_hfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dea_qfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dif_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dif_hfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dif_qfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
mass_bfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
mass_hfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
mass_qfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
ma_mass_bfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
ma_mass_hfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
ma_mass_qfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
mfi_bfq|float|Y|MFI指标是成交量的RSI指标-CLOSE, HIGH, LOW, VOL, N=14
mfi_hfq|float|Y|MFI指标是成交量的RSI指标-CLOSE, HIGH, LOW, VOL, N=14
mfi_qfq|float|Y|MFI指标是成交量的RSI指标-CLOSE, HIGH, LOW, VOL, N=14
mtm_bfq|float|Y|动量指标-CLOSE, N=12, M=6
mtm_hfq|float|Y|动量指标-CLOSE, N=12, M=6
mtm_qfq|float|Y|动量指标-CLOSE, N=12, M=6
mtmma_bfq|float|Y|动量指标-CLOSE, N=12, M=6
mtmma_hfq|float|Y|动量指标-CLOSE, N=12, M=6
mtmma_qfq|float|Y|动量指标-CLOSE, N=12, M=6
obv_bfq|float|Y|能量潮指标-CLOSE, VOL
obv_hfq|float|Y|能量潮指标-CLOSE, VOL
obv_qfq|float|Y|能量潮指标-CLOSE, VOL
psy_bfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psy_hfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psy_qfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psyma_bfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psyma_hfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psyma_qfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
roc_bfq|float|Y|变动率指标-CLOSE, N=12, M=6
roc_hfq|float|Y|变动率指标-CLOSE, N=12, M=6
roc_qfq|float|Y|变动率指标-CLOSE, N=12, M=6
maroc_bfq|float|Y|变动率指标-CLOSE, N=12, M=6
maroc_hfq|float|Y|变动率指标-CLOSE, N=12, M=6
maroc_qfq|float|Y|变动率指标-CLOSE, N=12, M=6
rsi_bfq_12|float|Y|RSI指标-CLOSE, N=12
rsi_bfq_24|float|Y|RSI指标-CLOSE, N=24
rsi_bfq_6|float|Y|RSI指标-CLOSE, N=6
rsi_hfq_12|float|Y|RSI指标-CLOSE, N=12
rsi_hfq_24|float|Y|RSI指标-CLOSE, N=24
rsi_hfq_6|float|Y|RSI指标-CLOSE, N=6
rsi_qfq_12|float|Y|RSI指标-CLOSE, N=12
rsi_qfq_24|float|Y|RSI指标-CLOSE, N=24
rsi_qfq_6|float|Y|RSI指标-CLOSE, N=6
taq_down_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_down_hfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_down_qfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_mid_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_mid_hfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_mid_qfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_up_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_up_hfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_up_qfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
trix_bfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trix_hfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trix_qfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trma_bfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trma_hfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trma_qfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
vr_bfq|float|Y|VR容量比率-CLOSE, VOL, M1=26
vr_hfq|float|Y|VR容量比率-CLOSE, VOL, M1=26
vr_qfq|float|Y|VR容量比率-CLOSE, VOL, M1=26
wr_bfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr_hfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr_qfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr1_bfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr1_hfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr1_qfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
xsii_td1_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td1_hfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td1_qfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td2_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td2_hfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td2_qfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td3_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td3_hfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td3_qfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td4_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td4_hfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td4_qfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
""",
    "cyq_perf": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
his_low|float|Y|历史最低价
his_high|float|Y|历史最高价
cost_5pct|float|Y|5分位成本
cost_15pct|float|Y|15分位成本
cost_50pct|float|Y|50分位成本
cost_85pct|float|Y|85分位成本
cost_95pct|float|Y|95分位成本
weight_avg|float|Y|加权平均成本
winner_rate|float|Y|胜率
""",
    "cyq_chips": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
price|float|Y|成本价格
percent|float|Y|价格占比（%）
""",
    "bak_daily": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
name|str|Y|股票名称
pct_change|float|Y|涨跌幅
close|float|Y|收盘价
change|float|Y|涨跌额
open|float|Y|开盘价
high|float|Y|最高价
low|float|Y|最低价
pre_close|float|Y|昨收价
vol_ratio|float|Y|量比
turn_over|float|Y|换手率
swing|float|Y|振幅
vol|float|Y|成交量
amount|float|Y|成交额
selling|float|Y|内盘（主动卖，手）
buying|float|Y|外盘（主动买， 手）
total_share|float|Y|总股本(亿)
float_share|float|Y|流通股本(亿)
pe|float|Y|市盈(动)
industry|str|Y|所属行业
area|str|Y|所属地域
float_mv|float|Y|流通市值
total_mv|float|Y|总市值
avg_price|float|Y|平均价
strength|float|Y|强弱度(%)
activity|float|Y|活跃度(%)
avg_turnover|float|Y|笔换手
attack|float|Y|攻击波(%)
interval_3|float|Y|近3月涨幅
interval_6|float|Y|近6月涨幅
""",
}
FIELD_METADATA = {
    api: {
        row.split("|", 3)[0]: dict(
            zip(("type", "default", "description"), row.split("|", 3)[1:], strict=True)
        )
        for row in table.strip().splitlines()
    }
    for api, table in _OUTPUT_TABLES.items()
}
FIELDS = {api: list(columns) for api, columns in FIELD_METADATA.items()}
INPUT_FIELDS = {
    api: "ts_code trade_date start_date end_date".split()
    + (["offset", "limit"] if api == "bak_daily" else [])
    for api in FIELDS
}
_DOCS = {
    "stk_factor": (296, 10000, None),
    "stk_factor_pro": (328, 10000, None),
    "cyq_perf": (293, 6000, "20180101"),
    "cyq_chips": (294, 6000, "20180101"),
    "bak_daily": (255, 7000, None),
}
SOURCE_HTML_SHA256 = {
    "stk_factor": "949e808f8323bfeb182f1a6b3b13919ebf9f11ccac79e574bb257a053349b956",
    "stk_factor_pro": "4cf137ca8c301f6e1ab7cce22fd59240f5295a30e4f27943ae6ed88f587a0c15",
    "cyq_perf": "f7f0adff4585d66deb5763fc5c8f294c8248174f0731b55ba043066722b28ed8",
    "cyq_chips": "9012715db09bf099be50bbc6a6d31d3f322b3e039065fe304a4857ecc9d54863",
    "bak_daily": "f02c879ec2fef02e078809fd78c656cd8194e98c57b986036a2489854e74ebb1",
}

TECHNICAL_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _start) in _DOCS.items():
    _keys = ["ts_code", "trade_date"] + (["price"] if _api == "cyq_chips" else [])
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[field for field in FIELDS[_api] if field not in _keys],
        extra=FIELDS[_api],
        start=_start,
        rpm=30,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        input_fields=INPUT_FIELDS[_api],
        required_input_fields=["ts_code"] if _api.startswith("cyq_") else [],
        at_least_one_input=["ts_code", "trade_date"]
        if _api == "stk_factor_pro"
        else [],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[
            f for f, meta in FIELD_METADATA[_api].items() if meta["default"] != "Y"
        ],
        permission_status="unprobed",
        minimum_points=5000,
        independent_permission=None,
        permission_note="Published thresholds do not establish account entitlement. Independent permission is not stated. Local 30 rpm does not replace shared observed account/API gates.",
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        dependencies=["stocks"] if _api.startswith("cyq_") else [],
        saturation_fallback="stocks",
        saturation_param="ts_code",
        preserve_distinct_rows=True,
        date_field="trade_date",
        split_axis="trade_date",
        history_bound_verified=False,
        history_start_precision="year" if _start else "unknown",
        history_partition="stock_calendar_month_v1"
        if _api.startswith("cyq_")
        else "exact_day_v1",
        discovery_gap="Historical/delisted/T identities and source-observed stocks must join stored discovery. Current stock_basic alone, an empty response or a saturated returned subset does not certify a complete historical universe.",
        pagination_gap="Only bak_daily documents offset/limit. Other pages mentioning pagination do not specify those inputs: do not invent them. Legal date bisection must retain ts_code and explicit fields; single-stock/single-day saturation remains blocked.",
        pit_gap="trade_date is the data date, not a verified availability timestamp. Preserve observed_at and supplier revisions; downloaded indicators or share/valuation attributes are not automatically point-in-time research inputs.",
        refresh_gap="Recent seven-day overlap cannot certify older corrections, deletions or changed adjustment bases. No full-history revision sweep or supplier vintage guarantee is implemented here.",
        field_selection_note="Explicitly request every documented field, including all adjustment variants. All reviewed defaults are Y; fields='' and a successful reduced-column request do not prove full schema capture. Preserve additional future supplier columns and nulls.",
        namespace_note="Source suffix codes and historical T identities must survive normalization as source_ts_code; T and reused ordinary symbols stay distinct. Stock request scope does not imply ETF support.",
        field_gaps={
            field: [
                "live_field_presence_unprobed",
                "supplier_revision_and_availability_unverified",
            ]
            for field in FIELDS[_api]
        },
    )
    TECHNICAL_EXTRA_CONTRACTS[_api] = spec

for _api in ("stk_factor", "stk_factor_pro"):
    TECHNICAL_EXTRA_CONTRACTS[_api].update(
        history_gap="The page claims full history without a calendar lower bound. Require an explicit historical scope; example dates and today's stock list are not history boundaries.",
        documented_rate_tiers=[
            {"minimum_points": 5000, "rpm": 100 if _api == "stk_factor" else 30},
            {"minimum_points": 8000, "rpm": 500},
        ],
        unit_note="vol is lots and amount is thousand CNY. Preserve signed indicators and undefined warm-up values; do not treat every numeric field as a positive price.",
    )
TECHNICAL_EXTRA_CONTRACTS["stk_factor"].update(
    adjustment_note="The page describes historical daily snapshot qfq prices with a latest-day adjustment anchor and says snapshots are not updated; technical indicators use qfq. This is not pro_bar end_date-based dynamic qfq. Exact vintage/anchor interpretation and supplier corrections still require verification.",
    formula_gap="MACD/KDJ/RSI/BOLL/CCI labels do not fully specify seed, smoothing, warm-up, rounding, missing-day or adjustment methodology. Preserve supplier values rather than recomputing replacements.",
)
TECHNICAL_EXTRA_CONTRACTS["stk_factor_pro"].update(
    adjustment_note="bfq/qfq/hfq denote separate unadjusted/front/back-adjusted source series. The page does not inherit stk_factor's historical snapshot guarantee. Preserve every variant and never treat adj_factor alone as evidence for recreating supplier factors.",
    unit_note="vol lots; amount thousand CNY; share fields ten-thousand shares; total_mv/circ_mv ten-thousand CNY; stated percentages remain source-scaled. Loss-making pe/pe_ttm can be null. Other factor units follow the literal schema or remain unverified.",
    formula_gap="All literal defaults are retained in FIELD_METADATA. BBI M4 differs bfq=20/hfq=21/qfq=22; this may be a documentation inconsistency and must not be silently unified. kdj_* lacks an explicit J label. Complete formula, seed, warm-up and revision rules are not published.",
    pre_close_gap="pre_close is documented as daily's adjusted previous close and may disagree with prior close_qfq. Keep pre_close, change and pct_chg independently; do not repair the row from adjacent qfq data.",
)
for _api in ("cyq_perf", "cyq_chips"):
    TECHNICAL_EXTRA_CONTRACTS[_api].update(
        documented_daily_tiers=[
            {"minimum_points": 5000, "requests": 20000},
            {"minimum_points": 10000, "requests": 200000},
            {"minimum_points": 15000, "requests": "unlimited"},
        ],
        documented_update_time="18:00-19:00",
        update_timezone_verified=False,
        history_gap="The page gives year 2018, not the first trading observation. 20180101 is a conservative year envelope, not evidence every date or historical security is present.",
        adjustment_note="Chip cost-price adjustment basis is not specified. Do not equate price/cost with daily close, qfq or hfq without evidence.",
        formula_gap="Community-modelled triangular chip distribution with historical turnover decay is not an observed account-position ledger. Decay, initialization, corporate-action handling, rounding and vintages are unspecified.",
    )
TECHNICAL_EXTRA_CONTRACTS["cyq_perf"].update(
    unit_note="Cost quantiles, historical extrema and weighted cost are price-like but currency/adjustment is unstated. winner_rate scale and the historical extrema lookback are not formally specified; retain raw values.",
)
TECHNICAL_EXTRA_CONTRACTS["cyq_chips"].update(
    documented_requests_per_minute=200,
    unit_note="percent is documented in percent units; price is cost price with currency/adjustment unknown. Do not enforce sum=100 without verified discretization and rounding rules.",
    saturation_gap="At 6000 rows for one stock on one day no price filter or offset is documented. Keep blocked; do not invent price buckets or discard chip levels.",
)
TECHNICAL_EXTRA_CONTRACTS["bak_daily"].update(
    documented_history_hint="approximately mid-2017; some early days missing",
    history_gap="Approximate mid-2017 origin and explicitly missing early days do not supply an exact lower bound. Require configured scope and retain the supplier's early-hole gap; no synthetic start day.",
    documented_pagination={
        "offset_param": "offset",
        "limit_param": "limit",
        "input_type": "str",
        "row_cap": 7000,
    },
    pagination_gap="offset and limit are documented as strings, but default limit/order stability and full paging consistency are unverified. This pure planner uses legal date partitions, not unverified offsets; runtime must keep terminal cap blocked until a tested pagination path exists.",
    unit_note="selling/buying are lots; total_share/float_share are hundred-million shares. vol/amount/float_mv/total_mv currency or scale is not specified, unlike daily. Percent-labelled strength/activity/attack retain source units; other ratio scales remain unverified.",
    adjustment_note="Backup-price adjustment basis and close/pre_close compatibility with daily are not specified. Preserve backup values and provenance rather than replacing the primary daily dataset.",
    formula_gap="Dynamic PE, industry/area, strength/activity/attack and interval returns have no full methodology or publication-vintage contract. Backup coverage is not an independently verified primary-price substitute.",
)
# Every source column has a gap slot; add field-specific ambiguities without dropping it.
for _api, spec in TECHNICAL_EXTRA_CONTRACTS.items():
    for _field, gaps in spec["field_gaps"].items():
        if _field not in ("ts_code", "trade_date", "name", "industry", "area"):
            gaps.append("formula_units_adjustment_subject_to_api_notes")
for _field in (
    "bbi_bfq",
    "bbi_hfq",
    "bbi_qfq",
    "pre_close",
    "kdj_bfq",
    "kdj_hfq",
    "kdj_qfq",
):
    TECHNICAL_EXTRA_CONTRACTS["stk_factor_pro"]["field_gaps"][_field].append(
        "specific_documentation_ambiguity_see_formula_or_pre_close_gap"
    )


def _enabled(config):
    values = config.get("technical_extra_apis", tuple(TECHNICAL_EXTRA_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(api, str) or api not in TECHNICAL_EXTRA_CONTRACTS
        for api in values
    ):
        raise ValueError("technical_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("technical_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "technical_extra_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - TECHNICAL_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in technical_extra_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        floor = TECHNICAL_EXTRA_CONTRACTS[api]["history_start"]
        candidates = [_parse(v) for v in (value, floor) if v is not None]
        starts[api] = max(candidates) if candidates else None
    return starts


def technical_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["technical_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks = (
        _stocks(identifiers if identifiers is not None else {})
        if any(api.startswith("cyq_") for api in enabled)
        else []
    )
    gaps = []
    for api in enabled:
        spec = TECHNICAL_EXTRA_CONTRACTS[api]
        for kind in (
            "history_gap",
            "discovery_gap",
            "pagination_gap",
            "pit_gap",
            "refresh_gap",
            "formula_gap",
            "pre_close_gap",
            "saturation_gap",
        ):
            if spec.get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": spec[kind],
                    }
                )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "unknown_history_start_requires_scope"
                if starts[api] is None
                else "configured_scope_not_verified_complete",
            }
        )
        if api.startswith("cyq_"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["stocks"],
                    "reason": "stored_discovery_completeness_unverified"
                    if stocks
                    else "awaiting_stored_stocks",
                    "observed_codes": len(stocks),
                    "universe_complete": False,
                }
            )
    return gaps


def _days(begin, end, stocks=None):
    day = begin
    while day <= end:
        for code in stocks if stocks is not None else (None,):
            yield {
                "trade_date": day.strftime("%Y%m%d"),
                **({"ts_code": code} if code else {}),
            }
        day += timedelta(days=1)


def _months(begin, end, stocks):
    day = begin
    while day <= end:
        last = min(end, date(day.year, day.month, monthrange(day.year, day.month)[1]))
        for code in stocks:
            yield {
                "ts_code": code,
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
        day = last + timedelta(days=1)


def iter_technical_extra_jobs(config, today, identifiers=None):
    """Fair recent days and history: per-stock chip months, all-stock factor days."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks = (
        _stocks(identifiers if identifiers is not None else {})
        if any(api.startswith("cyq_") for api in enabled)
        else []
    )
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            start = starts[api]
            codes = stocks if api.startswith("cyq_") else None
            if not history:
                streams[api] = iter(_days(max(start or recent, recent), today, codes))
            elif start and start < recent:
                streams[api] = (
                    iter(_months(start, recent - timedelta(days=1), codes))
                    if codes is not None
                    else iter(_days(start, recent - timedelta(days=1)))
                )
        while streams:
            for api in tuple(streams):
                params = next(streams[api], None)
                if params is None:
                    del streams[api]
                else:
                    yield {
                        "api_name": api,
                        "params": params,
                        "fields": ",".join(FIELDS[api]),
                        "priority": 55 if history else 20,
                        "epoch": "history" if history else epoch,
                    }
