# 规划进度与清单去重生产完成检查点

- 本轮属于progress：runtime eb3bf64已合入master/GitHub/云端，双端预检passed；315 tests/Ruff通过。正式规划状态已有有限签名，11 history连续500→1000，恢复后继续1500/2000；作业481106与尝试36529迁移未丢。旧前缀重扫暂new_jobs=0，不冒充历史完成。
- 云端validation/pre-finite-planning-state.json与finite-planning-alias-acceptance.json；只重启tushare-worker，专属采集/文档均恢复且新任务验证；没有暂停遗留。研究为空，通用US任务未动。正常批326/334请求、整批122.069/119.488秒、failed_stage=null。
- Mac两次镜像验证，最终e45c6159共107697文件；前版40ef395f清单54300820字节与archives同inode和SHA。/tmp/tushare-planning-alias-mac-verified.json。旧重复文件保留；未来镜像去重已真实通过。
- 父独立worktree现在5a23b1e，额外pick Connect runtime b626e6d（未部署）。全319tests发现通用store fixture对3个有请求维度接口缺正确observation/API，已交structured仅修测试，勿降低reader校验；40专项曾过。下一轮接该测试delta、全回归、实际5接口+旧4接口有界能力探测/字段对账/启用与Mac/API验收。
- text schema3累积候选9cf3a60（parent c62cb54），仅需pick该commit；50专项与316k合成实际写入证据通过，尚未父审查/部署，保留旧schema1/2和全部文件。remaining在独立龙虎榜/游资4纯合同，hm_detail隐藏tag须显式请求字段接点，不可只声明已保留。
- 完整263基线+11发现、原文/附件/历史修订仍继续；RRG价格坐标技术验收不解除PIT/ETF准入。保留其他研究者脏文件。下一轮先读本记录和各agent就绪记录，不重复本轮已验收镜像/维护。
