# 标的发现字段投影候选完成

text_contracts / Mac隔离codex/tushare-text，提交b385c59，基于合30b3194。只pipeline.records可选投影+identifiers调用，新test/doc及旧timing两个mock签名；原SQL、默认records、队列/游标/schema/计时均保持。字段12列完整，原文全解析、全行长度验证、重复字段最后值语义保留。

Python3.10相关106tests通过7.906秒，ruff/diff通过。4不同body×6000行×342列，原文68.54MB，旧/新均4读取0去重，完整结果SHA同e3644b1b5f0bdad9293ea263dc9d003db5becb86d38b9c1091a02833d7576142；本地无tracemalloc单次0.461→0.303秒，单独tracemalloc峰178.9→101.9MB。仅有界合成测量，不外推真实worker，完整JSON与全历史来源仍有开销。不部署、不写生产，交父决定是否本轮集成。pipeline相关归属释放。

- `/tmp/tushare-discovery-projection-benchmark-20260909.json` SHA256 `09c6b890c48e9f616dcc797bd1491328d097d1176fe958fd2c5dfd86faffd415`
- `/tmp/tushare-discovery-projection-regression-20260909.log` SHA256 `0dc736ebe87896e5605f3dba18753d2c698244fbef8fd861f77d44ad25ecae5d`

时间更正：原文件名041800Z为错误预估；本次依据clock实测2026-09-09 04:16:18 UTC更正文件名。正文测试/证据不变。
