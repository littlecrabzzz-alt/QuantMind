# index_weight 公共 reader 部署

- `6c9e79e7`将默认代码字段选择收口到`tushare_store`，CLI、FastAPI、QuantBot和直接reader现在都根据数据合同键选择`ts_code`或`index_code`。
- 生产Python 3.10镜像联合21项测试通过。固定版`data-f9c557…`在无Token并屏蔽socket/DNS时，API与QuantBot均自动用`index_code`查询`SH000300`并返回5行，上游调用0。
- GitHub、Mac与云端Git均对齐到同一提交。只重启`quantmind` API，HTTP健康检200；采集worker、Beat和DB继续healthy。
- `con_code`来源后缀格式的规范化仍为显式缺口，不在旧固定版上伪造内部代码。机器证据见`docs/tushare-reader-default-20260911.evidence.json`。
