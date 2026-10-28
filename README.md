# 短视频脚本 Agent

帮助创作者根据产品素材与品牌规则，生成有来源、可编辑、满足时长上限的脚本。Python 3.11+ CLI、原生 DeepSeek Agent Loop，本地素材检索、确定性时长估算及规则检查。仅交付JSON脚本，不生成/发布视频或调用真实TTS。

**验证：37项自动化测试通过；mock/live套件各11/11通过（live中10个真实模型路径，1个缺输入未调用模型）。真实超时案例为38→27秒，另有15秒目标下38→14秒。**

评审入口：[验收报告](docs/03-evaluation.md)、[素材](data/materials.json)、[品牌/时长规则](data/brand_rules.json)、[实际输出](examples/outputs/)、[程序自动Trace](examples/traces/)。

## 安装与运行

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
python -m src.main --mode mock --input examples/inputs/normal.json --trace examples/traces/local_mock.json --output examples/outputs/local_mock.json
python -m pytest -q
python -m examples.run_cases --mode mock
```

mock无需密钥，只用于工具/流程测试。真实调用：

```powershell
$env:OPENAI_BASE_URL='https://api.deepseek.com'
$env:OPENAI_MODEL='deepseek-flash'
# 在本机安全设置OPENAI_API_KEY，不写入项目/Git
python -m src.main --mode live --input examples/inputs/overlong.json --trace examples/traces/local_live.json --output examples/outputs/local_live.json
python -m examples.run_cases --mode live --prefix my_live
```

默认base/model即上述DeepSeek值；不自动加载.env。CLI输出UTF-8 JSON。每轮只接受一个工具动作，16轮/14工具上限；两次模型请求/格式错误即incomplete，HTTP超时45秒。DeepSeek关闭thinking并禁用并行工具请求；多工具响应会被拒绝而不是部分执行。completed、needs_information、needs_materials、cannot_satisfy为已处理业务结果，退出码0；tool_failed/incomplete退出码1。

## 输入和交付

输入request_id、theme、audience、platform、target_seconds（1–300整数秒）、style，可选initial_draft。缺五项关键信息时返回needs_information，不调用模型。目标时长是硬上限，30秒允许输出28秒。

交付status/approved、script（标题、分镜、旁白、字幕、逐镜估时与来源）、estimated_total_seconds、source_citations、risks、knowledge_gaps、两项真实检查结果及draft_history/tool_errors。只有completed才提供approved=true和最终script。失败草稿放last_draft及draft_history，不能冒充已通过脚本。

每个场景含id、visual、narration、subtitle、hold_seconds、source_id、fact_id。最终script额外加estimated_seconds及source_citation，便于核对；**可编辑源结构是last_draft**。修改last_draft后放回新请求的initial_draft重新运行，不要把script中的检查标注字段当成输入字段。

## 事实与品牌边界

默认P01只有“支持字幕”这条事实，没有自动识别、准确率或效率提升数据。素材检索是关键词/别名匹配，结果含ID、版本日期、事实ID和原文。模型选择查询与脚本内容，应用不代模型改稿。

为保证MVP的事实可追溯，标题和画面指令从品牌中性白名单选择；每镜字幕必须等于实际检索到的完整事实原文；旁白为该原文或一条品牌中性衔接语，不接受自由扩写的产品结论。每镜绑定source_id/fact_id，校验后由应用附上原文、版本和SHA-256。无依据的“效率提升80%”会被拒绝，即使出现在标题、画面指令或字幕中也不能通过。

这是受控文案与分镜编排，不是任意营销长文的语义事实核查器。可调整允许范围内的标题、画面顺序、衔接语、停留时长和场景数量；事实性文字须随来源保持一致。平台、受众、风格交给模型用于编排，不声称完成真实平台全部审核政策或受众效果验证。

## 时长估算与修订

每镜预计秒数 = max(画面hold_seconds、ceil(旁白Unicode字母/数字/汉字数÷4)、ceil(字幕对应字符数÷5)、品牌最短4秒)。镜间转场1秒；总时长=各镜预计秒数之和+转场总秒数。旁白与字幕同时出现，取max而非重复相加。不实际sleep，结果是合成规则下的预计时长，不是真实配音测量。至少2镜，最多6镜；brand_minimum_seconds=9是品牌结构下界，不保证长文案也能9秒完成。

estimate_duration(draft)登记不可变草稿快照，返回内容SHA-256草稿ID和逐镜估时；check_rules(draft_id)检查同一快照。模型观察passed=false后须修改脚本、获得新ID并重跑两项工具。最终finalize_script只接收ID，不允许在结束动作中偷换脚本；输入目标、素材或品牌规则变化时，旧检查会STALE_CHECK失效。

overlong示例的38秒初稿是**预先给定的可编辑输入**（3镜各12秒加2秒转场），不是声称模型必然先写出38秒。正常案例的初稿和长稿修订均由live模式中的真实模型提交。离线策略将38秒改为28秒；真实模型的实际修正秒数以输出/Trace为准，不强制复制参考数字。shorter_target把目标改15秒，要求不同压缩结果；too_short目标3秒，无法满足品牌下界须停止而非造0秒空脚本。

rule_repair提供包含无依据80%结论的待编辑初稿，模型需依据规则失败结果修订；旧失败草稿保留并标记检查不通过，最终脚本不得含该结论。不能仅根据tool.ok=true判断通过，还要检查data.passed。

## 故障和素材替换

```powershell
python -m src.main --mode mock --input examples/inputs/tool_failure.json --inject-failure estimate_duration --failure-mode always --trace examples/traces/failure_local.json
python -m src.main --mode mock --input examples/inputs/changed_source.json --materials examples/fixtures/changed.json --trace examples/traces/changed_local.json
```

once故障只注入一次，可重试恢复；always持续失败。工具失败不等于“已通过检查”。素材替换fixture将P01改为“支持手动添加字幕”并更新版本，字幕及引用应随之更新；empty fixture移除所有素材，不能沿用原结果。每次CLI运行重新载入素材，无旧脚本缓存。

runner逐项运行真实CLI、自动保存候选和检查，核对分镜时长/转场、来源原文/版本/hash、草稿ID及结果/Trace一致性。输入缺失场景没有模型调用，不能算作live动态路径。完整结果和失败记录见03-evaluation.md。

## 限制

只有合成素材、有限品牌词表、简化字符语速模型，不验证真实TTS、素材可用性或实际剪辑视频。未实现生产身份鉴权、云端保存和发布。真实LLM费用不在模拟时长或业务输出中，未查账单不报告金额。候选人个人贡献、投入时间与主观反思应本人填写。

仓库：https://github.com/largepineapple/shadow4。
