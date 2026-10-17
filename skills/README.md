# QuantBot 技能包

本目录是产品运行资源，不是根目录编码助手指令。`SKILL.md` 提供任务操作流程；同目录 `references/`、`REFERENCES/`、`docs/` 和角色提示词供技能按需读取，不能按普通开发笔记删除。

## 加载与安装

- `scripts/quantbot_init.sh` 将本目录打成 ZIP，通过 QwenPaw 技能池 API 上传，再将含 `SKILL.md` 的技能广播到目标工作区（默认 `default`）。更新会替换同名技能；执行前确认目标实例和工作区。
- `bash scripts/quantbot_init.sh --skills-only` 只安装技能；`--persona-only` 只写入 `config/qwenpaw/{SOUL,PROFILE,AGENTS}.md`；无参数会执行两者。主栈 QwenPaw 容器名为 `quantmind-local-qwenpaw`，不向宿主机发布 8088；脚本的宿主机默认地址和裸 `qwenpaw` 容器名不适用于主栈。安装时在目标 QwenPaw 容器内调用回环 API，并先确认工作区与写入授权。
- 安装后的技能由 QuantBot 根据任务读取，不等于把全部正文永久注入每轮会话。
- Main 含完整安装源，但 Library 运行快照的安装白名单不含 `skills/`。缺技能时先单独准备完整安装源树（`scripts/quantbot_init.sh`、`skills/`、`config/qwenpaw/` 保持相对目录），在 QwenPaw 容器可读位置执行该树中的脚本；不要假定 `/quantmind/skills` 存在，也不要因更新 Main 就宣称运行工作区已更新。
- 本地编码助手不会因为仓库存在 `skills/` 就自动获得全部技能。需要时直接读取对应 `SKILL.md`，或按所用工具的技能机制显式安装；不要把技能正文复制进根 `AGENTS.md`。
- 前端用户卡片的唯一内容源是 `scripts/gen_prompts.py` 的 `P` 列表，生成到 `electron/src/features/skills-center/prompts.generated.ts`；不维护重复 Markdown 卡片，也不是技能安装来源。

## 维护边界

新增技能以 `skills/<name>/SKILL.md` 为入口，frontmatter 包含 `name` 和 `description`。保留券商技能中的上游链接、作者和许可声明；富途技能来源为 <https://openapi.futunn.com/skills/opend-skills.zip>。

QuantMind 只在本地 Mac 运行。Main 是开发源码，主业务由 Library 中已核准运行快照的 `scripts/local-primary.sh` 管理；隔离沙盒由 Main 的 `scripts/local-dev.sh` 管理，不能与主业务同时占用 8000 或复用业务数据。操作前识别 Compose 项目和实际挂载。模型种类从 `backend/shared/training/request.py::ALLOWED_MODEL_TYPES` 读取，特征和数据覆盖从实际接口读取，不维护固定数量。
