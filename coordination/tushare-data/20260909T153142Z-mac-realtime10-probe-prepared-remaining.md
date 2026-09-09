# Realtime10 future probe and fixed audit preparation
- 节点/任务：Mac remaining_markets；状态：仅候选，未执行。
- 范围：独占 /tmp/tushare-realtime10-probe.py、/tmp/realtime10-fixed-verify.py、/tmp/test_realtime10_helpers.py、/tmp/realtime10-probe-handoff.md；runtime 无修改。
- 基线：独立 realtime-runtime 99497d4 + 7de205f；要求父 2abcd7f（含同日 superseded-slot mandatory guard）。
- 15 calls/120s 上限：auction 未typed/STK/ETF 各近日日与窄历史共6单码，其余9各一次1MIN/current-only。计划默认不生成 slot，显式 execute 才现场生成，shared gates/lock/prepared/inflight 沿用已审骨架，无自动 enable。
- 固定 audit：105已知列与未知/null/source identity、所有对应parts独立去重、日期/频率/namespace、Cloud/Mac SHA等价，0 upstream；限量超限拒绝不截断。
- 验证：Python3.10 19 tests通过，Ruff通过；只临时合成文件/内存DB doubles，未读取token/生产DB，未源请求/启用/发布/重启。准确脚本SHA/未来命令/实际seed前提见 /tmp/realtime10-probe-handoff.md。
- 下一步：父只审准备文件；真实seed recipe与发布窗口尚未选择。全部原权限/历史/频率/PIT缺口保留。
