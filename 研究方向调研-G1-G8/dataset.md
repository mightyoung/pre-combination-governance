# DataSet

> 候选数据集的**可得性侦察**与获取登记。**当前状态：全部未下载。**
> 纪律：下载须在方向通过「硬性关卡」（关键强基线 / 数据 / 算力 / 合规）且最小可证伪实验（MME）计划**获人工批准**后执行；下载完成当刻按文末「获取登记要求」补齐目录结构、处理过程与坑。
> 侦察记录：2026-10-08，全部为公开官方页核实（官方仓库 / 数据集页 / 发布说明）；未执行任何下载或代码运行；许可与体量以官方页当天信息为准。

## 总览（六源基准与 MME 候选）

| 数据集 | 对接证据流 | 官方渠道 | 许可 | 体量 | 获取难度 | 状态 |
|---|---|---|---|---|---|---|
| HA4M | 人（装配动作六模态：RGB/深度/IR/点云/骨架） | CNR GitLab `baltig.cnr.it/ISP/ha4m`；Science Data Bank DOI `10.57760/sciencedb.01872` | CC BY 4.0（以仓库 LICENSE 为准） | **2.92 TB** [sources/s56@1]（217 文件，V2） | 低（公开直下；全量大） | 未下载 |
| HM-SYNC | 人机（真实制造设备交互：深度图 + 3D 骨架） | HuggingFace `saluslab/HM-SYNC` | MIT | 15.5 GB [sources/s57@1] | 低 | 未下载 |
| MECCANO | 人（第一人称装配：RGB/深度/注视） | `iplab.dmi.unict.it/MECCANO/` + GitHub `fpv-iplab/MECCANO` | 未核（以官网为准） | 未核 | 低-中 | 未下载 |
| MIMII | 机（设备异响音频：阀门/泵/风机/滑轨） | Zenodo `10.5281/zenodo.3384388` | CC BY-SA 4.0 | ≈68 GB（8 分包，单包 7.5–10.9 GB）[sources/s60@1] | 低（量大） | 未下载 |
| XJTU-SY | 机（轴承全寿命振动） | GitHub `WangBiaoXJTU/xjtu-sy-bearing-datasets`（多镜像） | Academic Use（须引用） | GB 级（未精确核） | 中（镜像稳定性因地区而异） | 未下载 |
| CWRU | 机（轴承故障振动，12k/48k） | `engineering.case.edu/bearingdatacenter` | 未明示（公开可用 + 引用惯例） | 小（.mat 分包） | 低（注意旧域名已废） | 未下载 |
| TEP（Rieth 扩展集） | 环/法（过程变量与故障，52 变量 / 20 故障） | Harvard Dataverse DOI `10.7910/DVN/6C3JR1` [sources/s64@1] | CC0（公共领域） | ≈1.8 GB | 低 | 未下载 |
| TEP（Reinartz 扩展版，备选） | 同上（29 状态 / 2800 runs） | `web.mit.edu/braatzgroup/links.html` [sources/s65@1] | 以页面为准 | ≈1.9 GB | 低 | 未下载 |
| mTSBench（19 数据集 / 344 序列） | 通用多变量时序异常检测池（G7 已追踪） | GitHub `PLAN-Lab/mTSBench` + HuggingFace `PLAN-Lab/mTSBench` | 未核（以仓库为准） | 以仓库为准（支持按数据集子集取用） | 低（git-lfs） | 未下载 |
| SWaT（备选） | 环（水处理过程 + 注入攻击真值） | iTrust/SUTD Datasets 页 | 研究申请制；不可再分发 | 未核 | 中（审批约 3 个工作日） | 未申请 |

> 补充：论文主工程远端 `datasets/` 已有 HA4M、HM-SYNC、MECCANO、MIMII、TEP 的归档或部分归档与核验记录（如 MIMII `6_dB_valve.zip`、TEP 全量核验）——那些属主工程侧资产，与本表登记分开；本项目取用时仍须单独核验。

## 各候选要点（侦察记录）

### HA4M（人）
- 内容：12 类装配动作 × 41 被试 × 217 视频（Azure Kinect 采集）；六种同步模态：RGB、深度图、IR、RGB-深度对齐、点云、骨架；共标注 4123 个动作段；任务为行星轮系（EGT）装配。
- 渠道：CNR GitLab（持续扩充，含 LICENSE 文件）＋ Science Data Bank V2（2023-12-12 更新，217 文件）。
- 坑：**全量 2.92 TB** [sources/s56@1]——必须按「单被试 / 单模态 / 单动作」分包取用；构建 loader 前先冻结子集清单。
- 用途：人（H）流动作/装配事件证据源；发射器验证与 MME 场景播种。

### HM-SYNC（人机）
- 内容：电弧增材制造（WAAM）设备前 6 个月深度图 + 3D 骨架（隐私保护姿态跟踪），1228 次交互；Carnegie Mellon University 出品。
- 渠道：HuggingFace `saluslab/HM-SYNC`（train-000~013 分包，共 15.5 GB）；许可 MIT（论文与 HF 页一致）[sources/s57@1]。
- 用途：人机交互时序/会话证据流；少见地直接面向「人机交互制造场景」的公开数据。

### MECCANO（人，备选）
- 内容：第一人称装配（玩具摩托）RGB + 深度 + 注视信号，20 被试 × 2 国；8857 个动作段、64349 个物体框、61 动作类；含 6 项任务基线。
- 渠道：官网下载页 + GitHub（代码与预训练模型）；主工程远端归档快照中已见。
- 用途：与 HA4M 互补（第一人称 vs 第三人称视觉）；许可口径待回核。

