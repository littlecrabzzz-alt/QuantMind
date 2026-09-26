# components

用途：可复用的 UI 组件。

## 说明
- 归属路径：electron\src\features\user-center\components
- 修改本目录代码后请同步更新本 README

## 最近更新
- `ProfileInfo.tsx`：在 `loading/error/空数据` 早返回分支补充 `Form form={form}` 绑定，避免 Ant Design 报告 `useForm` 实例未连接表单的控制台警告。
- `SecuritySettings.tsx`：修改密码提交前新增与后端一致的密码复杂度校验（至少8位，包含大小写字母和数字），并在弹窗内展示规则提示，减少 `POST /api/v1/auth/change-password` 的 400 无效请求。
- `CloudStrategyManagement.tsx`：创建时间列增加安全格式化，`null/0/非法时间` 统一显示 `--`，避免出现 `1970/1/1 08:00:00` 的误导性时间。
- `OtherSettings.tsx`：移除“同步系统预置模板”入口，页面改为暂未开放空态；模板同步仅保留在“我的策略”页按钮入口。
- `CloudStrategyManagement.tsx`、`OtherSettings.tsx`：统一 Tab 内容容器定位，移除 `max-w/mx-auto` 与额外外层卡片偏移，切换“个人档案/安全设置/我的策略/其他设置”时内容起始位置保持一致。
- `OtherSettings.tsx`：空态卡片改为顶部对齐（不再垂直居中），与“我的策略/个人档案/安全设置”视觉起点一致。

## 研究结果关联（2026-09-26）

`CloudStrategyManagement` 复用统一策略 API，分别显示 `base_status` 与 `effective_status`。`parameters.research_case_id` 提供研究工作台入口，配置抽屉支持 `/user-center?tab=strategies&strategyId=<id>`。草稿配置不等于执行程序；此入口不调用 activate 或配置调度。

课题的 `ResearchLedgerPanel` 反向查询同一策略关联，读取已登记的 evidence/view 原件，经既有 `LedgerDetailView` 展示曲线和按日期明细。参数中的 `research_review` 为复核说明，`historical_results` 为原件引用，均不取代服务端准入门控。
