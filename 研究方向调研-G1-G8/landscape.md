# 领域地图：八方向追踪（首轮 2026-10-08）

> 模式：discover / 梳理前沿。本文是主交付物；阅读路线见 `paper-reading.md`；检索与证据流水见 `research/*.jsonl`。
> 阅读深度声明：除特别注明外，本轮文献均只读到摘要或检索片段（`reading_depth=abstract` 或 `source_only`），不得在论文中冒充全文证据；标准状态以 iso.org 官方页面为准。

## 0. 总览

| 方向 | 频率 | 核心问题 | 本轮关键锚点 | 新证据（2025–2026） |
|---|---|---|---|---|
| G1 依赖证据/冲突 | 月度 | 高冲突/依赖证据的度量、修正与组合 | arXiv 2608.13108；Tang 2026；Lu & Zhu 2026；Fei 2025 SLR；IEECR；gamma-CUBV [papers/p01@1][papers/p30@1][papers/p44@1][papers/p45@1] | 10 |
| G2 EDL×LLM 校准 | 月度 | 生成式证据的校准、单趟不确定性与防污染 | arXiv 2507.18366；ICLR 2026 C-EDL；BELIEFRAG；EESD；SLLCP [papers/p05@3][papers/p49@1][papers/p52@1] | 12+2 资源 |
| G3 多智能体聚合与记忆治理 | 季度 | 辩论/投票之外有原理的聚合；记忆投毒治理 | arXiv 2605.06028（Blackwell）；KDD 2026 consensus；OWASP 2026 [papers/p10@3][papers/p13@1] | 5+2 |
| G4 provenance×BF | 季度 | 谱系如何改变组合算子本身 | PRIMEX-PEV（JAIF 2025-12）；arXiv 2604.21618；Yu 2008 经典 [papers/p16@1][papers/p18@1] | 2+1 |
| G5 HRC 标准与动态风险 | 事件驱动 | 标准口径与动态风险方法前沿 | ISO 10218:2025；ISO/AWI 15066-1 在研；(EU) 2023/1230 [papers/p19@1][papers/p22@1] | 4+3 |
| G6 屏障/过程安全 | 半年度 | 动态屏障与 AI-HAZOP 的真实效能 | AIChE PSP 2026 两篇；ChatP&ID；Guo 2026；19–37% 有效性 [papers/p27@1][papers/p32@1] | 5 |
| G7 本体栈与数据质量 | 半年度 | 异构接入的语义标准与质量基准 | AAS/IEC 63278；arXiv 2608.24918；mTSBench；事件级 AD 基准 [papers/p34@1][papers/p36@3] | 4 |
| G8 前兆与选择性预测/IUT | 半年度 | 拒判的统计证书与预警提前量 | SCoRE 2026；joint certificate 2026；临床分流 2026 [papers/p38@3][papers/p40@3] | 3+2 |

---

## 1. G1 依赖证据/冲突新作（月度）

### 最新进展
- **混沌冲突度量 + 历史经验加权**（arXiv:2608.13108，2026-08）[papers/p01@1]：把「证据间冲突」与「证据内非特异性」联合度量（五条形式化性质），用谱聚类划分决策空间、遗憾理论计算历史可靠性画像；16 个基准平均 F1 85.78 / AUC 93.30，超 8 个 DST 基线。
- **复杂网络可靠性模型**（Tang et al., Group Decision and Negotiation 35(3), 2026）[papers/p02@1]：把证据体当网络节点、证据距离当边权，用直接/间接强度定权，缓解高冲突反直觉。
- **软似然 + 可靠性优化**（Lu & Zhu, EAAI 163, 2026-05）[papers/p03@1]：SLSQP 约束优化估源相似度 + OWA 权重替代差分权重，单步软似然融合；目标识别 +0.14pp。
- **中文期刊动向**（兵器装备工程学报 2026 增刊）[papers/p04@1]：模糊隶属度→全集未知分配 + 内聚度/冲突度双维加权——反映「BPA 未知项的物理意义」仍是活跃问题。
- **领域 SLR 锚点**（Fei, Li & Ding, Neurocomputing 643:130419, 2025）[papers/p30@1]：DST × 安全/事故/应急的系统综述，按 4R 危机管理框架分类——证明「安全 × 证据理论」不是空白而是**窄口**，我们的差异化必须在治理/依赖/生命周期维度上主张。
- **量子干涉再分配（IEECR, SSRN 7549569, 2026）**[papers/p44@1]：把量子概率的干涉效应引入 D-S——焦点元素关联图量化命题间干涉强度，将多元素焦元质量再分配至单点，模糊隶属度生成 BPA + Deng 熵排序证据；四数据集超 5 个代表性融合方法（91.00% / 85.00%）。
- **依赖感知风险界（gamma-CUBV, arXiv:2610.03465, 2026-10）**[papers/p45@1]：单一指数框架统一含依赖感知的风险界族；折间等相关下有效折数 K_eff=K/[1+(K−1)ρ]，多源加权融合按「未来风险上界最小化」选权——**依赖折扣首次以风险证书语言出现在分析侧**（与 G3 的 N_eff 同构；本文主张治理侧，不与之争新颖）。
- **Information Fusion 125（2026）目录信号**[papers/p46@1][papers/p47@1]：过自信/非合作行为的多尺度群决策融合（103401）、概率密度的边际分布鲁棒融合（103423）——顶刊入口在「行为偏差 × 鲁棒融合」。
- **IJAR 认知不确定性应用**（2026）[papers/p48@1]：元公平框架下 DST（Yager 函数 + 厚区间）医疗风险预测，含 50 人用户研究（经中文新闻转述，引用前核原文）。

