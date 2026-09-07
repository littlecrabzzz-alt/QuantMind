#!/usr/bin/env python3
"""Read public research sources once; no API keys or model calls required.

Requires Python 3.10+, curl and POSIX file locking. This is a bounded source
snapshot, not a complete historical crawler. See the report's coverage notes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "arxiv": ("https://rss.arxiv.org/atom/q-fin.ST+q-fin.PM+q-fin.TR+q-fin.CP", "当前公告批次；不保证覆盖完整回看区间"),
    "qlib": ("https://api.github.com/repos/microsoft/qlib/releases?per_page=10", "最近最多 10 个正式发布，非代码提交全量"),
    "rd_agent": ("https://api.github.com/repos/microsoft/RD-Agent/releases?per_page=10", "最近最多 10 个正式发布，非代码提交全量"),
    "playbook": ("https://api.github.com/repos/hugo2046/QuantsPlaybook/commits?per_page=10", "最近最多 10 个提交，不自动执行代码"),
    "vnpy": ("https://www.vnpy.com/forum/", "首页各板块最新帖入口；无准确发布日期的条目只作为待核实线索"),
    "quantconnect": ("https://www.quantconnect.com/forum/", "公开首页内嵌讨论快照，非完整论坛；原始时间未标明时区"),
    "joinquant": ("https://www.joinquant.com/view/community/list", "仅探测公开页面是否包含可解析条目，动态页面不算采集成功"),
}
TOPICS = {
    "统计验证": ("backtest", "overfit", "falsifi", "回测", "样本外", "leakage"),
    "因子与组合": ("factor", "portfolio", "rotation", "因子", "组合", "轮动", "rrg"),
    "预测模型": ("prediction", "forecast", "stock returns", "预测", "时序"),
    "执行与成本": ("slippage", "market impact", "execution", "metaorder", "成交", "滑点"),
    "AI研究工具": ("llm", "language model", "prompt", "qlib", "rd-agent", "智能体"),
}
ATOM = "{http://www.w3.org/2005/Atom}"


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def plain(text):
    parser = TextOnly()
    parser.feed(text or "")
    return " ".join(" ".join(parser.parts).split())


def item(key, title, url, summary="", published=None, updated=None, **extra):
    if not url.startswith("https://"):
        raise ValueError("条目链接必须为 HTTPS")
    return dict(key=key, title=plain(title), url=url, summary=plain(summary),
                published_at=published, updated_at=updated, **extra)


def parse(source, body):
    if source == "arxiv":
        root = ET.fromstring(body)
        if root.tag != ATOM + "feed":
            raise ValueError("不是有效 Atom feed")
        result = []
        for e in root.findall(ATOM + "entry"):
            raw_id = e.findtext(ATOM + "id", "")
            match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", raw_id)
            if not match:
                raise ValueError("arXiv 条目缺少论文 ID")
            paper_id, version = match.groups()
            announce = e.findtext("{http://arxiv.org/schemas/atom}announce_type", "unknown")
            # RSS updated is feed generation time, not the paper's revision date.
            result.append(item(
                "arxiv:" + paper_id, e.findtext(ATOM + "title"),
                "https://arxiv.org/abs/" + paper_id,
                e.findtext(ATOM + "summary"), version=version,
                announced_at=e.findtext(ATOM + "published"),
                announce_type=announce, kind="论文公告",
                authors=e.findtext("{http://purl.org/dc/elements/1.1/}creator"),
                categories=[c.get("term") for c in e.findall(ATOM + "category")],
                reading_depth="摘要，未核对全文或复现",
            ))
        return result
    if source in {"qlib", "rd_agent", "playbook"}:
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError("GitHub 未返回条目列表")
        result = []
        for x in data:
            if source == "playbook":
                commit = x["commit"]
                result.append(item(
                    "github:playbook:" + x["sha"], commit["message"].splitlines()[0],
                    x["html_url"], commit["message"], commit["committer"]["date"],
                    kind="代码提交", reading_depth="提交说明，未审查或运行代码",
                ))
            elif not x.get("draft") and not x.get("prerelease"):
                result.append(item(
                    f"github:{source}:{x['id']}", source + " " + (x["name"] or x["tag_name"]),
                    x["html_url"], x.get("body"), x["published_at"],
                    kind="工具发布", reading_depth="发布说明，未安装验证",
                ))
        return result
    if source == "quantconnect":
        match = re.search(r'<script[^>]+id="jsonDiscussionsData"[^>]*>(.*?)</script>', body, re.S)
        if not match:
            raise ValueError("页面没有公开讨论数据，不能视作无更新")
        data = json.loads(match.group(1))
        return [item(
            f"quantconnect:{x['id']}", x["title"], x["url"],
            x.get("content") or x.get("abstract"), x.get("published"), x.get("updated"),
            kind="技术讨论", reading_depth="公开主帖，未核对全部回复或复现",
            date_note="来源未声明时区；仅按原始日历日期筛选",
        ) for x in data["discussions"] if x.get("status") == "visible"]
    if source == "vnpy":
        matches = re.findall(
            r'<div class="last-post-title">\s*<a href="(/forum/post/\d+)" title="([^"]+)"', body)
        if not matches:
            raise ValueError("未解析到论坛条目，可能是结构变化或访问限制")
        return [item("vnpy:" + path.rsplit("/", 1)[-1], html.unescape(title),
                     "https://www.vnpy.com" + path, kind="技术讨论线索",
                     reading_depth="仅首页标题；发布时间与正文待核实")
                for path, title in matches]
    if source == "joinquant":
        raise ValueError("公开页面未接入结构化解析；本次页面可能仅为动态外壳，鉴权需求尚未确定")
    raise ValueError("未知来源")


def classify(entry, start, end):
    title = entry["title"].lower()
    if re.search(r"readme|^docs:|招聘|交流群|课程|报名|优惠|荐股|今日行情|收盘点评", title):
        return "排除：推广或文档维护", [], 0
    text = title + " " + entry["summary"].lower()
    topics = [name for name, words in TOPICS.items() if any(w in text for w in words)]
    dates = [str(entry.get(k) or "")[:10] for k in ("announced_at", "published_at", "updated_at")]
    valid = []
    for value in dates:
        try:
            valid.append(date.fromisoformat(value))
        except ValueError:
            pass
    if not valid:
        return "日期待核实", topics, 0
    newest = max(valid)
    if newest < start:
        return "历史条目", topics, 0
    if newest > end:
        return "未来日期待核实", topics, 0
    if not topics:
        return "低主题相关度", [], 0
    score = sum(3 for words in TOPICS.values() if any(w in title for w in words)) + len(topics)
    return "窗口内候选", topics, score


def connect(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS versions (key TEXT, fingerprint TEXT, seen_at TEXT, payload TEXT, PRIMARY KEY(key, fingerprint))")
    return db


def save(db, entry, now):
    payload = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    old = db.execute("SELECT fingerprint FROM entries WHERE key=?", (entry["key"],)).fetchone()
    status = "首次发现" if old is None else "内容变化" if old[0] != fingerprint else "重复"
    db.execute("INSERT INTO entries VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET fingerprint=excluded.fingerprint,last_seen=excluded.last_seen,payload=excluded.payload",
               (entry["key"], fingerprint, now, now, payload))
    db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)", (entry["key"], fingerprint, now, payload))
    return status


def fetch(source, directory):
    url, coverage = SOURCES[source]
    destination = directory / (source + ".body")
    try:
        completed = subprocess.run([
            "curl", "--silent", "--show-error", "--location", "--proto", "=https",
            "--proto-redir", "=https", "--max-time", "25", "--connect-timeout", "10",
            "--max-filesize", "3000000", "--user-agent", "QuantMindResearchReader/0.1",
            "--output", str(destination), "--write-out", "%{http_code}", url,
        ], capture_output=True, text=True, timeout=30)
        code = completed.stdout
        if completed.returncode or code != "200":
            raise RuntimeError(f"HTTP {code or 'unknown'}; curl exit {completed.returncode}")
        entries = parse(source, destination.read_text(encoding="utf-8"))
        return dict(source=source, status="ok", http_status=code, coverage=coverage,
                    fetched=len(entries), items=entries)
    except Exception as error:
        return dict(source=source, status="failed", error=str(error), coverage=coverage,
                    fetched=0, items=[])


def markdown(report):
    lines = ["# 量化研究采集试运行", "", f"执行时间：{report['run_at']}；方式：{report['mode']}",
             f"筛选区间：{report['start_date']} 至 {report['end_date']}（含首尾日期）。", "",
             "本报告为公开内容采集及关键词初筛，未调用 LLM；不是全文评审或复现结果。",
             "来源均为有限快照，不能保证完整覆盖该区间；定时任务状态请在 Codex 中查看。", "",
             "| 来源 | 状态 | 解析条目 | 覆盖范围或异常 |", "| --- | --- | ---: | --- |"]
    for s in report["sources"]:
        note = s.get("error", s["coverage"]).replace("|", "/")
        lines.append(f"| {s['source']} | {s['status']} | {s['fetched']} | {note} |")
    lines += ["", f"归档计数：{report['counts']}。窗口内候选：{len(report['candidates'])} 条。", "",
              "## 本次新增或变化的候选（最多 5 条）", ""]
    selected = [x for x in report["candidates"] if x["change"] != "重复"][:5]
    if not selected:
        lines.append("本次没有新增候选。请同时查看来源失败与覆盖范围，不能据此推断所有平台均无更新。")
    for x in selected:
        title = x['title'].replace('[', '(').replace(']', ')')
        lines += [f"### [{title}]({x['url']})", "",
                  f"- 来源：{x['source']}；类型：{x['kind']}；归档：{x['change']}",
                  f"- 日期：公告 {x.get('announced_at') or '未知'}；首次发表 {x.get('published_at') or '未知'}；更新 {x.get('updated_at') or '未知'}",
                  f"- 主题：{'、'.join(x['topics'])}；阅读深度：{x['reading_depth']}",
                  f"- 版本/公告类型：{x.get('version') or '不适用'} / {x.get('announce_type') or '不适用'}",
                  f"- 来源内容摘录：{x['summary'][:500]}",
                  "- 方法证据、项目适用性与最小实验：待人工或后续 LLM 评审，不由关键词得分代替。", ""]
    lines += ["## 数据文件", "", "`report.json` 保存全部窗口内候选、条目筛选原因与来源状态；`raw/` 保存本次公开响应；共享 SQLite 保存条目及版本。", ""]
    return "\n".join(lines)


def screening_window(now, lookback_days, previous=None):
    if previous is not None:
        # Replaying the same captured sources must use the original date window.
        return date.fromisoformat(previous["start_date"]), date.fromisoformat(previous["end_date"])
    end = (now + timedelta(hours=8)).date()
    return end - timedelta(days=lookback_days - 1), end


def self_test():
    sample = item("arxiv:1", "Backtest overfitting", "https://arxiv.org/abs/1", "test", "2026-09-04")
    with tempfile.TemporaryDirectory() as directory:
        with connect(Path(directory) / "test.sqlite3") as db:
            assert save(db, sample, "first") == "首次发现"
            assert save(db, sample, "second") == "重复"
            changed = {**sample, "summary": "revised"}
            assert save(db, changed, "third") == "内容变化"
            assert db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 2
    start, end = date(2026, 8, 29), date(2026, 9, 5)
    now = datetime(2026, 9, 7, 17, tzinfo=timezone.utc)
    assert screening_window(now, 7) == (date(2026, 9, 2), date(2026, 9, 8))
    assert screening_window(now, 1) == (date(2026, 9, 8), date(2026, 9, 8))
    assert screening_window(now, 7, {"start_date": str(start), "end_date": str(end)}) == (start, end)
    assert classify(sample, start, end)[0] == "窗口内候选"
    assert classify({**sample, "published_at": "2016-09-04"}, start, end)[0] == "历史条目"
    assert classify({**sample, "published_at": None}, start, end)[0] == "日期待核实"
    assert classify({**sample, "title": "今日行情 Backtest"}, start, end)[0].startswith("排除")
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>oai:arXiv.org:2609.00001v2</id><title>Factor model</title><published>2026-09-04</published><updated>2026-09-05</updated></entry></feed>'
    parsed = parse("arxiv", atom)[0]
    assert parsed["key"] == "arxiv:2609.00001" and parsed["version"] == "v2"
    assert parsed["published_at"] is None and parsed["updated_at"] is None
    assert parsed["announced_at"] == "2026-09-04"
    assert parse("arxiv", atom.replace("2026-09-05", "2026-09-06")) == [parsed]
    assert plain('<script>hidden</script><p>A &amp; B</p>') == "A & B"
    try:
        parse("quantconnect", "<html>Login</html>")
    except ValueError:
        pass
    else:
        raise AssertionError("Missing data must be a source failure")
    print("PASS: identity/version dedup, time filtering, news exclusion, Atom date semantics, missing-data detection")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/research_watch")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--replay", type=Path, help="Reprocess a previous run directory without network calls")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not 1 <= args.lookback_days <= 365:
        parser.error("lookback-days must be 1..365")
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another research collection is running")
        now = datetime.now(timezone.utc)
        run_dir = args.output / now.strftime("%Y%m%dT%H%M%S.%fZ")
        raw = run_dir / "raw"
        raw.mkdir(parents=True)
        previous = None
        if args.replay:
            previous = json.loads((args.replay / "report.json").read_text())
            results = []
            for s in previous["sources"]:
                result = {**s, "items": []}
                if s["status"] == "ok":
                    body = (args.replay / "raw" / (s["source"] + ".body")).read_text()
                    (raw / (s["source"] + ".body")).write_text(body)
                    result["items"] = parse(s["source"], body)
                results.append(result)
        else:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda s: fetch(s, raw), SOURCES))
        # Screening uses source calendar dates; timestamp timezone is preserved, not guessed.
        start, end = screening_window(now, args.lookback_days, previous)
        report = dict(run_at=now.isoformat(), mode="replay" if args.replay else "live",
                      start_date=str(start), end_date=str(end), sources=[], counts={},
                      candidates=[], screened=[])
        with connect(args.output / "catalog.sqlite3") as db:
            for result in results:
                entries = result.pop("items")
                report["sources"].append(result)
                for entry in entries:
                    entry["source"] = result["source"]
                    change = save(db, entry, now.isoformat())
                    report["counts"][change] = report["counts"].get(change, 0) + 1
                    reason, topics, score = classify(entry, start, end)
                    enriched = {**entry, "change": change, "screening": reason, "topics": topics, "score": score}
                    report["screened"].append(enriched)
                    if reason == "窗口内候选":
                        report["candidates"].append(enriched)
        report["candidates"].sort(key=lambda x: (-x["score"], x["key"]))
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        (run_dir / "report.md").write_text(markdown(report))
        print(json.dumps({"run_dir": str(run_dir), "mode": report["mode"], "counts": report["counts"],
                          "candidates": len(report["candidates"]), "sources": report["sources"]}, ensure_ascii=False, indent=2))
        # Partial failure is deliberately a nonzero exit, with usable artifacts retained.
        return 2 if any(s["status"] != "ok" for s in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
