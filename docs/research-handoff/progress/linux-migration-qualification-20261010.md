# Linux 云端迁移与新平台资格方案（静态草案，2026-10-10）

状态：专用云端环境待创建；未在Linux运行任何探针或方法。本轮同意推进独立Linux路线与文档准备，不是无限计算许可。已有Muyon环境不能替代研究三专用环境。本文不修改算法、不放宽预算，也不批准安装、收费、修改系统安全/代理或裸跑。

## 可迁移部分与当前不可直接启动原因

静态检查 `tools/worker.py`：两方法的stdin/stdout适配、canonical science投影、observer、vendor方法和checkpoint接口未见Mac专用系统调用，因此算法/适配层有Linux可移植性；这只是源码判断，未实测。Python 3.12.10与已用cryptography46.0.5/jsonschema4.26.0/packaging26/psutil7.2.2，以及attrs/referencing/rpds-py/jsonschema-specifications/cffi/pycparser依赖，需在专用Linux环境先只读盘点。原生扩展与Python解释器必须是Linux对应构件，不能复制Mac二进制；缺包先报告，当前不授权下载或安装。

当前冻结包1,315,572 bytes，SHA-256 `eeba84f69768c86109017f462fbbd4224646d09b2745ee46f08e94f6a83cdf11`；362项manifest SHA `a24c9906645e3c5969d0ba7260bfbdde0644f71686d6a2023cfd1ef4b2bb2559`，未包含真正runtime二进制。它是Mac冻结包，不能原样声称Linux可执行。`tools/supervisor.py:21–27`绑定Mac路径与5,847项运行时哈希；`:29–42`渲染Seatbelt profile，`:122`硬编码sandbox-exec。`tools/combined_run.py:56`同样用sandbox-exec启动受限探针；`tools/runtime_binding.py`明确Mac Python布局。这些要求新Linux构建身份、运行时绑定、manifest/profile与新的独立静态复核，不能覆盖旧Mac包。

Mac本次可见终止traceback：`tools/combined_watchdog.py:126`最终清理阶段调用`:35–41 group_members`，`:37 psutil.process_iter`的Mac backend经sysctl进程枚举被工具沙箱拒绝。`:54–55`运行期采样也递归查询child tree，是类似受限接口的潜在点，但没有保存原捕获错误，不能认定它就是首发点。`combined_run.py:47`有另一组枚举；psutil Linux backend `pids()`使用procfs，故不会经过Mac sysctl路径，但云端/proc可见性与权限是否足够仍未知。迁移不是规避拒绝：必须在新平台用获允许的等效隔离/监督边界重新证明资格，缺条件立即停。

## 最小替换与保持原样

| 层 | Linux所需最小工作 | 必须保持 |
| --- | --- | --- |
| 运行时 | 只读盘点现有Python/依赖；新增Linux路径/构件哈希绑定；不搬Mac .dylib/.so | 无secret/.env读取，无任意.pth执行或未授权安装 |
| 隔离启动器 | 用环境已有且允许的Linux隔离工具/namespace与seccomp/等效机制取代Seatbelt；只挂载代码/runtime最小只读树，oracle/reference/sidecar不给worker；public输入经pipe | 无出网、无worker写文件、fork拒绝、外部读写/链接逃逸拒绝；不bind宿主home/凭据或开放整个宿主根 |
| 监督/资源 | 核验可读取owned process的/proc CPU/RSS、可回收子进程并受控kill进程组；保持累计CPU账本、pid创建身份、等待后的CPU与输出reserve，保证失败时仍尽力保存最终回执 | 不把AccessDenied当通过；不遗漏已回收CPU、资格/control children/监督/清理；不能用cgroup memory.current冒充原RSS指标 |
| 资格 | 新Linux profile/runtime/manifest精确绑定，使用同一次单批总账；适配Linux预期errno/退出语义并单独静态审核 | 全部资格实际通过才允许科学worker；旧Mac receipts不可复用 |
| 科学与判定 | 保留两方法vendor、worker/observer科学语义、S2-N8 public/sidecar/reference及数值合同；仅新平台launcher/binding/review元数据 | ES→Proposed各一次instrumented warmup；2ACK/6checkpoint，容差1e-12；失败保存，不修改oracle求通过 |

如采用bwrap，先只读检查已有binary与namespace能力；不假定Linux有可用user namespace。此前Linux namespace/bwrap条件不足必须视为真实阻断。容器存在、/proc可读、结构校验通过都不足以证明上述边界。cgroup若可用仅作为现有授权委派范围的辅助，不创建系统级权限或擅改内核配置；最低仍须证明实际累计账本和终止机制。若平台不能提供等效隔离，报告缺失条件，转回取得正常Mac工具审批的路线也需新一次授权。

## 资格检查与预算

先冻结新Linux构建和独立静态审查，再取得精确构建/平台/路径的一次计算授权与工具审批。首次无害自检纳入同120秒wall/60秒CPU总账；不得先消耗一轮再自动重启预算。若无法在该总额内完成，停止并报告，不加时。