### MIMII（机）
- 内容：阀门/泵/风机/滑轨四类机器的正常/异常声音（8 通道，16 kHz，16 bit），混入真实工厂背景噪声；-6dB 与 0dB 两个信噪档。
- 渠道：Zenodo 3384388 [sources/s60@1]；许可 CC BY-SA 4.0；官方基线代码 `MIMII-hitachi/mimii_baseline`。
- 坑：① 全量 ≈68 GB（单包最大 10.9 GB）[sources/s60@1]，应按机器类别取子集；② 备选 **DG 版**（Zenodo `6529887`）许可为 **CC BY-NC-SA（禁止商用）** [sources/s61@1]，选型时注意差异；③ 主工程已有 `6_dB_valve.zip`（4183 个 wav）核验记录，可交叉核验，但不得外推为整个 MIMII 结论。
- 用途：机（E）流设备状态证据；容量探测与 loader smoke 候选。

### XJTU-SY（机）
- 内容：15 个轴承全寿命（加速退化）数据，3 种工况（35Hz/12kN、37.5Hz/11kN、40Hz/10kN）；水平+垂直振动，25.6 kHz 采样，CSV 格式 [sources/s62@1]。
- 渠道：官方 GitHub 仓库 README 汇总多镜像（作者网站 / MEGA / Google Drive / MediaFire / Baidu / Dropbox）；另有 Mendeley 处理版（`data.mendeley.com/datasets/mpn45f4gxc/1`，.mat）。
- 坑：镜像可用性随地区波动（下载时逐个试连并校验）；许可口径「Academic Use」+ 必须引用 Wang et al. 2020。
- 用途：机流退化/寿命证据；与 CWRU 形成「故障分类 vs 全寿命」互补。

### CWRU（机）
- 内容：2hp 电机试验台轴承数据；正常基线 + 驱动端/风扇端故障（内圈/外圈/滚动体 × 0.007/0.014/0.021 英寸）；12k/48k 采样；4 种负载（0–3 hp）[sources/s63@1]。
- 渠道：`engineering.case.edu/bearingdatacenter`（download-data-file 页直下 .mat）。
- 坑：**旧域名 `csegroups.case.edu` 已废弃**（证书失配/连接失败多为旧链接误报）；官方页未明示许可（学术使用 + 引用惯例）。
- 用途：机流故障证据；主工程已有 CWRULoader 实现，可作兼容性参照。

### TEP（环/法）
- 两个版本：① Rieth et al. 2017 扩展集（Harvard Dataverse，CC0，≈1.8 GB [sources/s64@1]；20 故障 × 500 runs，训练 500 / 测试 960 长度，52 变量）；② Reinartz et al. 2021 扩展版（MIT Braatz 组页面，≈1.9 GB [sources/s65@1]；29 状态 × 2800 runs，长度 2000）。
- 用途：环/法流过程变量与故障真值；容量探测代表域（主工程 C2 sizing smoke 即用 TEP）。
- 坑：版本口径需先冻结（Rieth vs Reinartz 的故障数/长度不同），否则跨论文数字不可比。

### mTSBench（通用池）
- 内容：344 条多变量序列 / 19 数据集 / 12 领域 / 24 检测器（含 LLM-based）；三种无监督选择器基线；论文附录含 19 数据集的具体说明（本地已存）。
- 渠道：GitHub（代码）＋ HuggingFace（数据，git-lfs；支持按数据集子集取用）。
- 用途：G7 方向基准；MME 的「外部检测器池」与性能矩阵来源。
- 坑：个别子数据集有已知口径问题（如 MITDB/SVDB 的平凡异常、SWaT 同源访问限制），论文附录已提示；许可未核。

### SWaT（环，备选）
- 内容：水处理试验台 51 传感器 × 11 天（前 7 天正常 + 后 4 天含 41 次注入攻击）；主文件 `SWaT_Dataset_Normal_v1` / `SWaT_Dataset_Attack_v0`。
- 渠道：iTrust/SUTD Datasets 页**申请制**（约 3 个工作日审批）；**不可再分发**。
- 用途：需要「过程 + 攻击」双真值场景时的备选；与 TEP 互补。
- 坑：若要使用应提早申请；许可限制影响基准发布（不得把原始数据打包进公开资产）。

## 自建 / 半合成部分（不依赖下载）

- 料、法两流（物料台账、作业票、点检记录等）：按 72 元素树规则化生成（合成），与真实数据集按事件时间轴对齐（六源半合成基准的核心工作量在此）。
- 依赖操纵注入层（provenance 四类：多视图重复、多版本重写、共因、抄改）：随基准构建脚本生成，用于制造「同一物理事件重复进入」的受控场景。
- 测流（质量元层）：由来源统计（时间戳、版本、血缘、校准状态）派生，无需外部数据。
- 真值口径：自建层负责标签规则重写，背书口径见方向 2 文档 Phase 1′（GB/T 13861-2022 等）。

## 获取登记要求（下载后立即补，替换本占位节）

- 每个数据集下完立刻补：目录结构 / 记录格式、处理过程（去重、格式转换、过滤）、坑（重复条目及其指标影响）、split 口径（按维度而非样本）、下载与校验命令（断点续传 + SHA-256/md5 校验）。
- 不得把凭证写入仓库 / 脚本 / 日志；校验值以官方页公布值为准（MIMII 页含逐包 md5）。
- 本文件只登记事实与计划，**不构成下载授权**；下载动作以获批的 MME 计划为准。
