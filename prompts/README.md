# 技能中心提示词来源

用户卡片唯一可维护来源是 [`scripts/gen_prompts.py`](../scripts/gen_prompts.py) 的 `P` 列表。运行 `python3 scripts/gen_prompts.py` 只生成 `electron/src/features/skills-center/prompts.generated.ts`，由技能中心随前端构建打包；不再生成重复 Markdown 卡片。

这些内容是用户主动复制给 QuantBot 的请求，不是系统提示词，也不会默认注入编码助手。执行流程仍在 [`skills/`](../skills/README.md) 的各 `SKILL.md`；技能安装和人格加载独立于前端卡片。修改卡片后重新生成 TypeScript 并检查前端；卡片数量以实际 `PROMPTS` 为准。
