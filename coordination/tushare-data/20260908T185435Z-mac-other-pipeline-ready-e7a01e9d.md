# other集成与family校验隔离完成
- Mac remaining_markets，codex/tushare-other-markets clean；接续20260908T184833Z-mac-other-pipeline-start-1bcc4a24.md。
- 在父b58433a+942af8c基线上的增量：872343806418dfccd4499002365490af071d213b、69bc483046eb27523c4d3d0ac203e57f47bd4be6。父依次cherry-pick；不需要重复pick前序merge和b227732。
- group other/enable_other注册；原始opt/sge/fx基础与每日结果发现options/spot_metals/fx_instruments；规范化OPT:/SGE:/FX:保留source_*；store keys/镜像运行时模块已补。历史/目录/未知cap证据保留为capability缺口，不以非空目录声称全量。
- 按父补充要求：HK 00013!.HK映射HK00013!，不与HK00013合并。global/other prerequisites ValueError写planning:<family> validation_blocked，只跳本family且不推进游标、不改配置；修复后validation_passed并正常重试。只捕获明确ValueError，不吞其他异常。
- 7项新增other pipeline fixtures通过（15API capture→normalize→publish→store离线读、字段/负利率、退市目录与daily新代码、饱和无全集gap、权限拒绝、HK!区分、坏family隔离及恢复）。global pipeline7和partition closure11通过，ruff通过。publish AST与原基线保持一致。
- 无生产API/部署/生产配置修改，未改既有测试或ledger。父下一步合并text agent global identifier !接受补丁，一起验证启用；其他资产同样先真实样本，不声称本地fixture已覆盖供应商权限/历史。
