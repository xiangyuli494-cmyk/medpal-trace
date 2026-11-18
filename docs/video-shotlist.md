# C9 三分钟演示分镜（本地审阅稿）

> 日期：2026-11-17；负责人：t1；依据：C8 方案书与 main `ef98682`。
> 12 镜头，共 180 秒；本清单是录制主稿。配套新字幕为 `video/subtitles-c9-3min.srt`。
> 既有 D3 手册与旧字幕的时间轴不一致时，以本稿为准；本任务不包含视频成片。

## 1. 逐镜头清单

| 镜头 | 时间码 | 秒 | 画面与操作 | 旁白 | 核对点 |
| --- | --- | --- | --- | --- | --- |
| 01 | 00:00–00:10 | 10 | 演示页首屏，保留数据声明 | MedPal Trace 是可核验的医疗知识演示原型，使用合成数据，不用于临床诊断。 | 项目名与声明可读 |
| 02 | 00:10–00:24 | 14 | 打开 C8 架构 PNG，从交互层指向六步编排 | 系统把提问、知识查询和证据记录分开。每条回答都保存过程和原文引用。 | 使用本轮正式导出图，虚线云服务不说成在线 |
| 03 | 00:24–00:38 | 14 | 已准备好的终端启动本地服务，展示 /health 返回，再切 /web/ | 默认使用本地数据库、BM25 和离线处理，录制过程不依赖云服务。 | 显示 SQLite；剪辑可压缩等待，不改输出 |
| 04 | 00:38–00:52 | 14 | 输入「上腹隐痛伴反酸，下一步做什么检查？」并提交 | 先看一次真实请求。系统检索资料，识别实体，再查询已收录的关系。 | 本镜头必须真请求，不使用 loading 展示态替代 |
| 05 | 00:52–01:06 | 14 | 特写科室、检查、trace_id 和完整率 | 结构化结果给出科室与检查，并记录 trace 编号。完整率反映引用能否核对，不代表医学正确率。 | 证据条数以现场值为准；药品名称不作为推荐讲解 |
| 06 | 01:06–01:25 | 19 | 展开一条真实证据，停留在原文和锚点 ID | 点开证据，就能看到来源资产和原句。评审可以直接核对这条引用。 | 原句、资产 ID 与锚点均能辨认 |
| 07 | 01:25–01:44 | 19 | 点选六步中的检索、图查询、冲突检查，展示证据高亮 | 决策链包含检索、实体抽取、标准对齐、图查询、冲突检查和结论。每步保留可检查的结果。 | 六步 op 与当前真实 trace 一致 |
| 08 | 01:44–01:58 | 14 | 回读该 trace 的报告端点，展示正文与上传状态 | 报告保存了结论和复现命令。未配置对象存储时仍有本地报告，云地址会明确留空。 | 不把 report_uri=null 演成上传成功 |
| 09 | 01:58–02:13 | 15 | 打开预先生成的假锚点 trace，展示 0% 和缺口标红 | 这是一条明确标记的故障注入：资产存在，引用的锚点不存在，服务端计算出完整率为零。 | 必须使用真实写入的测试 trace；不得前端改数 |
| 10 | 02:13–02:26 | 13 | 打开 /web/?demo=refusal，保留演示入口提示 | 这里展示拒答界面。它是页面演示状态；真实请求是否拒答，要回读 trace 的 refusal 字段确认。 | 不将 UI 展示态冒充真实拒答测试 |
| 11 | 02:26–02:44 | 18 | 终端展示本轮验收 PASS 与评测末行 | 60 条合成样本的离线评测中，科室准确率为零点九六七。测试与指标均可通过仓库命令复核。 | 展示实际 n 与后端；不要混入未合 PR 测试数 |
| 12 | 02:44–03:00 | 16 | /v1/cloud 返回与架构图同屏，最后显示仓库链接 | 云适配代码与历史调用记录可查，完整云端链路仍待验证。下一步完成材料定稿和冻结验收。 | ready 只是配置判定；仓库链接可读 |

## 2. 本地录制准备（Windows PowerShell）

在仓库根目录运行；使用新临时目录，不清理或覆盖现有数据。

```powershell
$repoPath = (Get-Location).Path
$recordPath = Join-Path ([IO.Path]::GetTempPath()) ('medpal-record-' + [guid]::NewGuid())
$env:PYTHONPATH = "$repoPath\packages\core;$repoPath\apps\api"
$env:PYTHONIOENCODING = 'utf-8'
$env:MEDPAL_DATA_DIR = $recordPath
$env:MEDPAL_DB = Join-Path $recordPath 'medpal.db'
$env:MEDPAL_REPORT_DIR = Join-Path $recordPath 'reports'
$env:MEDPAL_LEXICON = Join-Path $repoPath 'data\lexicon\medical.json'
$env:MEDPAL_LLM = 'offline'
$env:MEDPAL_DB_BACKEND = 'sqlite'
# 仅移除当前终端进程的云变量，既不打印值，也不修改本机凭据文件。
Get-ChildItem Env: | Where-Object { $_.Name -like 'HUAWEI_*' -or $_.Name -like 'MEDPAL_LLM_*' } |
  ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
python -m app.seed
python -c "from tools.web_accept import make_fake_anchor_trace; print('故障注入 trace:', make_fake_anchor_trace())"
# 记下上面返回的 ID，镜头 09 使用 /web/?trace=该ID。
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

镜头 08 的报告端点为 `GET /v1/reports/{真实trace_id}`，镜头 09 的故障 trace 与服务必须使用同一临时库。
验收输出可在录制前单独采集；画面注明「本地预先采集」，不伪装成长耗时命令现场瞬时完成。

## 3. 导演与交付检查

- 1920×1080、30fps；终端字号至少 16px；页面缩放 100%。
- 证据原文和 0% 故障注入为必留镜头；完整率与正确率不能混讲。
- 配套字幕总长 180 秒。旧 `subtitles-3min.srt` 不直接套用本时间轴。
- 出片前核对所有 trace_id、证据数、测试数与实际输出，遮住真实凭据、手机号与无关窗口。
- 本地/离线版本使用相同内容；云端版本只在成功业务请求与回读完成后另录。
- C9 交付为分镜和字幕；3/5 分钟成片、PPT 与录屏制作属于 W4，不在本轮标为完成。