### 核心方法对比
| 方法族 | 依赖处理 | 冲突处理 | 决策输出 | 局限 |
|---|---|---|---|---|
| Dempster 归一化 | 要求 distinct | 归一化放大冲突 | 单一 BetP | 高冲突反直觉（经典） |
| PCR5/PCR6（Dezert） | 不处理依赖 | 比例再分配部分冲突 | 质量函数 | 多源组合规模增长；≠依赖 |
| cautious / 最小承诺 | 幂等保守 | 保留无知 | 区间 | 保守性代价 |
| ER/ERr-DE/ER-TLD | 依赖度参数化 | 权重-可靠性分离 | 效用/区间 | 依赖参数或已知或难估 |
| 依赖感知风险界（p45） | K_eff 有效折数折扣 | 权重=未来风险上界最小化 | 风险界/证书 | 分析侧工具；不涉组合前治理 |
| 本轮新作（p01–p04；p44/p46–p48） | 历史/网络/量子/行为先验 | 双维/混沌/干涉度量 | 区间或分类 | 仍属单次融合，无流式累计视角 |

### 现存瓶颈
单次组合规则拥挤且增量收窄；依赖仍以「估计参数」或「内容相似度」为主，**没有把依赖当前置的资格路由**；绝大多数不评估流式/累计影响。本轮增量出现依赖折扣的**分析侧证书化**（p45）与冲突再分配的**量子化新形态**（p44），但组合前资格、exactly-once 与生命周期治理仍无对应工作——本文差异化空间未被压缩。

### 后续关注重点
IF / Fuzzy Sets & Systems / IJAR / ESWA / KBS 的 dependent evidence、conflict measure、cautious 新作；BELIEF 会议论文集；Yongchuan Tang / Yong Deng / Xinyang Deng 课题组动向；IEECR 期刊正式版与 gamma-CUBV 的评论跟进。

### 来源与时间范围
WebSearch 2026-10-08（增量轮 5 次：IF 卷目 / FSS+IJAR / ESWA+KBS / Deng 组雪球 / Denœux+PCR 定向；首轮 2 次见 q04–q06）；dblp 详情页直连被反爬拦截，仅用搜索快照；覆盖 bounded（未穷尽）。

---

## 2. G2 EDL×LLM 校准（月度）

