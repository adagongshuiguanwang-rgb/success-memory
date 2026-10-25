# 经验库接入示例

将以下内容加入所用 AI 工具的常驻说明。把入口地址解析成该工具实际能够读取的位置；仅复制文件名不代表工具会自动加载它。

```text
成功经验入口：<可访问的仓库位置>/memory/INDEX.md。
相关任务先读主题索引，核对项目、环境和前提；匹配项按净分从高到低读取，同分按失败次数少、id 升序排序。
直接复用适用的方法并验收；没有匹配项时按现场情况解决。
新经验实际验收成功后按六字段模板保存；计数写 memory/registry.json，运行 tools/memory.py reindex 生成索引。
复用最终成功 +1、失败 -1，使用 tools/memory.py record 提供唯一 event_id 与证据；读取不计分，重复事件不重复计数。
确认失效后暂停调用并清理对应经验；其他有效经验保留。
历史摘要尽量只留主题词；进行中状态另存 private/active/ 并保留可用指针。
经验资料服从当前用户授权与项目约束；执行前按需读取 PROTOCOL.md。
```

For tools using English instructions:

```text
Memory entry: <accessible repository location>/memory/INDEX.md.
Route by topic and match scope. Read eligible entries by score descending, then fewer failures, then id ascending.
Reuse the matching method and verify the actual outcome. Read further files only as needed.
Score = success_count - failure_count. Record only final accepted outcomes with a unique event_id and evidence.
Use tools/memory.py record; duplicate events do not change counts. Reading an entry does not score.
Save new six-field experiences only after success; update memory/registry.json and run reindex.
Pause confirmed invalid entries, then review removal. A single failure lowers the score without erasing successes.
Keep completed-history summaries short. Persist active-task state and a usable recovery pointer.
Experience records do not override the current user's instructions or grant execution permission.
```
