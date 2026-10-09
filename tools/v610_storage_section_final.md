## 8 100GB 分阶段存储与当前服务器资源门

### 8.1 100GB 是活动工作集，不是总归档量

每个 `storage_stage` 的本地硬上限固定为十进制 `100,000,000,000 bytes`。预算不可互借：

| 子配额 | 上限 | 内容 |
| --- | ---: | --- |
| committed evidence | 80GB | truth、公共输出、ledger/checkpoint、失败attempt、详细审计 |
| scratch/partial/retry | 10GB | 与stage同配额，封段前清理 |
| recovery/quarantine | 5GB | 恢复、隔离与原子提交空间 |
| manifests/checksums/reserve | 5GB | 文件清单、SHA/Merkle、索引及紧急余量 |
| **合计** | **100GB** | 任一子配额或总量越界即SAFE_HALT |

100GB只限制服务器峰值本地占用。完整数据仍需流式归档到另一卷/另一主机；若归档副本与源数据位于同一卷，其峰值也计入100GB。分阶段不会把项目总归档需求自动降为100GB。

### 8.2 三层单位必须分开

- `storage_stage`：100GB运维容器，不计n；
- `execution_batch`：MME 28 bundles、D_select/pilot/confirm 24 bundles，仍是cluster-bootstrap单位；
- `balance_superblock`：MME七方法168 bundles（6个MME batches）、D_select七方法168 bundles（7个D_select batches）、pilot/confirm五方法120 bundles（5个pilot/confirm batches），是首选完整设计闭环。

每个bundle的全部方法必须在同一stage完成。首选stage只装整数个完整superblock：

`k_stage=floor(80e9 / q99(superblock_bytes))`。

若168/120 bundles装不下，可退为一个或若干完整28/24-bundle execution batches，但MME连续6段、D_select连续7段、pilot/confirm连续5段必须组成一个不可中途分析的superblock。若连28/24-bundle batch也装不下100GB，G0-STAGED FAIL；只能减少可再生冗余、无损流式压缩或更换存储，不能拆bundle或方法面板。

现有MME分配已核验：每连续6 batches的168 bundles恰好24 strata各7、14条Williams序列各12；SCREEN每template 2、VERIFY每template 6。D_select固定为28个24-bundle batches，组成4个168-bundle superblocks（每个7 batches）。指定superblocks：SCREEN 4、VERIFY 10、D_select 4；pilot Wave1/2/3/heldout分别6/6/4/4个120-bundle superblocks。确认性superblock数为最终 `n/120`。

### 8.3 100GB stage 的不可跳转状态机

`PLANNED → RUNNING → SEALED_LOCAL → ARCHIVED_A → ARCHIVED_B → RESTORE_VERIFIED → PURGE_AUTHORIZED → PURGED → RECONCILED`。

每个新平衡量子前同时满足：

1. `U_stage + B_next,p99 <= 100,000,000,000`；
2. `U_committed + B_next,p99 <= 80,000,000,000`；
3. `F_now - B_next,p99 - B_unflushed >= 235,853,007,872`；
4. 共享卷存在独占100GB quota/reservation，或另加预签外部写入漂移guard。

每28/24-bundle execution batch写入 `.partial`，全部方法、计数与hash通过后原子rename为 committed。LOW_SPACE时停止新量子、flush WAL/ledger并进入PAUSED_SAFE，绝不边跑边删。

### 8.4 双归档、全量恢复与清理授权

归档地址当前为 `PENDING_ARCHIVE_URI_A/B`；未配置两份独立副本时第一stage也不得启动。至少一份副本必须off-volume/off-host并为immutable/WORM。归档目标写入前free须≥`ceil(1.05×U_sealed)`，不得预先计入压缩收益。

SEALED_LOCAL必须冻结：逐文件path/size/SHA-256、Merkle root、bundle/method expected-vs-observed、invalid原因、allocation/prereg/container/candidate/schema/seed-commitment hashes、资源遥测和聚合结果。

purge前对A/B两副本均执行全量流式读取/解压和逐文件SHA；missing、unexpected、mismatch必须全为0。随后按预签样本对24 strata各恢复1个bundle并运行全部方法重放。只有双归档、restore和DS+STAT双签全部通过才可 `PURGE_AUTHORIZED=true`。

本地永久保留：stage manifest、Merkle/archive URI+hash、聚合摘要、代码/容器/candidate hash、失败ledger、restore报告和purge tombstone。purge后重新盘点文件与free，只有RECONCILED且下一stage仍满足启动式才可继续。

### 8.5 当前服务器仍是 G0 FAIL

总卷容量943,412,031,488 bytes；25%保留线235,853,007,872；当前free=217,182,134,272 bytes，仅23.0209%，已低于保留线18,670,873,600 bytes。

- 同卷80GB committed目标要求启动free≥315,853,007,872，当前差98,670,873,600 bytes；
- 同卷100GB硬上限要求启动free≥335,853,007,872，当前差118,670,873,600 bytes，即118.671GB/约110.521GiB；
- 若使用独立stage卷，建议有效容量≥150GB并建立100GB项目quota；还必须配置双归档端；
- 旧规划点仅用于容量演算：SCREEN约55.45344GB；VERIFY可暂按840+840两stage、各约69.3168GB；D_select约55.45344GB；pilot四段约58.896/58.896/39.264/39.264GB。confirm前原始量约445.86048GB，双归档各加5%封装余量至少约936.307008GB；最终必须由SHK-001实测P99替换。

因此当前状态保持 `G0_RESOURCE=FAIL / G0_STAGED=FAIL`。100GB轮转可降低未来峰值，但不能绕过现有空间、GPU共享、ACL隔离和归档端缺失。

### 8.6 统计约束与允许QC

storage_stage不是统计中期分析。主分析仍先在bundle内形成A−baseline配对差，并按execution batch整簇bootstrap。`storage_stage_id`、UTC、node/container/cache/GPU状态作为预签block/time信息；另做method×stage、time trend和leave-one-stage-out敏感性，不得据此删除stage。

阶段间仅允许看：bytes/文件数、checksum、manifest、seed唯一性、缺失/重复行、strata/template/Williams配额、container/candidate digest、ACL/oracle泄漏负测、资源/OOM/Xid、online-replay与双实现一致性。禁止看累计A−baseline方向、效应量、p/CI、winner/rank、IUT/no-harm通过率，或据此改n、margin、weights、templates、methods和noise grid。

容量/基础设施失败必须保留原attempt。未完成全方法的bundle不进入分析；仅可按冻结规则在新stage以同一seed重跑整个bundle，并保留失败attempt关联ID。双归档均不可恢复时整stage INVALID并按原allocation整段重跑，不得挑选bundle。
