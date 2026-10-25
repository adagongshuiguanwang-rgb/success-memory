#!/usr/bin/env python3
"""Small, single-writer CLI for the success-memory registry."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def load_registry(root):
    path = root / "memory" / "registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"registry not found: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid registry JSON: {exc}")
    validate_registry(data)
    return data


def validate_registry(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "topics", "experiences"} or data["schema_version"] != 1:
        raise ValueError("registry must have schema_version:1, topics, and experiences")
    if not isinstance(data["topics"], dict) or not isinstance(data["experiences"], list):
        raise ValueError("topics must be an object and experiences an array")
    for topic_id, topic in data["topics"].items():
        if not isinstance(topic_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", topic_id):
            raise ValueError(f"topic key must be a safe single-segment identifier: {topic_id!r}")
        if (not isinstance(topic, dict) or set(topic) != {"name", "aliases"}
                or not isinstance(topic["name"], str) or not topic["name"].strip()
                or not isinstance(topic["aliases"], list)
                or any(not isinstance(alias, str) or not alias.strip() for alias in topic["aliases"])):
            raise ValueError(f"invalid topic definition: {topic_id}")
    seen_ids, seen_events = set(), {}
    required = {"id", "topic", "path", "scope", "summary", "status", "success_count", "failure_count", "events"}
    for item in data["experiences"]:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("each experience must match the registry schema exactly")
        for key in ("id", "path", "scope", "summary"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"{key} must be a nonempty string for {item.get('id', '<unknown>')}")
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate experience id: {item['id']}")
        seen_ids.add(item["id"])
        if item["topic"] not in data["topics"]:
            raise ValueError(f"unknown topic for {item['id']}: {item['topic']}")
        if item["status"] not in ("active", "paused"):
            raise ValueError(f"invalid status for {item['id']}")
        for key in ("success_count", "failure_count"):
            if type(item[key]) is not int or item[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer for {item['id']}")
        if item["status"] == "active" and item["success_count"] < 1:
            raise ValueError(f"active experience must have at least one success: {item['id']}")
        if not isinstance(item["events"], list):
            raise ValueError(f"events must be an array for {item['id']}")
        successes = failures = 0
        for event in item["events"]:
            if not isinstance(event, dict) or set(event) != {"event_id", "result", "evidence"} or event["result"] not in ("success", "failure"):
                raise ValueError(f"invalid event for {item['id']}")
            eid = event["event_id"]
            if not isinstance(eid, str) or not eid.strip() or not isinstance(event["evidence"], str) or not event["evidence"].strip():
                raise ValueError(f"event_id and evidence must be nonempty strings for {item['id']}")
            if eid in seen_events:
                raise ValueError(f"duplicate event id: {eid}")
            seen_events[eid] = item["id"]
            if event["result"] == "success": successes += 1
            else: failures += 1
        if successes != item["success_count"] or failures != item["failure_count"]:
            raise ValueError(f"counts do not match events for {item['id']}")


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)


def resolve_topic(data, query):
    matches = []
    for key, topic in data["topics"].items():
        if query == key or query == topic["name"] or query in topic["aliases"]:
            matches.append(key)
    if len(matches) != 1: raise ValueError(f"unknown or ambiguous topic: {query}")
    return matches[0]


def rank_items(data, topic):
    return sorted((e for e in data["experiences"] if e["topic"] == topic and e["status"] == "active"),
                  key=lambda e: (-(e["success_count"] - e["failure_count"]), e["failure_count"], e["id"]))


def rank(root, query):
    data = load_registry(root)
    topic = resolve_topic(data, query)
    result = [{"id": e["id"], "score": e["success_count"] - e["failure_count"],
               "counts": {"success": e["success_count"], "failure": e["failure_count"]},
               "scope": e["scope"], "path": e["path"]} for e in rank_items(data, topic)]
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def safe_evidence(root, raw):
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("evidence must be a repository-relative path without '..'")
    candidate = (root / rel).resolve()
    try: candidate.relative_to(root.resolve())
    except ValueError: raise ValueError("evidence escapes repository root")
    if not candidate.is_file(): raise ValueError(f"evidence file does not exist: {raw}")
    return rel.as_posix()


def safe_repo_path(root, raw, label):
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"{label} must be a repository-relative path without '..'")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"{label} escapes repository root")
    return candidate


def md_cell(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def reindex(root, data=None):
    data = data if data is not None else load_registry(root)
    validate_registry(data)
    topics = data["topics"]
    # Resolve every generated and linked path before writing any index file.
    root_index = safe_repo_path(root, "memory/INDEX.md", "index path")
    topic_indexes = {tid: safe_repo_path(root, f"memory/{tid}/INDEX.md", "topic index path") for tid in topics}
    experience_paths = {e["id"]: safe_repo_path(root, e["path"], "experience path") for e in data["experiences"]}
    lines = ["# 主题入口", "", "| 主题词 | 别名 | 索引 | active 条目数 |", "| --- | --- | --- | ---: |"]
    for tid, topic in topics.items():
        active = sum(e["topic"] == tid and e["status"] == "active" for e in data["experiences"])
        lines.append(f"| {md_cell(topic['name'])} | {md_cell('、'.join(topic['aliases']))} | [{md_cell(tid)}/INDEX.md]({md_cell(tid)}/INDEX.md) | {active} |")
    lines += ["", "## 已暂停主题", ""]
    paused_topics = [tid for tid in topics if any(e["topic"] == tid and e["status"] == "paused" for e in data["experiences"])]
    if paused_topics:
        lines += [f"- {topics[t]['name']}：含已暂停经验，见主题索引。" for t in paused_topics]
    else: lines.append("暂无。")
    atomic_write(root_index, "\n".join(lines) + "\n")
    for tid, topic in topics.items():
        active = rank_items(data, tid)
        paused = sorted((e for e in data["experiences"] if e["topic"] == tid and e["status"] == "paused"), key=lambda e: e["id"])
        out = [f"# {topic['name']}", "", "## Active", "", "| id | score | 成功 | 失败 | status | 适用条件 | 摘要 | 经验 |", "| --- | ---: | ---: | ---: | --- | --- | --- | --- |"]
        for e in active:
            link = Path(os.path.relpath(experience_paths[e["id"]], topic_indexes[tid].parent)).as_posix()
            out.append(f"| {md_cell(e['id'])} | {e['success_count']-e['failure_count']} | {e['success_count']} | {e['failure_count']} | {e['status']} | {md_cell(e['scope'])} | {md_cell(e['summary'])} | [{md_cell(e['id'])}]({link}) |")
        out += ["", "## Paused", ""]
        if paused:
            out += ["| id | score | 成功 | 失败 | status | 适用条件 | 摘要 | 经验 |", "| --- | ---: | ---: | ---: | --- | --- | --- | --- |"]
            for e in paused:
                link = Path(os.path.relpath(experience_paths[e["id"]], topic_indexes[tid].parent)).as_posix()
                out.append(f"| {md_cell(e['id'])} | {e['success_count']-e['failure_count']} | {e['success_count']} | {e['failure_count']} | {e['status']} | {md_cell(e['scope'])} | {md_cell(e['summary'])} | [{md_cell(e['id'])}]({link}) |")
        else: out.append("暂无。")
        out[0] = "# " + md_cell(topic["name"])
        atomic_write(topic_indexes[tid], "\n".join(out) + "\n")


def record(root, exp_id, result, event_id, evidence):
    data = load_registry(root)
    exp = next((e for e in data["experiences"] if e["id"] == exp_id), None)
    if exp is None: raise ValueError(f"unknown experience id: {exp_id}")
    for old in data["experiences"]:
        for event in old["events"]:
            if event["event_id"] == event_id:
                if old["id"] == exp_id and event["result"] == result:
                    print(json.dumps({"id": exp_id, "duplicate": True}, separators=(",", ":")))
                    return
                raise ValueError(f"event id conflict: {event_id}")
    evidence = safe_evidence(root, evidence)
    exp["events"].append({"event_id": event_id, "result": result, "evidence": evidence})
    exp[result + "_count"] += 1
    validate_registry(data)
    atomic_write(root / "memory" / "registry.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    try:
        reindex(root, data)
    except Exception as exc:
        raise RuntimeError(f"registry count committed; run reindex to repair generated indexes: {exc}") from exc
    print(json.dumps({"id": exp_id, "score": exp["success_count"] - exp["failure_count"], "duplicate": False}, separators=(",", ":")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Single-writer success-memory scoring CLI")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    p_rank = sub.add_parser("rank"); p_rank.add_argument("--topic", required=True)
    p_record = sub.add_parser("record"); p_record.add_argument("id"); p_record.add_argument("--result", choices=("success", "failure"), required=True); p_record.add_argument("--event-id", required=True); p_record.add_argument("--evidence", required=True)
    sub.add_parser("reindex")
    args = parser.parse_args(argv)
    try:
        if args.command == "rank": rank(args.root.resolve(), args.topic)
        elif args.command == "record": record(args.root.resolve(), args.id, args.result, args.event_id, args.evidence)
        else: reindex(args.root.resolve())
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
