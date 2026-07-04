# Benchmark（固定基准）

> ⚠️ **这个文件一旦定下，尽量不要改。** 实验之间要可比，靠的就是基准不变。
> 如果确实要改基准（换语料、换指标），那等于开一条新基准线，旧实验的数字不再可比——
> 到那时请新建 `benchmark-v2.md`，不要覆盖本文件。

## 固定语料

- 文件：`chapters/1-5.text`（火影同人小说前 5 章）
- 章节：Chapter 1 ~ Chapter 5
- 标题格式：分隔线 + 编号（`------------` 换行 `001 标题`）

## 固定配置

- 翻译 / 抽取模型：DeepSeek（`deepseek-chat`）
- QA 判官模型：默认 DeepSeek（可在实验中替换，替换须在该实验记录里写明）
- 翻译方向：中文 → 英文（Chinese → English）
- 翻译 temperature：0.3；QA temperature：0.1

## 固定指标（Metrics）

每次实验对每一臂（arm）统计：

| 指标 | 含义 |
|---|---|
| High | 高严重度 issue 数 |
| Medium | 中严重度 issue 数 |
| Low | 低严重度 issue 数（噪音较多，参考价值低） |
| QA Pass Rate | 通过的章节数 / 总章节数 |
| 真实问题数 | 人工复核后确认的真问题（剔除"一致却上报"等噪音） |

> 经验：DeepSeek 做判官时 Low 档大量是噪音，**看 Medium+High 和"真实问题数"更靠谱**。

## 如何跑

```bash
# A/B 对照（关闭 vs 开启 Memory）
python main.py --input chapters/1-5.text --ab-test

# 普通定稿（QA→修订闭环）
python main.py --input chapters/1-5.text --limit 1 --revise
```
