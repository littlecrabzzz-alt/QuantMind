# Publish 最小优化交接

Mac隔离codex/tushare-text，基线a68c6d9已合入，候选575e3e1已push。仅publish内一次完整GROUP（按api_name,state显式排序）派生coverage/scope，serialize前在所有archive映射最后使用后previous=None；不改tick/gap/schema/index/格式。发布归属释放；父决定与foreign8后续合批，未生产操作。

49项相关tests通过（1.011s），ruff/diff check通过。新专项从本地Git对象a68c6d9提取完整旧publish方法，不fetch；3代manifest/CURRENT逐字节一致，NOOP/序列化失败重试、unknown state/API/NULL/Unicode、2份真实Mockcapture-Parquet修订、legacy probe及全部历史closure文件逐个SHA匹配。weakref验证旧版对象仅候选在最后编码前释放，必要共享内容仍保留。该专项需有a68c6d9 Git对象的开发checkout，非无.git业务容器；现有timing/archive/pipeline/interval测试一起通过。

/tmp/tushare-publish-equivalence-regression-20260909.log SHA256 7680f31b76c76274e7f67a35ae6c3493914d7da7198a1a9c64df8e88cc3b85f7

短doc docs/tushare-publish-aggregation.md。前一轮10万rowid样本可省scope重复扫描0.211s，但本轮不测worker真实性能，previous释放不保证RSS立即下降；不将quantmind3核/12GiB结果外推到0.75核/1GiB worker。全部原历史/PIT缺口保持。
