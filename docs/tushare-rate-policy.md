# 分层请求门与灰度启用候选

本候选默认 `rate_policy=legacy`，旧账户/API间隔、已观察供应商quota、权限拒绝和公平轮转继续使用。只有显式 `tiered_v1` 才调整API上限；不启用新接口、不改任务/游标/规划签名，也不修改原始数据。没有部署或实际提速结论。

## 配额依据和保守边界

[官方总表290](https://tushare.pro/document/1?doc_id=290)区分积分和独立权限，5000以上常规500次/分钟、10000以上特色300次/分钟。官方类别逐项核对后147个明确常规API使用静态allowlist，可至500；`stk_nineturn/stk_ah_comparison/stk_surv`归特色300，在8100回原合同30/30/50并要求复核。`hk_basic/hk_tradecal/us_basic/us_tradecal/hm_detail`归不确定、保持合同保守；hm_detail在8100还会报告10000门槛未满足。其余没有明确单页或分类依据的积分接口先限300，积分不足10000降到200保守复核档；不能因合同原先是本地30次就证明供应商只允许30，也不能据此把未知接口升500。`fut_weekly_monthly/hsgt_top10/namechange`明确保持旧合同上限；factor_value及未验证独立权益也保持合同保守档（最多200）。

分类审计来源为官方290类别层次，静态清单输入SHA `f0e1b6adca065edf6a77eecd9f72029308872fe9f7055603e83b45584af53bbe`，不能从其他API的补集自动生成。复核标记不会重置任务或伪造权限已失效的供应商响应。

单页/合同明确阶梯优先：[daily27](https://tushare.pro/document/1?doc_id=27)500、[stock_basic25](https://tushare.pro/document/2?doc_id=25)50、[cyq_chips294](https://tushare.pro/document/2?doc_id=294)200、[limit_step356](https://tushare.pro/document/2?doc_id=356)及[kpl_list347](https://tushare.pro/document/2?doc_id=347)8000以上500；合同更低单页频次与显式`api_requests_per_minute`仍取更严值。已观察到的1次/60秒等quota和`api_min_interval_seconds`始终覆盖这些名义档位。

用户提供的已购独立权益映射：news/major_news/cctv_news=400；anns_d、irm_qa_sh/sz、npr、research_report=500；monetary_policy=200，统一到2027-09-08。这是用户账户信息，不是从10100积分推导的授权。400是本地已购族档，并非官网一般积分档。权限到期后回到合同保守档并提示复核，不推定续费。配置与报告没有token、订单或付款材料。

两笔积分和注册积分分别记录：8000到2027-09-08、2000到2026-12-05、100无到期。采用**到期日北京时间00:00**保守切换：当前10100→2026-12-05起8100→2027-09-08起100（未续费假设）。90/30/7天及已到期窗口进入`pipeline-status.json.rate_policy.entitlement`；目前2000分已进入90天窗口。明确8000+单页500及已验证常规daily500在8100仍保持；未知叶子继续保守，不关闭权限缺口。

## cyq_perf日硬上限

[官方293](https://tushare.pro/document/2?doc_id=293)为10000积分200000次/天、5000积分20000次/天。本地永不超过200000；预计8100时降20000，低于5000时0。本地自然日按Asia/Shanghai，供应商未声明时区这一点仍是边界假设。

`capture_sample`发HTTP前在独立`daily-quota.sqlite`中`BEGIN IMMEDIATE`持久预留，覆盖自动队列和使用同入口/同root的有限probe。失败、空响应、超时与不确定中断不退还预留；并发不能超过最后一个名额。未拿到耐久预留则不发HTTP。此计数**无法覆盖在其他程序/其他root自行使用同账户的调用**，不声称供应商账户全天用量已完整对账。

300启用事务调用`activate(root)`，启用当天因旧用量不完整而`activation_guard`，仅cyq_perf阻断到次日。次日或数周后首次调用无需额外等一天；未经过启用helper且缺activation时仍保守阻断首次日。配置提交前失败、跨日恢复会更新activation到真正启用日；已启用重入不会重置计数。账本损坏、时钟回退均失败关闭。此SQLite不发布、不镜像、不参与源数据集；删除后也不能以零用量继续当天调用。

本地guard不写假HTTP attempts、不改旧job/result/tries，不覆盖供应商已观察quota；只设cyq_perf API门到次日，其他API继续。状态区分未初始化、activation_guard、ready、耗尽、时钟回退和账本不可用。

## 可审查启用与恢复

业务容器内先部署候选代码，再运行已有业务入口中的脚本。默认仅计划：

```bash
python3 scripts/tushare_rate_rollout.py --stage 300
python3 scripts/tushare_rate_rollout.py --stage 300 --execute
```

execute核对现有authority与固定`/data/tushare`，非阻塞取得`pipeline.lock`，保存validation/rate-rollout/300.before.json**原字节**、300.after.json、prepared与committed收据。仅修改`rate_policy`、`requests_per_minute`、`rollout_account_rpm`、`account_entitlement`；其他键语义不变。收据记录240→500全局硬ceiling、首阶段rollout300及effective=min(500,300)=300。没有上游请求、发布或队列操作；receipt成功不是吞吐灰度验收。

配置原子替换、文件与目录fsync；prepared之后中断用同命令恢复，当前配置必须仍等于before或after SHA，任何旁路更改都拒绝覆盖。已成功同阶段重跑幂等，不重复重置activation。锁忙安全退出，由操作者后续重试，不暂停消费者。

后续400/500使用同脚本，要求前阶段验收文件及其SHA，文件至少包含`status: passed`、对应`rollout_account_rpm: 300/400`、与当前配置相符的`config_sha256`；由人工审核真实正常批次/限流/超时/资源证据后提供，不由helper编造：

```bash
python3 scripts/tushare_rate_rollout.py --stage 400 --acceptance /tmp/stage300-accepted.json --acceptance-sha256 VERIFIED_SHA
python3 scripts/tushare_rate_rollout.py --stage 400 --acceptance /tmp/stage300-accepted.json --acceptance-sha256 VERIFIED_SHA --execute
```

全局ceiling仍最多500；400/500依赖多API轮转，未知单API仍不升500。报告提供当前解析API上限/source、有效账户档及更严格的实际间隔。当前采集规划/发布CPU瓶颈不会因提高名义额度自动消失，不承诺线性提速。

## 隔离验证

```bash
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_rate_policy test_tushare_extended_pipeline test_tushare_pipeline test_tushare_http_evidence test_tushare_tick_timing test_tushare_family_fairness test_tushare_structured_fairness
```

临时SQLite、MockTransport和禁网/凭据guard，覆盖旧默认、分层/单页/未知档、到期时点/提醒、日配额并发/提交失败/重开/午夜/activation恢复、无假attempt、其他API继续、公平性、CLI默认计划、锁冲突、原配置保留、原子替换及收据失败恢复、400/500前档SHA门槛和quota账本不进入manifest。
