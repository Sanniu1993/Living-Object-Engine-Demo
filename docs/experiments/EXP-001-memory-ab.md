# EXP-001 — Memory A/B

**日期：** 2026-07-04 ~ 2026-07-05

## 目的
验证 Memory 是否提高翻译一致性。

## 假设
Memory 能减少术语漂移（term drift）和人名译法不一致。

## 修改
无（不改系统，只对比开/关 Memory 两种翻译方式）。

## 实验设置
- **A 臂：** 关闭 Memory —— Translator 看不到 Memory，只靠当章内容自己判断译法
- **B 臂：** 开启 Memory —— Translator 正常消费 Memory
- 两臂共用同一份、正常增长的 Memory 作为 QA 判定基准（否则基准不同，差异不可信）
- Benchmark：Chapter 1~5（见 `benchmark/benchmark.md`）
- 判官：DeepSeek

## 结果

多次运行，只看**真实问题（Medium+High，剔除噪音）**：

| 运行 | 说明 | 无 Memory | 有 Memory |
|---|---|---|---|
| Run 2 | QA 去噪后 | ~5 真实问题（另有 8 条是判官越界点评剧情，已剔除） | 1 |
| Run 3 | 加类别约束后 | 0 | 6（第1章人名姓/名顺序混用） |

典型真实问题（无 Memory 臂）：
- `忍界第二次大战` 译成 `Second Great Ninja War`，而基准是 `Second Shinobi World War`
- `火影辅佐` 一会儿 `Hokage Assistant` 一会儿 `Hokage's Assistant`

## 结论
**方向上支持 Memory 有效**（能减少术语/人名漂移），但**尚不能下定论**：
- 样本只有 5 章，且 DeepSeek 判官噪音大、翻译非确定性（temperature=0.3），
  两次运行的胜负方向甚至相反 —— 说明单次 A/B 受随机性主导。
- 要拿到可信结论，需要：**换更强判官** + **多跑几轮取平均**（见 EXP-002 的动机）。

## 下一步
- 换 GPT/Claude 做判官后重跑（依赖 v0.7 的判官可插拔接口）
- 同一配置跑 5~10 轮，看均值和方差
