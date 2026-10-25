# 清理过期开发缓存

- id: DISK-001
- scope: 主题=磁盘；项目=Windows 本机维护；条件=pip/npm 使用默认 LocalAppData 缓存，目标为释放旧缓存空间；不覆盖运行环境、模型或业务文件。
- problem: 七天前的包下载缓存与过期 tmp 文件累计占用空间；本次并未发生满盘故障。
- action: 先运行[清理脚本](../../examples/disk/cleanup-old-caches.ps1)预览并核对候选，再加 -Apply；脚本仅处理固定缓存路径、跳过链接及占用文件。之后用相同缓存路径执行 npm cache verify、pip cache info，核对删除清单与空闲增量。
- acceptance: 2026-10-26，本机实测删除 4,572 个文件、4,283,364,134 字节；操作期间空闲增加 4,292,976,640 字节；删除项全部不存在，npm 缓存二次校验正常，Node/npm/pip 基本命令正常；2 个占用文件跳过。未验证所有应用运行。
- evidence: [脱敏实测摘要](../../examples/disk/result.json)；原始文件清单保留在原执行者本机，未公开。摘要证明记录了本次观测，不能独立复现历史执行或证明通用收益。