### 最新进展
- **证据知识蒸馏**（arXiv:2507.18366，2025-07）[papers/p05@3]：把需多趟采样的不确定性教师（BNN/Laplace/BayesPE）蒸成 LoRA 学生，单趟输出；softmax 与 Dirichlet（evidential）两条学生路线，后者显式建模认知不确定性。代码开源（BPE-KD）。
- **DRO + 证据集成校准微调基础模型**（ICLR 2026）[papers/p06@1]：微调后验变平坦/多峰导致 UQ 失效，用分布鲁棒优化 + 证据理论做多样性集成，理论保证校准改进；覆盖大视觉语言模型。
- **Evidential Transformation Networks（ETN，2026）**[papers/p07@1]：post-hoc 轻量模块，在 logit 空间学样本相关仿射变换→Dirichlet 参数，让现成预训练模型输出 EDL 式不确定性，单趟、免重训——对「为 VLM 证据源外挂校准器」是现成路线（source_only：经二手技术媒体转述，引用前定位原文）。
- **EvidentialRAG（2026-07）**[papers/p08@1]：用 EDL 量化并缓解多源 RAG 的信息冲突——直接对应语义证据的冲突处理（source_only：经论文聚合站转述）。
- **post-hoc 冲突感知校准成形**：C-EDL（arXiv:2506.05937，v3 2026-10-02 = ICLR 2026 正式版）[papers/p49@1] 与 CLEAR（arXiv:2610.01384）[papers/p50@1] 都以「任务保持变换 / 潜空间扰动视图」量化表示分歧或潜空间冲突，据此动态压低证据强度；C-EDL 把 OOD/对抗覆盖降低至约 55% / 90%，CLEAR 提升 OOD/对抗 AUROC +8.29 / +5.01 且比同类 post-hoc 快 17.4×——**ETN 之外第二条成熟 post-hoc 路线（对象是单模型内部）**。
- **证据蒸馏「支持 vs 质量」分离**（EESD, arXiv:2610.08514, 2026-10-06）[papers/p51@1]：执行相关性（支持）与有效伪计数（证据量）分开建模，Dirichlet 后验产生不确定性惩罚权重；NLL 降 55.0–59.3%，一轮修正学习后 Pass@1 15.0→20.4%（[+2.8,+8.0]pp）——与本文「贡献守恒/质量元层」同向的 LLM 侧旁证。
- **RAG 证据状态治理登场**（BELIEFRAG, arXiv:2609.39139）[papers/p52@1]：显式状态（充分性/可靠性/冲突/不确定性/缺口/获取成本）闭环控制检索—改写—验证—回答—停止—拒答；F1 0.572 vs 0.555 且 token 省 39%；「校准的可回答性」最有效，但**来源漂移可使同一决策信号失效**——LLM 证据治理最邻近工作，须引用定位（见 §9 第 4 条）。
- **conformal 校准外挂成熟**：SLLCP（冻结 VLM + 标签局部化 conformal，肇事轨迹识别 89.6%/88.4% vs 基线 4.6%/39.1%，arXiv:2610.02765）[papers/p53@1]；paraphrase-aware conformal（改写鲁棒，NeurIPS 2026，arXiv:2610.04239）[papers/p54@1]。
- **系统级不确定性传播**（arXiv:2604.23505，雪球发现）[papers/p55@1]：不确定性在复合 LLM 系统内跨边界被变换复用，早期错误传播复合、难检测难治理；给出 P1/P2/P3 分类与五个开放挑战——与本文「生命周期一致治理」问题意识直接同构，可引为问题动机。
- **资源**：awesome-evidential-deep-learning（本轮经 raw README 核实，48KB；**列表最后更新 2025/01，实际已停更**——2026 年 G2 新作不能依赖该列表，须走论文检索）。列表确认含 4 篇综述（2022 belief theory meets DL、2022 IJCAI evidential reasoning survey、2023 TMLR prior/posterior networks、2024 arXiv comprehensive EDL survey [papers/p09@1]）与 IB-EDL（ICLR 2025，openreview PDF + 代码库）[papers/p43@1]；BFTA 2025 Denœux 讲义（Evidential ML 全集）。

### 核心方法对比
| 路线 | 不确定性来源 | 开销 | 适配 LLM/VLM 证据源 |
|---|---|---|---|
| 贝叶斯/集成 | 参数/采样 | 多趟，高 | 教师模型 |
| evidential 蒸馏 | Dirichlet 证据 | 单趟（学生） | 已支持文本分类 |
| ETN post-hoc | logit→Dirichlet | 单趟 + 小数据 | 适配现成预训练模型 |
| 冲突感知 post-hoc（p49/p50） | 表示分歧/潜空间冲突 | 单趟 + 校准数据 | 适配现成模型；未验 LLM 危害推理 |
| conformal/black-box（p53/p54） | 经验分布 | 校准集 | 黑盒可用但无 epistemic 分解；改写/漂移鲁棒性开始被处理 |
| 自一致性/verbalized | 采样方差 | 多趟 | 不等于经验正确率（校准漂移） |

### 现存瓶颈
可靠性结论多限于分类任务；开放文本危害推理的外推未证（项目内 v13 即引用 evidential distillation 的同一局限）；post-hoc 校准与版本漂移的联合影响缺少系统评测；RAG/智能体侧已出现「证据状态治理」（p52）与系统级传播分类（p55）——融合层与 LLM 证据状态之间的接口（冲突/缺口信号如何进入 BF 组合前治理）尚无系统评测，是本轮新暴露的空白。

