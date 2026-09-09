# 研究记录点击反馈修复
- Mac，当前研究工作台任务，进行中；接续 20260908T180755Z-mac-workbench-accepted-61f69a3.md。
- 独立 worktree quantmind-glm-research-validation，codex/research-workbench；仅修改 ResearchWorkbench.tsx 的课题打开反馈、详情定位与窄屏详情标题布局，不修改数据/队列/模型调用。
- 用户确认点击列表课题名没有效果；真实页面与 GET 200 证明详情已载入，但窄屏列表占满视口，详情在其下，无自动定位。
- 修复后 typecheck、真实窄屏点击/切换/轮询不抢滚动位置验证，再发布前端。保留其他未提交工作。
