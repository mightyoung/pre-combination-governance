# risk-fusion-bench：v20.1 / v6.7 非确认性资格切片

> **状态提示（2026-07-23 验收补注）**：本 README 的状态表主要描述早期 G1/G2 canary 切片，未覆盖其后落地的 Stage-1 合同层（`src/rfb/contracts/`）、Stage-2 事务运行时（`src/rfb/runtime/`）、方法面板（`src/rfb/methods/`，B0–B5+Proposed）、formal 隔离层（`src/rfb/formal/`）与 Gate B 组件（capacity/durable/archive/regeneration/purge/closeout）。当前权威状态以根目录 `GateChecklist-v6.13.json` 与 `AGENTS.md` 为准：`runtime_gate=PASS`（开发核验），总状态 `FORMAL_EXPERIMENT_BLOCKED`。

本仓库最初是论文 legacy-v5 的玩具融合链。当前已在保留旧接口的基础上，增加面向 v20.1 / 实验协议 v6.7 的 **G1/G2 非确认性 canary**：验证生成器种子隔离、方法可见 payload 隔离、根级一次性贡献和 fail-closed 行为。

这仍然不是完整的 v20.1 运行时，也不是 pilot 或确认性实验实现。仓库中的 canary、单元测试、合成数据和输出均不能支持论文效果主张，不能迁移或重命名为 `D_test`。

## 当前状态

| 层级 | 状态 | 可以说明什么 | 不能说明什么 |
| --- | --- | --- | --- |
| legacy-v5 玩具链 | 保留 | BPA、时间折扣和基础融合代码可运行 | 不能作为 v20.1 实现或论文实验证据 |
| G1 generator canary | 已关闭当前工程切片 | physical/noise/arrival 子流分离、同配置可重放 | 不能证明24层场景有效、真实过程逼真或功效充分 |
| G1 payload isolation | 已关闭当前工程切片 | 方法可见 `CanonicalObs` 不携带标签、路径、文件名、simulationRun、category、attack/truth；真值进入 scorer-only sidecar | 不能代替容器ACL、真实数据导入审计或统计泄漏探针 |
| G2 duplicate/root canary | 已关闭当前工程切片 | exact duplicate 不重复贡献；同root同版本alternate view只审计；无法安全处理时冻结 | 不能替代完整事务台账或独立实现等价性 |
| Pilot / power-confirm / D_test | **PENDING / BLOCKED** | 无 | 当前禁止生成确认性数据和正式结果 |

“已关闭”仅指当前测试覆盖的狭窄工程合同，不表示 v6.7 对应 Gate 已整体关闭。

## 快速验证

从仓库根目录运行完整测试：

```bash
python -m pytest -q
```

以该命令当次输出为准；任何测试失败都表示当前资格切片尚未闭合，不能继续晋升。

生成一个非确认性 canary 包：

```bash
python -m experiments.shakedown_canary --output-dir <D_shakedown空目录>
```

例如：

```bash
python -m experiments.shakedown_canary --output-dir D_shakedown/SHK-001
```

输出目录必须不存在或为空；路径中出现 `D_test` 会被程序拒绝。可选参数为：

```text
--base-seed INT
--physical-bundles INT   # 最少8
--noise-views INT        # 最少2
--arrival-views INT      # 最少2
```

默认 canary 使用8个 physical bundles、每个2个noise views、每个noise view再生成2个arrival views。它只生成隔离工件和QA记录，不执行候选方法；`run_ledger.jsonl` 的状态是 `GENERATED_NOT_EXECUTED`。

## Canary 输出与禁止事项

输出目录包含：

- `NON_CONFIRMATORY_DO_NOT_PROMOTE`：不可晋升标记；
- `scorer_only_truth_store.jsonl`：仅供 scorer/orchestrator；
- `method_visible_operational_payload.jsonl`：方法可见负载；
- `arrival_manifest.jsonl`：arrival/lifecycle 视图；
- `run_ledger.jsonl`：生成台账，不是方法执行结果；
- `qa.json`：seed、重放、hash和payload隔离检查；
- `manifest.json`：`confirmatory=false`、`claim_support=none` 及工件hash。

以下操作被禁止：

- 把 canary 输出改名、复制或迁移到 `D_test`；
- 从 canary 计算 A 对 G* 的效果量、置信区间或论文主结果；
- 把 `GENERATED_NOT_EXECUTED` 解释为方法已执行；
- 在 pilot、power-confirm、Allocation/TestManifest 密封前生成确认性种子；
- 用当前 legacy runner 冒充 v20.1 的 A 或独立实现 C。

## 已关闭的工程切片

### 1. Seed split 与重放