### 后续关注重点
IB-EDL（ICLR 2025）之后的 LLM-evidential 新作；arXiv cs.CL/cs.LG 的 "evidential + LLM/RAG" 组合；校准度量（ECE/Brier/NLL）在开放生成上的可用性；post-hoc 冲突感知校准（C-EDL/CLEAR 谱系）与 BF 治理层的接口。

### 来源与时间范围
WebSearch 2026-10-08（增量轮：evidential distillation/post-hoc、RAG 冲突、conformal 各 1 次 + awesome 列表复核 q07@2/q29@1）；关键条目经 arXiv abs 页逐条核验版本；覆盖 bounded。

---

## 3. G3 多智能体聚合与记忆治理（季度）

### 最新进展
- **Blackwell 信息量视角的形式化判决**（arXiv:2605.06028，2026-05）[papers/p10@3]：证明投票与辩论诱导的信息结构**不优于全体私有信息的池化**，贝叶斯池化后验是 Blackwell 序下的上界；MA-PoP（product-of-posteriors）在 6 个 QA 基准超过 SOTA 辩论/投票且 token 更少。**这是本项目「辩论/投票无原理性」论证的 2026 最强外部佐证，同时引入强竞争协议（池化后验）——MME 基线必须认真考虑。**
- **共识≠正确**（KDD Workshop on Evaluation and Trustworthiness of Agentic AI，2026-08-09）[papers/p11@1]：15 任务 × 5 模型族；协议诱导的同意（agreement）miscoverage 18–47%；有效智能体数 N_eff≈N/(1+(N−1)ρ) 诊断；建议 split-conformal 证书 + 校准辩论。**直接支撑「模型数量≠独立信息量」与两轴区分策略。**（source_only：经行业博客转述，含 26.5 万样本一致性研究引述。）
- **反向贝叶斯锚定**（arXiv 2026-09-10，When Agents Disagree）[papers/p12@1]：前向/反向两种 factorized 后验的 JS 一致性排序，MinJS/FwdJS/LogLin 三策略，分歧子集增益最大（source_only：经科技媒体转述）。
- **OWASP Top 10 for Agentic Applications 2026**（2025-12 发布）[papers/p13@1]：ASI06 记忆与上下文投毒等十条风险；配合 Microsoft 2026-02 六十天实测（在 M365 Copilot/ChatGPT/Claude/Gemini/Perplexity/Grok 生产流量中观测到记忆投毒尝试）[papers/p14@1]——记忆治理从研究 artifact 变成运维现实。
- **可信记忆栈**（行业综合，2026）[papers/p15@1]：provenance+validity window、双时序、WAL+MVCC、内容寻址四层；学术锚点 MINJA（2025 记忆注入攻击）、A-MemGuard（2025 共识记忆防御）、"The Log is the Agent"（arXiv 2605.21997）、Multi-Agent Memory 计算机体系结构视角（arXiv 2603.10062）。

### 核心方法对比
| 聚合协议 | 理论性质 | 独立信息处理 | 审计/治理 |
|---|---|---|---|
| 投票/多数 | 无信息增益保证 | 默认独立 | 弱 |
| 辩论（MAD） | 鞅/不优于投票 | 共识内生（多样性坍缩） | 弱 |
| 异构委员会/Council | 降幻觉但增成本 | 模型多≠独立 | 中 |
| 证据论折扣聚合（本项目） | 有界影响/指数遗忘 | 显式折扣+依赖路由 | 强（日志+血缘） |
| 池化后验（MA-PoP）/反向锚 | Blackwell 上界/双因子化 | 相关误差仍可过自信 | 中 |

### 现存瓶颈
池化后验强的协议假设条件独立；证据论路线缺少与 Blackwell/MA-PoP 同量级的**信息量层面**对比；记忆防御（A-MemGuard 等）与融合层的耦合尚无标准评测。

### 后续关注重点
Blackwell/池化后验与证据聚合的对比实验（可作 MME 第五臂）；记忆投毒与 lineage 交叉的评测基准；NIST AI Agent Standards Initiative（2026-02）后续文件。

### 来源与时间范围
WebSearch 2026-10-08；覆盖 bounded。secondary 来源（博客/新闻）仅作线索，引用前须回原文。

---

## 4. G4 provenance × BF（季度）

