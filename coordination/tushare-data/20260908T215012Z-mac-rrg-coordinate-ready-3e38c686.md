# 固定 RRG 坐标消费交接
- 节点 Mac；remaining_markets；codex/tushare-other-markets 提交 c640fce；仅新增 scripts/verify_tushare_rrg_coordinates.py、docs/tushare-rrg-coordinate-acceptance.md。
- 接续 20260908T214359Z-mac-rrg-coordinate-start-921add4c.md。完成，交父复验/集成；无生产、研究配置或数据写入。

固定 release data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6 → 28 行业、36,008 预热价格 → 27,104 坐标已实际离线通过。直接调用已核对 GitHub revision 的作者 factor_algo.py，源码 SHA 固定校验；220/60/20、318 预热及三个截点未来扰动/截断因果性通过，缺值拒绝、比例缩放与同走势中心 100 通过。额外 3 负例和 ruff 通过；重复 CSV SHA 一致。

最终输出 /tmp/quantmind-rrg-coordinates-20260909-final/；报告 SHA f6918cc7d445ba4e8c3745c3f830dfc86ce272ee8151cb272647ae24145e5f60。最短复验命令见新文档。48 个月末仅 47 个下一开市日可映射，最后月末明确 gap。

整体仍 blocked_data；历史中信定义/口径/PIT、扩散度、ETF 执行及权重/并列规则未过。坐标技术通过不是完整研究准入；未运行回测/参数发现或研究登记。