- `Scenario` 保留 legacy `seed` 接口，并显式支持 `physical_seed` 与 `noise_seed`；
- 改变 physical seed 会改变 truth hash；
- 只改变 noise seed 会改变观测证据，但不改变 truth；
- canary 另行派生 arrival seed，arrival变化只改变arrival manifest；
- 同一完整配置的truth、payload和arrival逐位可重放；
- canary按 physical bundle 记录共享truth hash。

### 2. Method-visible payload isolation

- `CanonicalObs` 不新增任何truth metadata字段；
- TEP的fault label、simulationRun和源文件信息只进入 scorer-only sidecar；
- CWRU的label及源文件路径/文件名只进入 scorer-only sidecar；
- MVTec的image path、filename、category和defect type只进入 scorer-only sidecar；
- `BaseLoader.scorer_only_sidecar()` 与 `scorer_only_metadata()` 是显式分离API；
- canary对方法可见payload执行禁止字段扫描并验证独立hash。

### 3. Duplicate/root conflict fail-closed

- 相同 `event_id` 且指纹完全一致：只追加 `DUPLICATE_AUDIT`，不重复改变信念；
- 同一root、同一version的alternate view：只追加 `ALTERNATE_VIEW_AUDIT`；
- 同一root出现更高version而没有事务replacement ledger：冻结并返回 `HIGHER_VERSION_REQUIRES_TRANSACTION_LEDGER`；
- event-id equivocation、完全冲突等无法安全提交的状态：原信念/时间/history不变，状态冻结并留下审计记录；
- 旧的 `Evidence(m, t_gen, source_id, reliability)` 位置参数接口仍可运行。

## 仍然 PENDING，禁止越界声明

### 完整事务生命周期

当前仅做保守阻断，尚未实现或资格化：

- 原子 `replacement` 与旧贡献撤销；
- replay ledger、处理token和幂等恢复；
- retire、merge、supersede及版本DAG；
- CAS interleaving、ABA、tombstone/epoch；
- crash recovery和append-only事务裁决；
- v20.1完整PCR/OLR、setwise certificate、mapping/route/runtime合同。

### 双实现与正式方法臂

- 独立实现 C 及A–C表示/状态/hash等价性IUT；
- MethodRegistry、InformationSetDiff和冻结的arm×frame matrix；
- A、A的消融、M0–M4和强基线的公平实现；
- `D_select` 中唯一主比较 G* 的选择与冻结。

### 真实数据、场景与统计资格

- 两拓扑CSTR、24候选层的可达性和ActionTruth双复核；
- TEP/CWRU/MVTec/HA4M等真实数据的run-level split、访问隔离和数据卡；
- real datasets、独立模拟器、unseen topology或shadow/HIL支持；
- mapper calibration/qualification、coupling sensitivity及适用域；
- 独立pilot的coverage、ICC、discordance、tail和共同无效率；
- 完整gate的power-confirm、Type-I检查和盲态SSR。

### D_test 密封

以下条件尚未满足：

- AllocationManifest、TestManifest及所有容器/代码/hash签名；
- 独立test master key、ACL和scorer-only truth store；
- 预签失败映射、common-invalid、rerun裁决和单次锁定分析；
- 正式样本量、层分配、SESOI、no-harm margins和G*；
- `test_opened=true` 的合法解封流程。

因此当前结论固定为：

```text
G1/G2 NON-CONFIRMATORY CANARY AVAILABLE
PILOT NOT QUALIFIED
CONFIRMATORY GENERATION FORBIDDEN
D_test SEALED/UNOPENED
```

## 主要代码入口

| 路径 | 作用 | 当前边界 |
| --- | --- | --- |
| `src/rfb/benchmark/generator.py` | physical/noise seed分离的合成生成器 | G1 canary，不是真实过程生成器 |
| `src/rfb/loaders/` | 各流加载器和scorer-only sidecar | 合成fixture资格，不代表真实数据闭合 |
| `src/rfb/temporal.py` | 时间融合及最小root/duplicate fail-closed canary | 非完整事务运行时 |
| `experiments/shakedown_canary.py` | 非确认性隔离包生成入口 | 不运行方法、不产出结果 |
| `tests/` | legacy回归、G1/G2合同和canary测试 | 工程测试，不是实验数据 |

Python要求为3.11+（`src/rfb/capacity.py` 使用 `enum.StrEnum`，3.10 无法导入；此前"3.10+"的声明有误，2026-07-23 验收修正）。依赖除 requirements.txt 所列外，门禁证据链（`gate_evidence.py`、`g004_evidence.py` 及 Gate A/B 测试）硬依赖 `jsonschema`。正式复现环境、容器锁和外部数据依赖仍待密封。