### 最新进展
- **PRIMEX-PEV 正式出版**（J. Advances in Information Fusion 20(2):152–171, 2025-12；Chang, Kuo, Bar-Shalom, Chong, Mori）[papers/p16@1]：素指数向量（PEV）表示，在指数空间用 GCD/LCM 做冗余消除与谱系保留；扩展异步更新与部分信息传播；面向边缘/联邦/资源受限。**最接近的 lineage-only 强基线有了权威最新版。**
- **事件触发分布式跟踪**（arXiv:2604.21618）[papers/p17@3]：consensus PRIMEX + greedy gossip PRIMEX + 信息码新颖度驱动的事件触发；对比协方差交与集中式。注意 PRIMEX 作用于概率密度（高斯域），**不是信念函数**——作为基线的对应关系须如实写明。
- **经典锚点**（Yu, Kallurkar & Flo, CTS 2008）[papers/p18@1]：provenance-aware D-S 信任评估，避免 double counting 的原则化处理——本项目 C1 的直接思想近邻。

### 核心方法对比
| 工作 | 表示 | 依赖处理 | 重复消除 | 时间维度 |
|---|---|---|---|---|
| Yu 2008 | BF + 软件智能体 | provenance 检测 | 事后解释 | 无 |
| PRIMEX/PRIMEX-PEV | 素指数编码 pdf | 显式谱系 | 代数消除（GCD） | 异步更新 |
| 本项目 | BF + 双注册表 + 账本 | 组合前资格（UNKNOWN 失败关闭） | 根级 exactly-once | 生命周期事件（supersede/merge/retire/replay） |

### 现存瓶颈
PEV 编码假设谱系可由素数乘积忠实编码（高阶超边/部分依赖受限）；BF × provenance 的联合 2026 新作稀缺——**这是 G1/G4 之间真实的空隙**；post-commit equivalence 的撤销-重建仍无标准 benchmark。

### 后续关注重点
JAIF / FUSION 会议的 lineage 论文；PEV 与 BF 的混合编码可行性；IF 期刊 "provenance" 关键词月度追踪。

### 来源与时间范围
WebSearch 2026-10-08（isif.org 官方页 + arXiv）；覆盖 bounded。

---

## 5. G5 HRC 标准与动态风险（标准事件驱动）

### 最新进展（标准口径，2026-10-08 官方核验）
- **ISO 10218-1:2025 与 ISO 10218-2:2025 已发布**（2025-02 出版、2025-04 生效）[papers/p19@1][papers/p20@1]：ISO/TS 15066:2016 的协作应用要求（SRMS/手引导/SSM/PFL 四技术、生物力学接触限值表）**已并入 ISO 10218 系列**，不再作为独立技术规范存在；新增机器人安全相关**网络安全要求**、明确功能安全要求、新机器人分类与测试方法；术语从「协作机器人」改为「协作应用」（机器人+任务+工具+环境整体）。
- **EN 版列入 EU 公报**（2026-09-07，robot-safety.net 转引官方公报）[papers/p21@1]：获机械指令推定符合；但 **(EU) 2023/1230 机械法规 2027-01-20 起取代机械指令**，届时需重新列名。法规明确纳入**集成 AI/ML（行为随时间改变）的机械**与网络安全基本要求——为本项目「治理层 + AI 证据源」提供合规叙事接口。
- **ISO/AWI 15066-1 在研**（iso.org 官方页，2026 查）[papers/p22@1]：Robotics — Physical contact with robots — Part 1: Biomechanical thresholds and data，2025-06-23 立项（stage 20.00），将取代 ISO/TS 15066:2016。行业媒体流传的「ISO/TS 15066:2026 / Annex C 动态力审计（±5N/<100ms）」**未在 iso.org 得到确认**；TÜV 2026-05 认证要求更新公告见 [papers/p23@1]，按行业信号跟踪、引用前须官方核实。
- **动态风险方法前沿**：AI 增强协作机器人综述（Schlotzhauer et al., Results in Engineering 2025）[papers/p24@1]；DT-HRCA 装配综述（MDPI Machines 14(3):255, 2026）[papers/p25@1]；SSM 三十年架构综述（Adamides 2025，经二次转述）[papers/p26@1]；RL 预active SRMS（Tiwari 2025，同上转述）。

### 核心方法对比
| 层 | 代表 | 输出 | 与本文关系 |
|---|---|---|---|
| 标准/合规 | ISO 10218:2025、(EU) 2023/1230 | PL/SIL、符合性 | 边界与威胁模型；不主张标准合规 |
| 感知层 | RGB-D/OpenPose/SSM 传感融合 | 距离/姿态/意图 | 六源中的「人」流证据 |
| 控制层 | PFL/阻抗/MPC 安全滤波器 | 速度/力调整 | 行动侧，融合层只读镜像 |
| 风险评估层（本文） | 证据融合 + 组合前治理 | 风险区间/拒判 | 提供可审计的决策依据 |