资格保留16个actor slots、最多2个合成控制child、无重试；Linux预期拒绝码必须在探针执行前冻结，不用Mac固定errno13套结论。覆盖：允许读正控/隔离读正控、外部读拒绝、输入写与外写拒绝、符号链接逃逸拒绝、仅本机loopback正控与隔离网络拒绝、fork正控及worker拒绝、TERM-resistant child/进程组清理、已回收CPU聚合与低阈值停止、单与总RSS、输出上限、global deadline。资格使用无敏感新nonce fixtures，无研究imports/公网请求；网络正控只用于对照，不准科学worker网络。

资格阶段45wall/8CPU/1MiB与2CPU保守reserve都在共享总额内。全部通过后仅S2-N8 ES→Proposed各一次warmup：2worker/2ACK/6checkpoint；全批120wall/60CPU、每worker25wall、单512MiB/总2GiB RSS、10MiB输出。主动114wall/55CPU/480MiB单/1792MiB总/9.75MiB输出，清理截止起点+118。任一身份/隔离/资源/科学/清理失败即停，保留失败，无measurement/A-A/replay/自动重试。采样合作式限制不是内核硬group配额。

Linux运行单独记platform、CPU型号/架构、依赖/运行时/profile/manifest、计时范围与状态。Mac与Linuxwarmup时间不可混池或作为方法性能优势证据；新平台计算仍只属已曝光的开发正确性覆盖。

## 云端材料位置与当前缺口

- GitHub公开固定源码commit `a21866022ba9ec08a1a5edf4a321718d633a2ab1`；交接分支提供旧synthetic config/source manifest和脱敏进度/摘要/哈希，未上传BUILD005-r2完整包、S2新stream包/runtime/profile或raw evidence。不能从有hash推断已经传到云端。
- 原Mac冻结ZIP只在本机保留，含平台路径绑定，不可直接作为公开发布物。Linux派生包应保留科学输入/代码hash，脱离Mac运行时与private permit，经正常受授权传输/只读来源核验；如需上传完整包须明确位置和内容边界，当前没有新上传或可用下载URL。
- Library此前官方prepare_uploads能力缺失，没有确认的文件ID；不重试或假称成功。Drive没有已确认的BUILD005包/文件ID（本轮未搜索/上传），不能宣称可获取。
- 专用研究三cloud env待用户创建/配置；真实Linux隔离能力、现有依赖、procfs/组终止权限和新平台资格均未确认。原D07未执行，原预注册v2存在性未知；缺正式材料仍阻断正式实验，不阻断讨论独立开发候选。

最小下一步：创建专用环境并只读盘点现有依赖/隔离/监控能力 → 补可取得的受授权Linux派生材料、静态审核与新哈希 → 明确单次资格+2worker预算授权 → 全部新资格通过才计算。本文到前两步要求清单，不运行任何新实验。

## 旧公开实现与本轮包的差异

云端对旧main的只读盘点报告：Python>=3.11、cpu_only前置配置；torch/vllm仅未来注释；旧mme_runner使用psutil而依赖清单未声明；AccessDenied统计可跳过；旧phase0资格sealed_linux_runtime=false；旧打包器含python.exe/Windows DLL。上述结论仅属旧源码，不能移植为BUILD005-r2资格。当前S2 stream入口是tools/worker.py而非旧mme_runner，冻结static校验明确列出已有psutil7.2.2，runtime-binding实际绑定Mac Python及已安装依赖5847项，仍不是Linux封装。当前worker/两方法路径没有GPU运行调用，但云端依赖存在性必须实查。

本轮guardian运行期child-tree查询未吞掉AccessDenied为成功，但group_members逐进程PermissionError/AccessDenied会跳过；因此新Linux适配必须核验受监控owned域的完整可见性，无法读取owned进程/组成员时明确失败且保留回执，不能凭部分列表宣布清理通过。无关宿主进程不能纳入权限扩张理由。Windows旧打包逻辑不作为Linux打包入口；新Linux运行时指纹必须实际本平台产生。

最小受授权传输清单：两方法所需original/observed vendor及其固定source blob身份、tools/worker与observer/contracts/oracle/预算/外部trace及待审核Linux launcher/helper、protocol/schedule/schema/probe-plan、新S2-N8 public/sidecar/reference和静态断言、新Linux runtime依赖版本与代码指纹、全文件manifest与ZIP hash、独立静态review。已有S2 public SHA `54458906c9522138661db8a03ba227b09ec78cb5bb4c1ab24e7c94fa647d7028`、sidecar `8b3e69cfaed1490f1f009d7c3925be174288317c33efccf95d1cb6903ba4a145`、reference `d7942a91248723b8c12128738c82d850cbb7aa02c7c13719071d5c633eea03df`，应保留这些科学bytes；完整新Linux包SHA尚不存在，不可预填。worker只接public pipe，sidecar/reference仅外部gate。

GitHub未包含原.omx、datasets/archive，clone不是原完整冻结包；不整体上传.omx、工具状态、用户目录、Mac runtime、旧审批permit、secret、原始媒体或大日志。缺原预注册仍标UNKNOWN，缺D07执行明确NOT_EXECUTED。
