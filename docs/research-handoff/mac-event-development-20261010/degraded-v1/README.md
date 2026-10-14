# 降级开发启动器（仅静态准备）

状态PREPARED_NON_AUTHOR_REVIEWED_NOT_RUN。用户已确认新协议；历史取消属于任务调用，未启动研究、不是失败实验。初查只有提案，无降级运行收据/许可消费标记，未重复任务。

不使用实验Seatbelt，不声称OS级文件/网络隔离、原隔离资格、MME或D07通过。旧profile、旧actor/监督器/CLI门禁及362冻结文件不改。新增独立launcher，算法/参考/测试模块原样按hash绑定；CPU子进程50秒硬限、父进程7软/8硬，合计名义58秒（仅这两进程），墙钟110秒主动终止，输出9MiB阈值，清理/写日志有保守余量但非外部120秒绝对deadline。未动态验证清理、限额和失败回执，硬杀父进程/机器中断可能无法留下最终收据。18测试只是13算法＋5资源谓词，不验证真实隔离/进程控制。

无网络/fork/越界读写探针，不加载bounded_actor或bounded_supervisor。一次Python子进程用于计算，父启动器监控退出、流输出并保存原始日志；不执行其他外部程序。父阶段预留一次固定全部240bundle，不重试；子先5＋13测试，失败即停，再120主槽，最后102参考。oracle在算法输出后才读，是代码顺序而非OS访问屏障。完整stdin/stdout阶段报告保留原始日志，主结果/评价在stdout.jsonl型日志中；失败也保留已完成阶段。运行前后检查固定输入/源码及旧362hash。绑定只覆盖列出文件和Python可执行文件，不覆盖整个标准库/runtime；不安装、不下载、不付费，不读取代理/凭证/env配置。

一次标记execution-used.json固定在本目录，换output-name也不允许第二次；新目录mkdir不覆盖。标记消费后任何失败不给重试。预启动错误留receipt；异常/超时杀子进程组、wait4回收CPU与实际退出码；输出日志和receipt.json。文件hash不是写保护，缺陷/代码变更在用户权限内可能读写其他文件或联网，不能把无网络代码说成无出网保证。

执行路径：CUA对Terminal明确拒绝仍生效。本轮不通过exec或其他终端代跑，不提权、不关闭平台沙箱；现有证据不足以认定exec可合法转接此次被拒操作，采取用户自行在已打开原生Terminal运行。仅交付命令，不执行。

用户手动命令（非作者复审收口后使用）：
```zsh
<LOCAL_RUNTIME_PATH> -I -B '<LOCAL_HOST_PATH>' --confirm-no-os-isolation --output-name manual-attempt-001
printf 'exit_code=%s\n' "$?"
```

binding.json SHA256：f736b4f9c30cb918a03e4cac7acb8380a77e0b176359f1ae05cd1bc6e8251c78。
运行后只需回报打印的receipt.json路径、退出码及receipt/error；无.env/密钥/完整终端历史。不要重复命令；失败停下。原根目录literal规则候选保持静态，不同时试另一动态路线。研究输出仅开发验证，不构成正式论文结论。