### 现存瓶颈
标准把「协作安全性」定义为应用级属性但不规定在线证据治理；AI 安全验证（动态响应审计）尚无统一基准；学术动态风险与标准合规两层皮。

### 后续关注重点
ISO/TC 299 与 IEC/TC 65 发布；(EU) 2023/1230 列名进展；ANSI/RIA R15.06 与 CSA Z434 对齐；15066-1 DIS 进展。

### 来源与时间范围
WebSearch 2026-10-08；iso.org 官方页（p22）+ EU 官方公报转引（p21）+ 行业媒体（p23，待核）。

---

## 6. G6 屏障/过程安全（半年度）

### 最新进展
- **动态屏障管理系统**（AIChE Process Safety Progress, prs.70040, 2026）[papers/p27@1]：Bowtie + 企业数据 + 实时告警/绩效/检查表闭环更新风险分；对齐 ANSI Z10/ISO 45001/45002。
- **矿业动态屏障监测**（AIChE PSP, prs.70015, 2026）[papers/p28@1]：CCM（连续控制监测）把维护管理工具与风险管理工具双向联通；复述 Qiao 等系统综述指出的三个未决问题（基准确定、实时数据成本-收益、屏障要素交互）。
- **AI-HAZOP 工程化**（TU Delft 过程智能组）[papers/p29@1]：DEXPI Smart P&ID 知识图谱 + ChatP&ID GraphRAG（AIChE Journal 72:e70540, 2026）+ pyDEXPI + DigiCo；生成式 AI 产出节点/偏差/原因/后果/措施草稿，**工程师保持负责**。
- **HAZOP KG 构建**（Guo et al., JLPPI 99:105814, 2026-01）[papers/p31@1]：本体设计与 LLM 信息抽取双优化。
- **关键负面证据**：2026 年一项四模型对比研究显示 LLM 生成的 HAZOP 场景**仅 19–37% 技术有效**（且多建议程序性而非工程性屏障）[papers/p32@1]；DT+AI-HAZOP 批判性综述（Alrowaie 2026 预印本）[papers/p33@1] 给出四条技术路径与失效模式（漂移/传感器故障/幻觉/自满）。

### 核心方法对比
| 路径 | 代表 | 强度 | 风险 |
|---|---|---|---|
| Bowtie+实时数据 | prs.70040/p70015 | 屏障健康闭环 | 依赖数据质量；无认证资格 |
| DEXPI/KG+GraphRAG | ChatP&ID | 可 grounding 的检索 | 仍需人工终审 |
| GenAI 直生 HAZOP | 四模型研究 | 快 | 19–37% 有效性，幻觉 [papers/p32@1] |
| 本文 SafetyArtifactIR | IR+禁止推理清单 | 边界显式、fail-closed | 工件错误不在保证内 |

### 现存瓶颈
动态屏障缺公共基准；LLM 安全分析有效性低且无证书；「屏障独立性」与「证据 distinctness」常被混用（本项目已单列禁止推理）。

### 后续关注重点
AIChE PSP / JLPPI / PSEP / RESS；CCPS RBPS 与新一代工业安全 KPI 结合的报告；EU 机械法规下 SIS/AI 的认证动态。

### 来源与时间范围
WebSearch 2026-10-08；覆盖 bounded；p32 为行业媒体转述的同行评议研究，引用前须定位原文。

---

## 7. G7 本体栈与数据质量（半年度）

### 最新进展
- **AAS 成为采购事实标准**：AAS 元模型已标准化为 **IEC 63278-1**；IDTA 发布 Part 1 v3；Eclipse BaSyx 2.0；EU 数字产品护照（ESPR）与德系车企供应商 AASX 要求驱动采纳 [papers/p34@1]（source_only： practitioner 文章，事实可回 IEC/IDTA 官网核）。
- **语义图统一工业数字主线**（arXiv:2608.24918，2026-08）[papers/p35@3]：本体驱动 RDF 知识图谱统一 11 类系统（ERP/MES/PLM/SCADA/QMS/SCM），78 类/108 对象属性/243 数据属性，援引 ISA-95/OPC UA/eClass/AAS/RAMI 4.0；**实证：阻断 24 个跨系统工具后 recall 1.00→0.31，69% 可发现信号需跨系统连接**；经 287 个 MCP 工具暴露给 LLM 智能体。
- **MTS-AD 基准成熟**：mTSBench（arXiv:2506.21550，v2 2026-02）[papers/p36@3]：19 数据集 344 条序列 × 24 检测器（含 LLM 检测器）；无通用冠军；最好的无监督选择器仅捕获 oracle 的 72%；LLM 检测器精度高但慢 10 倍。
- **事件级扰动基准**（arXiv:2602.15457，2026-02）[papers/p37@3]：统一事件级增强（校准传感器丢失、线性/对数漂移、加噪、窗口平移），14 模型 × 5 公开（SWaT/WADI/SMD/SKAB/TEP）+ 2 工业数据集；图模型在丢失/长事件下迁移最好；归一化流对对数漂移脆弱（F1 0.75→0.57）。

