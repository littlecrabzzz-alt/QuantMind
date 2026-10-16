"""公告标题分类与事件时点：单元测试（见 docs/11-公告事件库约定.md）。"""
import pandas as pd
import pytest

from ashare_lab.data.events import classify_title, effective_dates, clean_title

CASES = [
    # 业绩预告
    ("2019年年度业绩预告", ("earnings_forecast", "initial")),
    ("关于2020年半年度业绩预告的公告", ("earnings_forecast", "initial")),
    ("2018年年度业绩预增公告", ("earnings_forecast", "initial")),
    ("2015年半年度业绩预亏公告", ("earnings_forecast", "initial")),
    ("2016年年度业绩预减公告", ("earnings_forecast", "initial")),
    ("2019年年度业绩预告修正公告", ("earnings_forecast", "revision")),
    ("关于2021年度业绩预告的更正公告", ("earnings_forecast", "revision")),
    ("2013年半年度业绩预告补充公告", ("earnings_forecast", "revision")),
    ("2019年度业绩快报", (None, None)),
    ("关于召开2023年度业绩预告说明会的公告", (None, None)),
    # 回购
    ("关于以集中竞价交易方式回购公司股份方案的公告", ("buyback", "plan")),
    ("回购报告书", ("buyback", "plan")),
    ("关于以集中竞价交易方式回购公司股份的回购报告书", ("buyback", "plan")),
    ("关于首次回购公司股份的公告", ("buyback", "first")),
    ("关于以集中竞价交易方式首次回购公司股份的公告", ("buyback", "first")),
    ("关于回购公司股份的进展公告", ("buyback", "progress")),
    ("关于股份回购进展情况的公告", ("buyback", "progress")),
    ("关于股份回购实施结果暨股份变动的公告", ("buyback", "complete")),
    ("关于回购股份事项前十名股东和前十名无限售条件股东持股情况的公告", ("buyback", "other")),
    ("关于控股股东进行股票质押式回购交易的公告", (None, None)),
    ("关于回购注销部分限制性股票的公告", (None, None)),
    ("关于部分限制性股票回购注销完成的公告", (None, None)),
    ("关于回购注销部分限制性股票减少注册资本暨通知债权人的公告", (None, None)),
    ("关于业绩补偿股份回购及注销的公告", (None, None)),
    ("关于使用闲置资金购买国债逆回购的公告", (None, None)),
    # 增持
    ("关于控股股东增持公司股份计划的公告", ("insider_increase", "plan")),
    ("关于控股股东计划增持公司股份的公告", ("insider_increase", "plan")),
    ("关于控股股东增持公司股份计划的进展公告", ("insider_increase", "progress")),
    ("关于控股股东增持公司股份计划实施完成的公告", ("insider_increase", "complete")),
    ("股东增持股份结果公告", ("insider_increase", "complete")),
    ("关于控股股东增持公司股份的公告", ("insider_increase", "other")),
    ("关于高级管理人员增持公司股份的公告", ("insider_increase", "other")),
    ("关于控股股东增持计划时间过半的进展公告", ("insider_increase", "progress")),
    # 减持
    ("股东减持股份计划公告", ("insider_decrease", "plan")),
    ("关于持股5%以上股东减持股份的预披露公告", ("insider_decrease", "plan")),
    ("关于持股5%以上股东股份减持计划的预披露公告", ("insider_decrease", "plan")),
    ("股东减持股份结果公告", ("insider_decrease", "complete")),
    ("关于股东减持计划实施完毕的公告", ("insider_decrease", "complete")),
    ("股东减持股份进展公告", ("insider_decrease", "progress")),
    ("关于持股5%以上股东减持计划时间过半的进展公告", ("insider_decrease", "progress")),
    ("关于持股5%以上股东减持股份比例达到1%的公告", ("insider_decrease", "progress")),
    ("关于持股5%以上股东减持股份的提示性公告", ("insider_decrease", "other")),
    ("关于控股股东承诺不减持公司股份的公告", (None, None)),
    ("关于股东减持可转换公司债券的公告", (None, None)),
    # 监管
    ("关于收到中国证券监督管理委员会立案告知书的公告", ("regulatory", "investigation")),
    ("关于收到中国证监会立案调查通知书的公告", ("regulatory", "investigation")),
    ("关于立案调查事项进展暨风险提示的公告", ("regulatory", "investigation_progress")),
    ("关于收到行政处罚决定书的公告", ("regulatory", "penalty")),
    ("关于收到《行政处罚事先告知书》的公告", ("regulatory", "penalty")),
    ("关于收到深圳证券交易所纪律处分决定的公告", ("regulatory", "discipline")),
    ("关于公司及相关人员收到浙江证监局警示函的公告", ("regulatory", "warning")),
    ("关于收到深圳证券交易所监管函的公告", ("regulatory", "warning")),
    ("关于收到上海证券交易所问询函的公告", ("regulatory", "inquiry")),
    ("关于收到深圳证券交易所关注函的公告", ("regulatory", "inquiry")),
    ("关于对深圳证券交易所2019年年报问询函回复的公告", ("regulatory", "inquiry_reply")),
    ("关于延期回复上海证券交易所问询函的公告", ("regulatory", "inquiry_reply")),
    ("关于最近五年被证券监管部门和交易所采取监管措施或处罚及整改情况的公告", (None, None)),
    ("关于最近5年被证券监管部门和交易所采取监管措施或处罚情况的公告", (None, None)),
    ("关于最近三年未被证券监管部门和交易所处罚的公告", (None, None)),
    ("发行人及保荐机构关于第二轮审核问询函的回复意见", (None, None)),
    ("北京市金杜律师事务所关于公司回购股份的法律意见书", (None, None)),
    ("中诚信国际关于关注海通证券股份有限公司收到中国证券监督管理委员会立案告知书和调查通知书的公告", (None, None)),
    ("关于对深圳证券交易所关于公司回购股份问询函的回复公告", ("regulatory", "inquiry_reply")),
    ("关于收到上海证券交易所关于公司业绩预告的问询函的公告", ("regulatory", "inquiry")),
    # 第一轮核对后补充
    ("关于控股股东部分股份补充质押及质押延期回购的公告", (None, None)),
    ("关于终止回购公司股份的公告", ("buyback", "terminate")),
    ("关于提请股东会批准认购对象免于以要约方式增持公司股份的公告", (None, None)),
    ("南京高科关于增持南京银行股份有限公司股份计划实施结果的公告", (None, None)),
    ("关于增持两面针（扬州）酒店用品有限公司股权公告", (None, None)),
    ("关于控股股东增持公司股份计划实施期满的公告", ("insider_increase", "complete")),
    ("关于董事取消股份减持计划的公告", ("insider_decrease", "terminate")),
    ("关于持股5%以上股东权益变动暨提前终止减持计划的提示性公告", ("insider_decrease", "terminate")),
    ("关于北京首都在线科技股份有限公司申请向特定对象发行股票的审核问询函的回复", (None, None)),
    ("容诚会计师事务所（特殊普通合伙）关于浙江亚光科技股份有限公司2024年年报问询函中有关财务会计问题的专项说明", (None, None)),
    ("控股股东及实际控制人关于东尼电子股票交易异常波动的问询函的回函", ("regulatory", "inquiry_reply")),
    ("关于控股股东增持公司股份的公告", ("insider_increase", "other")),
    # 无关
    ("2018年年度报告", (None, None)),
    ("董事会决议公告", (None, None)),
    ("关于召开2020年第一次临时股东大会的通知", (None, None)),
]


@pytest.mark.parametrize("title,expected", CASES)
def test_classify(title, expected):
    assert classify_title(title) == expected


@pytest.mark.parametrize("raw,clean", [
    ("平安银行：2018年年度报告", "2018年年度报告"),
    ("*ST实 达:2006年中期报告更正公告", "2006年中期报告更正公告"),
    ("关于公司：某事项的说明", "某事项的说明"),
    ("2018年年度报告", "2018年年度报告"),
    ("中国国际金融股份有限公司关于收到中国证券监督管理委员会立案告知书的公告",
     "中国国际金融股份有限公司关于收到中国证券监督管理委员会立案告知书的公告"),
])
def test_clean_title(raw, clean):
    assert clean_title(raw) == clean


def test_classify_uses_cleaned_title():
    assert classify_title("回天新材：关于首次回购公司股份的公告") == ("buyback", "first")


def test_effective_dates_strictly_after():
    cal = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"])
    ann = pd.Series(pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-05", "2023-12-31", "2024-01-08"]))
    out = effective_dates(ann, cal)
    assert list(out[:4]) == list(pd.to_datetime(["2024-01-03", "2024-01-05", "2024-01-08", "2024-01-02"]))
    assert pd.isna(out[4])  # 日历之外
