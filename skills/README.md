# QuantBot 技能包

本目录是产品运行资源，不是根目录编码助手指令。`SKILL.md` 提供任务操作流程；同目录 `references/`、`REFERENCES/`、`docs/` 和角色提示词供技能按需读取，不能按普通开发笔记删除。

## 加载与安装

- `scripts/quantbot_init.sh` 将本目录打成 ZIP，通过 QwenPaw 技能池 API 上传，再将含 `SKILL.md` 的技能广播到目标工作区（默认 `default`）。更新会替换同名技能；执行前确认目标实例和工作区。
- `bash scripts/quantbot_init.sh --skills-only` 只安装技能；`--persona-only` 只写入 `config/qwenpaw/{SOUL,PROFILE,AGENTS}.md`；无参数会执行两者。脚本需能访问目标 QwenPaw API；人格安装还需能访问工作区或本机 `qwenpaw` 容器。
- 安装后的技能由 QuantBot 根据任务读取，不等于把全部正文永久注入每轮会话。
- 本地编码助手不会因为仓库存在 `skills/` 就自动获得全部技能。需要时直接读取对应 `SKILL.md`，或按所用工具的技能机制显式安装；不要把技能正文复制进根 `AGENTS.md`。
- 前端用户卡片另见 [prompts](../prompts/README.md)，不是技能安装来源。

## 维护边界

新增技能以 `skills/<name>/SKILL.md` 为入口，frontmatter 包含 `name` 和 `description`。保留券商技能中的上游链接、作者和许可声明；富途技能来源为 <https://openapi.futunn.com/skills/opend-skills.zip>。

操作前识别实际运行实例、Compose 项目和数据挂载。Mac 是当前唯一开发源；远端运行服务或数据库是否迁移必须另行核实，不通过旧地址推断。模型种类从 `backend/shared/training/request.py::ALLOWED_MODEL_TYPES` 读取，特征和数据覆盖从实际接口读取，不维护固定数量。