### 核心方法对比
| 层 | 标准/工具 | 作用 | 对本项目用途 |
|---|---|---|---|
| 观测语义 | W3C SOSA/SSN | 观测-特征对象模型 | 源适配层本体 |
| 资产语义 | AAS/IEC 63278、OPC UA | 资产-子模型-语义 ID | 主数据/测点绑定（Q01/Q05） |
| 血缘 | W3C PROV-O | 主体-活动-实体派生 | PCR/OLR 与 ledger |
| 集成 | OBDA/Ontop、RDF KG | 虚拟化查询 | 六源接入矩阵 |
| 质量 | 漂移补偿、事件级基准 | 质量度量与评测 | 质量元层（Q02–Q08）与压力测试 |

### 现存瓶颈
语义标准之间（AAS vs SOSA vs PROV）映射靠工程缝合；实时数据成本-收益未闭环（G6 同款问题）；AD 基准的「事件级」指标未被安全融合论文普遍采用。

### 后续关注重点
IDTA/IEC TC 65 发布；ESPR 时间表；事件级 AD 协议向风险融合评测的迁移；多本体对齐（AAS-SOSA-PROV）论文。

### 来源与时间范围
WebSearch 2026-10-08；覆盖 bounded。

---

## 8. G8 前兆挖掘与选择性预测/IUT（半年度）

### 最新进展
- **选择性预测证书化**：SCoRE（arXiv:2603.24704, 2026-03）[papers/p38@3]——广义 e 值 + 假设检验，对任意有界连续风险给出有限样本信任决策，免均匀集中、可推广到分布漂移；临床分流（Sci Rep 2026, Kwon & Kim）[papers/p39@1]——split/Mondrian/加权 conformal + 成本感知延迟，80% 覆盖率下保留案例错误降 46.7–49.6%；**joint finite-sample certificate**（arXiv:2606.08517）[papers/p40@3]——单证书同时上界被选风险、下界接受概率（1/√p_min 改进 vs 1/p_min）与下界部署效用。**与本文「拒判成本/可用性 no-harm」同构，可直接采用而非自造统计工具。**
- **前兆挖掘/领先指标**：预测性安全分析（near-miss 聚簇、纠正措施逾期、班次压力等领先指标）成为 2026 EHS 软件主线；CanQualify 2026 框架称领先指标+预测模型比滞后指标准 25–40%、案例称 TRIR 降 20–40%（厂商研究/案例，**证据弱，须标注**）[papers/p41@1]；业内共识：需 2–3 年一致数据，最大障碍是数据纪律而非算法 [papers/p42@1]。
- **IUT/共同主终点**：本轮未检索到 2026 新综述；项目内 v6.8 已采用（交并检验、SESOI、no-harm 门、联合功效 Monte Carlo、预算硬门）——**保持项目内权威，外部只需追踪统计社区对 adaptive selection 下证书的新结果（p40 即相关）**。

### 核心方法对比
| 工具 | 保证 | 适用本文场景 |
|---|---|---|
| RC 曲线/自报置信 | 无证书 | 仅诊断 |
| conformal 集合 | 边际覆盖率 | 风险区间输出 |
| CRC/选择性 conformal | 被选案例风险上界 | unsafe-SAFE 复合终点 |
| SCoRE / joint certificate | 风险+接受+效用三重证书 | 可用性-安全对撞的报告格式 |
| IUT（交并检验） | 多共同主终点 α 控制 | 确认性 Phase 2 主检验 |

### 现存瓶颈
证书多假设交换/校准集有效；安全证据融合中「拒判」的效用定义缺标准；前兆预测的受控结局研究稀少（案例多、RCT 少）。

