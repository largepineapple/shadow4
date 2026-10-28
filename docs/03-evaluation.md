# 验收报告

实际测试 `python -m pytest -q`：37 passed in 0.15s。完整命令与输出见 [test_results](../examples/test_results.txt)。

## 必须验收与实际结果

`python -m examples.run_cases --mode mock`：11/11通过、退出码0；`python -m examples.run_cases --mode live --prefix deepseek`：11/11通过、退出码0。[离线汇总](../examples/mock_results.json) / [真实套件汇总](../examples/deepseek_results.json)。

live套件中10个场景实际调用deepseek-flash进行工具选择、提交候选、观察检查结果并后续决策；missing在输入校验时返回，没有调用模型，不能计为真实动态路径。服务https://api.deepseek.com。下表数值来自实际运行文件：

| 场景 | 实际状态 | 预计秒数 | 运行秒数 | 证据 |
|---|---|---:|---:|---|
| normal | completed | 22 | 23.346 | [输出](../examples/outputs/deepseek_normal.json) / [Trace](../examples/traces/deepseek_normal.json) |
| missing | needs_information | — | 0.245 | [输出](../examples/outputs/deepseek_missing.json) / [Trace](../examples/traces/deepseek_missing.json) |
| no_materials | needs_materials | — | 16.884 | [输出](../examples/outputs/deepseek_no_materials.json) / [Trace](../examples/traces/deepseek_no_materials.json) |
| tool_failure | tool_failed | — | 24.421 | [输出](../examples/outputs/deepseek_tool_failure.json) / [Trace](../examples/traces/deepseek_tool_failure.json) |
| overlong | completed | 27 | 35.783 | [输出](../examples/outputs/deepseek_overlong.json) / [Trace](../examples/traces/deepseek_overlong.json) |
| too_short | cannot_satisfy | 9 | 25.096 | [输出](../examples/outputs/deepseek_too_short.json) / [Trace](../examples/traces/deepseek_too_short.json) |
| changed_source | completed | 9 | 23.827 | [输出](../examples/outputs/deepseek_changed_source.json) / [Trace](../examples/traces/deepseek_changed_source.json) |
| empty_results | needs_materials | — | 17.439 | [输出](../examples/outputs/deepseek_empty_results.json) / [Trace](../examples/traces/deepseek_empty_results.json) |
| rule_repair | completed | 19 | 35.299 | [输出](../examples/outputs/deepseek_rule_repair.json) / [Trace](../examples/traces/deepseek_rule_repair.json) |
| shorter_target | completed | 14 | 37.198 | [输出](../examples/outputs/deepseek_shorter_target.json) / [Trace](../examples/traces/deepseek_shorter_target.json) |
| transient_failure | completed | 11 | 30.109 | [输出](../examples/outputs/deepseek_transient_failure.json) / [Trace](../examples/traces/deepseek_transient_failure.json) |

真实套件墙钟总耗时 269.667 秒，与脚本预计播放时长是不同指标。API费用未读取账单，不报告金额。

## 关键验收证据

- 正常生成：真实模型提交22秒候选，估时与品牌/事实检查均通过，P01/F01原文引用逐镜对应。
- 缺信息：缺受众时needs_information、approved=false，无模型或工具调用。其余四项缺失由pytest逐一覆盖。
- 无素材：不相关主题和空知识库分别检索后仍无依据，needs_materials，不编造字幕之外的能力。
- 工具失败：estimate_duration持续故障时有限重试后tool_failed，估时为空、script为空；once故障重试后生成11秒脚本，两项检查通过，错误记录仍保留。
- 超时长：预先提供38秒可编辑初稿，真实模型先提交原稿估时38（passed=false），运行规则检查，再提交新稿估时27、重跑规则检查，最终completed。离线策略修正为28秒，不能把该数字写成live结果。
- 改变目标：同样38秒初稿，目标从30改15秒后，模型提交14秒修订稿，并重跑两项检查。不是简单复用27秒稿或修改用户目标。
- 无法满足：目标3秒，实际最小品牌结构草稿估时9秒，返回cannot_satisfy/TIME_LIMIT；script为空，不能标记为成功。
- 规则修订：给定待编辑稿含“效率提升80%”，实际check_rules返回UNSUPPORTED_NARRATION等风险；模型移除该结论并重估/重查，最终19秒稿通过。早前失败草稿完整保留在draft_history，不当作已批准内容。
- 素材替换：P01改为“支持手动添加字幕”后，真实生成9秒稿，字幕和引用均使用新原文及2026-10-20版本；清空素材时无脚本，不能沿用旧事实。

38秒初稿和80%风险稿来自examples/inputs中的显式initial_draft输入，是编辑工作流的可复现测试起点，**不是宣称模型自身首次生成了这些内容**。正常案例初稿和上述修订稿来自实际模型工具参数；应用未硬编码代模型压缩稿或事后修改估时。

## 自动化覆盖与独立核对

37项pytest覆盖：五类强制验收、38→28离线修正、规则修订、五项缺输入与非法时长、无/空素材、三类工具持续失败与once恢复、最短时长下界、替换素材、编辑稿不能复用旧检查、目标/素材/品牌变化使检查STALE_CHECK、未检索/不相关来源、标题/画面/字幕的虚构效果断言、执行上限保留实际检查、API脱敏/DeepSeek单工具约束及模型不能宣称未检查稿通过。

独立核对mock/live全部输出与Trace相等；每份候选内容重新算规范化JSON SHA-256与记录一致；每镜朗读/字幕/hold/品牌下界的max、转场与总时长重算一致；来源原文/版本/内容SHA-256、字幕与分镜引用逐项一致。只有同一草稿两项检查均通过才approved=true，旧稿风险和工具失败未抹除。

源码编译、文档本地链接检查通过。逐字节密钥扫描通过，测试进程已清除密钥并退出。没有真实视频、配音或发布，不把字符公式估算冒称为真实测量。

## 完成定义与待本人事项

- [x] 可运行mock/live CLI及真实模型生成/观察/修订循环。
- [x] 五类强制验收有自动化测试和实际输出/Trace。
- [x] 分镜与来源、估时和规则结果对应，事实不能越过来源，编辑/新目标须重新检查。
- [x] 失败如实返回、保留失败候选和错误，不伪造检查或发布成功。
- [x] README、五份文档、合成素材/品牌规则、tests、examples、依赖和环境变量样例齐全。
- [ ] 候选人本人填写04-ai-usage.md中的个人贡献/投入时间，及05-retrospective.md中的个人理解和反思。

限制：受控文案编排与原文字幕，不是任意营销文案的通用语义事实核验；语速/停留/转场为合成假设，非真实TTS验证；平台和风格用于模型编排，不构成真实平台审核认证。案例成功不保证任何模型、素材或品牌规则都可直接泛化。

仓库：https://github.com/largepineapple/shadow4。实际提交SHA以git log和交付消息为准。
