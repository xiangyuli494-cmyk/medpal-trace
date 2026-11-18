# C8 / C9 / C10 PR 审阅入口

> 编写：2026-11-17；验证：2026-11-18；负责人：t1。
> 本地分支：`docs/C8-C10-week3-local`；基线：main `ef98682`。
> 2026-11-18 按 t1 最新要求提交本周材料并发起队友审核；不合并、不发布 tag。

## 1. 先看这些文件

| 任务 | 文件 | 审阅重点 |
| --- | --- | --- |
| C8 | [方案书](../solution/方案书.md) | 六步链、真实 schema 字段、拒答计分、配置 ready 与远端验证的区别 |
| C8 | [架构 PNG](../solution/figures/medpal-architecture.png) / [SVG](../solution/figures/medpal-architecture.svg) / [HTML](../solution/figures/medpal-architecture.html) | 五层逻辑结构、模块边界、云端已证／未证状态；SVG 为可编辑矢量源 |
| C9 | [12 镜头分镜](../video-shotlist.md) | 180 秒节奏、逐镜画面／台词／操作；故障注入和 UI 展示态标注清楚 |
| C9 | [配套字幕](../video/subtitles-c9-3min.srt) | 与 12 镜头的起止时间逐一对齐；不与旧字幕混用 |
| C10 | [CHANGELOG](../../CHANGELOG.md) | main 已有功能、本 PR 文档、云端未验收项分别记录 |
| C10 | [冻结检查单](C10-freeze.md) | 使用原任务的 v0.9；正式 tag 只能指向审阅、合并和验收后的具体提交 |

## 2. 本轮纠正的关键口径

- 六步链包含 conflict_check；schema 必填字段以实际 JSON Schema 为准，序列化输入键为 in。
- trace 的零引用完整率约定与 eval 评分不同：零证据在 eval 中计 0.0，并纳入全部 n 条平均值。
- `/v1/cloud` 的 ready 只是配置齐全判断，没有逐项发起远端探测。
- 默认 BM25；显式选未配置的 KooSearch 时空召回，不能写成自动回落 BM25。
- 历史 MaaS 真调用与 CCE Pod 记录存在，APIG 当时只有 401/404；这些记录不能等同当前完整云端成功。
- 方案书和图不把未合入基线的 #96 镜像、探针和事务修复写成 main 已交付能力。
- 录制准备使用独立临时目录，避免旧手册的清库命令破坏原有数据。

## 3. 验证范围

执行完整 `scripts/verify.sh`，使用本地临时目录、offline 模型、SQLite 和 n≥60 / dept_acc≥0.85 门槛。
同时检查 C9 的 seed、故障 trace、真实问答和报告回读；检查分镜与字幕的镜头数、总时长和边界。
架构图已通过浏览器导出为 1500×1160 PNG 并目视核对，未发现裁切或文字重叠。
当前验证记录见同目录的 `C8-C10-verification.md`。

## 4. C10 的实际状态

C8/C9 文档和 C10 的 CHANGELOG、范围说明、检查单已准备供审。
#34 原始依赖要求「全部」，当前存在未合 PR 与未完成云端验收，因此本轮不宣称完成正式冻结。
本 PR 仅提交本周材料并请求队友独立审核；正式冻结仍需确认依赖与范围，再安排合并、最终验收和发布。

原本未跟踪的 `docs/handoff-codex.md` 与 `docs/cloud-evidence/20261110-rds-pg18/` 保持原样，不包含在本轮交付中。