### 后续关注重点
conformal/CRC 在安全关键拒判中的采用；always-valid/sequential testing（在线预警提前量的序贯检验）；near-miss 前兆的有对照评估。

### 来源与时间范围
WebSearch 2026-10-08；覆盖 bounded。

---

## 9. 跨方向发现（对研究方向的三条判断）

1. **（G3→论证）聚合空档被 2026 理论硬化，但竞争协议升级**：Blackwell 结果 [papers/p10@3] 证明辩论/投票不优于池化；论文中「替代辩论/投票」的叙事应从「空档存在」升级为「证据论协议提供投票所不具备的无知表示、冲突度量、依赖路由与拒判语义，且与池化后验可对撞」。MME 第五臂建议加入 product-of-posteriors 型基线。
2. **（G6+G2+G3→设计）「大模型只能是受控证据源」获三向独立证据**：LLM-HAZOP 仅 19–37% 有效 [papers/p32@1]、生产环境记忆投毒实测 [papers/p14@1]、EDL 单趟校准路线成熟 [papers/p05@3][papers/p07@1]——可靠性权重 + 复核门禁 + 校准外挂不是保守而是必要；可在引言引为设计动机。
3. **（G8→方法）拒判统计可证书化，no-harm 不必自造**：SCoRE/joint certificate [papers/p38@3][papers/p40@3] 与可用性下界直接对应 C2′ 的报告与判据；建议 v21 §6.3 引用并采用其证书结构（风险-接受-效用三重），把「拒绝不伪装安全」从设计原则升级为可检验统计陈述。
4. **（G2→邻近警示）LLM 证据治理同步兴起**：BELIEFRAG [papers/p52@1] 的「证据状态」与系统级传播分类 [papers/p55@1] 说明「证据生命周期治理」在 LLM 侧成为热点；本文须在引言明确对象差异（BF 组合前准入/根级守恒 vs RAG 控制回路状态），避免被读作重叠——这是本轮唯一需要主动防守的邻近面。

## 10. 对 v21/v22 修正的直接影响（可执行清单）

| # | 行动 | 依据 |
|---|---|---|
| 1 | 引用口径（修订期规范）：凡引协作安全标准一律用 ISO 10218-1/-2:2025 并注明 TS 15066:2016 并入史；**现稿经逐文件核查未引 ISO 标准、无需替换（2026-10-08）**；跟进 ISO/AWI 15066-1 | p19–p23 |
| 2 | §2 补 Fei 2025 SLR（安全×DST 现状）、PRIMEX-PEV 正式版、Blackwell 2026 | p30/p16/p10 |
| 3 | MME 基线集加入 product-of-posteriors（或明确排除理由）；lineage 基线锚定 PRIMEX-PEV 最新版 | p10/p16 |
| 4 | §6 拒判与可用性判据引用 conformal 证书族，定义风险-接受-效用三重报告 | p38/p40 |
| 5 | 引言引 LLM-HAZOP 19–37% 与记忆投毒实测作语义证据治理动机 | [papers/p32@1][papers/p14@1] |
| 6 | 六源接入矩阵挂接 AAS/IEC 63278-1、SOSA/SSN、PROV-O 现行版本 | p34/p35 |
| 7 | G1 相关：§2 引 gamma-CUBV（K_eff 依赖折扣=分析侧证书，明确不与之争新颖）与 IEECR（冲突再分配最新形态）；IF 125 卷目信号入台账 | p44/p45/p46/p47 |
| 8 | G2 相关：引言/§2 引 C-EDL/CLEAR（post-hoc 冲突感知校准）与 BELIEFRAG（LLM 证据治理，须定位差异）；EESD 作「支持-质量分离」旁证；p55 作问题动机 | p49–p55 |

## 11. 维护机制

- 频率：G1/G2 月度（每月上旬）；G3/G4 季度；G5 事件驱动（ISO/TC 299、IEC、EU OJ、认证机构公告）；G6/G7/G8 半年度。
- 每轮增量：追加 `research/searches.jsonl`、`papers.jsonl`（新文献，阅读深度如实）、`claims.jsonl`；更新本文件对应小节并标注版本；运行 `check-research.py`（Windows 无 fcntl，禁加 `--mark-review`）。
- 编号台账：首轮 q01–q20 / s01–s43 / p01–p43 / c01–c10；2026-10-08 G1/G2 增量轮 q21–q29 / s44–s54 / p44–p55 / c11–c20。
- 文献四分类台账：input / baseline / differentiator / **threat**（威胁新颖性者立即升级处理）。
