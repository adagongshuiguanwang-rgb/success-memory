import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import memory


class MemoryCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "memory" / "disk").mkdir(parents=True)
        (self.root / "examples").mkdir()
        (self.root / "examples" / "ok.json").write_text("{}", encoding="utf-8")
        self.registry_path = self.root / "memory" / "registry.json"
        self.write_registry([
            self.experience("D-2", 2, 0), self.experience("D-1", 1, 0),
            self.experience("D-3", 2, 0), self.experience("D-4", 1, 1),
        ])

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def experience(eid, successes, failures):
        return {"id": eid, "topic": "disk", "path": f"memory/disk/{eid}.md", "scope": "Windows", "summary": "sample",
                "status": "active", "success_count": successes, "failure_count": failures, "events":
                ([{"event_id": f"{eid}-s-{i}", "result": "success", "evidence": "examples/ok.json"} for i in range(successes)] +
                 [{"event_id": f"{eid}-f-{i}", "result": "failure", "evidence": "examples/ok.json"} for i in range(failures)])}

    def write_registry(self, experiences):
        data = {"schema_version": 1, "topics": {"disk": {"name": "磁盘", "aliases": ["disk", "存储空间", "缓存清理"]}}, "experiences": experiences}
        self.registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read(self):
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def test_record_success_and_failure_adjust_score(self):
        memory.record(self.root, "D-1", "success", "new-success", "examples/ok.json")
        memory.record(self.root, "D-1", "failure", "new-failure", "examples/ok.json")
        item = next(e for e in self.read()["experiences"] if e["id"] == "D-1")
        self.assertEqual((2, 1), (item["success_count"], item["failure_count"]))
        self.assertEqual(1, item["success_count"] - item["failure_count"])

    def test_rank_order_and_alias(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream): memory.rank(self.root, "存储空间")
        ids = [x["id"] for x in json.loads(stream.getvalue())]
        self.assertEqual(["D-2", "D-3", "D-1", "D-4"], ids)

    def test_duplicate_event_is_idempotent_and_conflict_does_not_write(self):
        memory.record(self.root, "D-1", "success", "once", "examples/ok.json")
        before = self.registry_path.read_bytes()
        memory.record(self.root, "D-1", "success", "once", "does-not-need-rechecking.json")
        self.assertEqual(before, self.registry_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "conflict"):
            memory.record(self.root, "D-1", "failure", "once", "examples/ok.json")
        self.assertEqual(before, self.registry_path.read_bytes())

    def test_rank_is_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()): memory.rank(self.root, "disk")
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_blank_event_does_not_commit_invalid_registry(self):
        before = self.registry_path.read_bytes()
        for event_id in ("", "   "):
            with self.assertRaisesRegex(ValueError, "nonempty"):
                memory.record(self.root, "D-1", "success", event_id, "examples/ok.json")
        self.assertEqual(before, self.registry_path.read_bytes())

    def test_rejects_escaping_evidence_without_registry_change(self):
        before = self.registry_path.read_bytes()
        for path in ("../secret", str((self.root / "examples" / "ok.json").resolve())):
            with self.assertRaises(ValueError): memory.record(self.root, "D-1", "success", "unsafe-" + str(len(path)), path)
        self.assertEqual(before, self.registry_path.read_bytes())

    def test_reindex_includes_score_and_status(self):
        memory.reindex(self.root)
        index = (self.root / "memory" / "disk" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| D-2 | 2 | 2 | 0 | active |", index)
        self.assertIn("## Paused", index)

    def test_rank_negative_score_tie_break_and_paused_exclusion(self):
        items = [self.experience("Z-low-fail", 1, 0), self.experience("A-more-fail", 2, 1),
                 self.experience("N-negative", 1, 3), self.experience("P-paused", 1, 0)]
        items[-1]["status"] = "paused"
        self.write_registry(items)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            memory.rank(self.root, "disk")
        result = json.loads(output.getvalue())
        self.assertEqual(["Z-low-fail", "A-more-fail", "N-negative"], [item["id"] for item in result])
        self.assertEqual(-2, result[-1]["score"])

    def test_unknown_id_and_topic_do_not_write(self):
        before = self.registry_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "unknown experience"):
            memory.record(self.root, "missing", "success", "unused", "examples/ok.json")
        with self.assertRaisesRegex(ValueError, "topic"):
            memory.rank(self.root, "unknown")
        self.assertEqual(before, self.registry_path.read_bytes())

    def test_reindex_rejects_unsafe_topic_before_writing(self):
        data = self.read()
        data["topics"]["../outside"] = data["topics"].pop("disk")
        before = (self.root / "memory" / "INDEX.md")
        before.write_text("sentinel", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "safe single-segment"):
            memory.reindex(self.root, data)
        self.assertEqual("sentinel", before.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "outside" / "INDEX.md").exists())

    def test_reindex_uses_real_relative_link_and_escapes_cells(self):
        data = self.read()
        exp = data["experiences"][0]
        exp["path"] = "memory/disk/nested/D-2.md"
        exp["scope"] = "Windows | local\ncache"
        exp["summary"] = "line one|line two"
        target = self.root / exp["path"]
        target.parent.mkdir()
        target.write_text("", encoding="utf-8")
        self.write_registry(data["experiences"])
        memory.reindex(self.root)
        index = (self.root / "memory" / "disk" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("](nested/D-2.md)", index)
        self.assertIn("Windows \\| local<br>cache", index)
        self.assertIn("line one\\|line two", index)

    def test_record_reports_committed_registry_if_reindex_fails(self):
        before = self.read()
        with patch.object(memory, "reindex", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "count committed; run reindex"):
                memory.record(self.root, "D-1", "success", "committed", "examples/ok.json")
        after = self.read()
        item = next(e for e in after["experiences"] if e["id"] == "D-1")
        self.assertEqual(2, item["success_count"])
        self.assertEqual(before["experiences"][1]["success_count"] + 1, item["success_count"])


if __name__ == "__main__":
    unittest.main()
