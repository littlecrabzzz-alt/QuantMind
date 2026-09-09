# Factor486 schema parser correction ready
- Independent Mac worktree quantmind-tushare-factor-catalog-schema; branch codex/tushare-factor-catalog-schema; base092dedf; delta f024021ba62cb9ba8514ddc1b4b6f71d27a96240 pushed, clean.
- Four declared files only: parse_document header guard (7-line diff),486 catalog output list, new dedicated test and docs/tushare-factor-catalog-schema.evidence.json. No production/config enable/API calls/ledger/progress changes.
- Schema首列名称与说明表分类名/序号区分；保留单列/两列紧凑表头及1w/3day数字字段。486旧13→真实4，删除9类别；重解析还阻止1..59公式序号污染。原HTML与SHA799b1716dd674500e499bee73be4015307df014c16064219e751bbbfb45650f2保留，原文件/tmp/tushare-calendar-factor-docs/486.html。
- 离线重放51已保存官方HTML，只有486说明列、268板块代码清单、211指数代码清单发生预期剔除，实际schema未丢失；catalog仅486 output_fields修改，其余字段/263 entries完全不变。其他两页目录未改。
- 12相关tests通过（5新+1catalog review+6intake）；Ruff/diff-check通过。详细离线比对/tmp/tushare-factor-catalog-schema-audit.json，版本化evidence保留完整差异。
- Parent only pick f024021；不依赖pure5aa26e1，可串行组合。未部署。
