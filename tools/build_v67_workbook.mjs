import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "file:///C:/Users/might/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workspace = process.argv[2];
if (!workspace) throw new Error("Usage: node build_v67_workbook.mjs <workspace>");

const outputPath = path.join(workspace, "实验资源与样本量预算v6.7.xlsx");
const previewDir = path.join(workspace, "outputs", "v67-workbook-preview");
await fs.mkdir(previewDir, { recursive: true });

const wb = Workbook.create();
const sheetNames = [
  "README", "Inputs", "ArmFrame", "PowerSensitivity", "PilotPrecision",
  "ResourceSummary", "Schedule", "Personnel", "Blockers", "Sources",
];
for (const name of sheetNames) wb.worksheets.add(name);

const C = {
  navy: "#17365D", blue: "#1F4E78", lightBlue: "#D9EAF7", paleBlue: "#EAF3F8",
  green: "#E2F0D9", amber: "#FFF2CC", red: "#FCE4D6", gray: "#E7E6E6",
  dark: "#1F1F1F", white: "#FFFFFF", grid: "#B7C9D6",
};

function title(sheet, range, value) {
  const r = sheet.getRange(range);
  r.merge();
  r.values = [[value]];
  r.format = {
    fill: C.navy,
    font: { bold: true, color: C.white, size: 15 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
  };
  r.format.rowHeight = 28;
}

function header(sheet, range) {
  const r = sheet.getRange(range);
  r.format = {
    fill: C.blue,
    font: { bold: true, color: C.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: C.grid },
  };
}

function grid(sheet, range) {
  const r = sheet.getRange(range);
  r.format.borders = { preset: "all", style: "thin", color: C.grid };
  r.format.verticalAlignment = "center";
  r.format.wrapText = true;
}

function finish(sheet, widths, freezeRows = 2) {
  sheet.showGridLines = false;
  if (freezeRows) sheet.freezePanes.freezeRows(freezeRows);
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  const used = sheet.getUsedRange();
  if (used) used.format.autofitRows();
}

// README
{
  const s = wb.worksheets.getItem("README");
  title(s, "A1:F1", "实验资源与样本量预算 v6.7 — 设计修复候选版");
  s.getRange("A3:F11").values = [
    ["项目", "值", "可否编辑", "状态", "判定依据", "备注"],
    ["规范绑定", "v20.1 / S1 v20.1 / S2 v20.1 / experiment v6.7", "否", "必须一致", "NormativeReleaseManifest", "任何跨版本拼接均使 package validation 失败"],
    ["当前状态", "DESIGN-REPAIRED / CONFIRM-BLOCKED", "否", "阻断", "v6.7 G0–G5 gates", "不得把本表容量估计写成确认性样本量"],
    ["独立单位", "physical_seed_base_bundle", "否", "冻结", "一次完整真实动力学轨迹", "tick/window/method/noise view 均为嵌套对象"],
    ["样本量", "由 pilot + power-confirm 决定", "是", "未锁定", "完整 gate 的 simultaneous power 下限", "Inputs 中仅给出规划点与资源包络"],
    ["主分析", "A vs 冻结 G*；paired by physical bundle", "否", "待密封", "v6.7 claim tree", "外部验证不并入主 n"],
    ["时间", "24 周执行 + 4 周缓冲", "否", "资源承诺", "Schedule", "缓冲不得用于事后改主张"],
    ["资源原则", "truth 只生成一次；各方法共享 truth hash", "否", "强制", "AllocationManifest/TestManifest", "方法臂不得各自重采样真值"],
    ["更新规则", "只改 Inputs 黄色单元；改后重新密封", "否", "强制", "版本/hash 审计", "所有输出必须由同一输入快照重算"],
  ];
  header(s, "A3:F3"); grid(s, "A3:F11");
  s.getRange("D5:D5").format.fill = C.red;
  s.getRange("B7:B7").format.fill = C.amber;
  s.getRange("A13:F15").values = [
    ["关键解释", null, null, null, null, null],
    ["功效公式", "配对二分类近似：n = (zα + zβ)^2 × q / Δ^2，再乘设计效应并补偿无效 bundle；最终仍以预签 Monte Carlo 为准。", null, null, null, null],
    ["零事件", "pilot 中零失败不能证明风险为零；PilotPrecision 给出零事件 95% 上界。", null, null, null, null],
  ];
  s.getRange("A13:F13").merge(); s.getRange("A13").format = { fill: C.lightBlue, font: { bold: true, color: C.dark } };
  s.getRange("B14:F14").merge(); s.getRange("B15:F15").merge(); grid(s, "A13:F15");
  finish(s, { A: 20, B: 34, C: 12, D: 14, E: 28, F: 34 });
}

// Inputs
{
  const s = wb.worksheets.getItem("Inputs");
  title(s, "A1:E1", "Inputs — 预签假设、规划点与容量边界");
  s.getRange("A3:E25").values = [
    ["ID", "数值", "单位", "类型", "定义/使用"],
    ["alpha_one_sided", 0.025, "概率", "统计", "共同主终点各自采用 IUT；这里不因 IUT 机械 Bonferroni"],
    ["target_power", 0.9, "概率", "统计", "完整 gate 的目标功效；最终看 simultaneous MC 下限"],
    ["SESOI_delta", 0.02, "绝对风险差", "统计", "规划点；pilot 后在不看 test 的情况下冻结"],
    ["discordant_q", 0.25, "概率", "统计", "配对二分类不一致概率 p10+p01 的规划点"],
    ["design_effect", 1.15, "倍数", "统计", "层/轨迹异质性与模型保守包络"],
    ["invalid_bundle_rate", 0.05, "概率", "统计", "资格失败/共同无效的规划上界"],
    ["candidate_strata", 24, "层", "设计", "2 CSTR 拓扑 × 4 路径族 × 3 严重度；资格后可删不可换"],
    ["min_per_stratum", 100, "bundle", "设计", "尾部与层级可解释性的资源下限，不等于功效结论"],
    ["ssr_envelope", 1.15, "倍数", "统计", "仅盲态 nuisance SSR，可上调不可下调"],
    ["mc_replicates", 250000, "replicate/grid", "功效", "power-confirm 重复数；需报告 simultaneous Wilson 下限"],
    ["mc_grid_points", 12, "点", "功效", "预签 nuisance grid"],
    ["mean_cpu_seconds_per_run", 8, "秒", "资源", "方法在共享 truth 上一次完整运行的保守均值"],
    ["cpu_overhead_factor", 1.3, "倍数", "资源", "容器、I/O、失败重跑与审计开销"],
    ["truth_mb_per_bundle", 80, "MB", "存储", "原始轨迹、truth 与证书；方法不可见字段物理隔离"],
    ["output_kb_per_method_run", 120, "KB", "存储", "belief、action、metric intermediate"],
    ["audit_kb_per_method_run", 240, "KB", "存储", "事件日志、ledger、hash 与审计证据"],
    ["storage_replication_factor", 2.5, "倍数", "存储", "工作副本 + 冷备 + 索引/压缩不确定性"],
    ["available_storage_tb", 4, "TB", "容量", "可用实验存储；需保留至少 25% 余量"],
    ["available_cpu_hours", 6000, "CPU-h", "容量", "两台工作站可交付总预算"],
    ["available_gpu_hours", 240, "GPU-h", "容量", "仅资格/外部验证；主治理不依赖 GPU"],
    ["execution_weeks", 24, "周", "计划", "G0–G9 正式执行"],
    ["buffer_weeks", 4, "周", "计划", "只吸收工程风险，不改变预注册主张"],
  ];
  header(s, "A3:E3"); grid(s, "A3:E26");
  s.getRange("B4:B26").format.fill = C.amber;
  s.getRange("B4:B11").format.numberFormat = "0.000";
  s.getRange("B12:B26").format.numberFormat = "0.00";
  s.getRange("A28:E30").values = [
    ["派生量", "公式/值", "单位", "用途", "状态"],
    ["planning_n_raw", null, "bundle", "解析近似，仅用于容量规划", "非确认性"],
    ["planning_n_rounded", null, "bundle", "同时满足层最小数并取 24 的倍数", "非确认性"],
  ];
  s.getRange("B29").formulas = [["=((NORM.S.INV(1-B4)+NORM.S.INV(B5))^2*B7/(B6^2))*B8/(1-B9)*B12"]];
  s.getRange("B30").formulas = [["=MAX(ROUNDUP(B29/B10,0)*B10,B10*B11)"]];
  header(s, "A28:E28"); grid(s, "A28:E30");
  s.getRange("B29:B30").format.fill = C.paleBlue; s.getRange("B29:B30").format.numberFormat = "0";
  finish(s, { A: 31, B: 18, C: 17, D: 16, E: 48 });
}

// ArmFrame
{
  const s = wb.worksheets.getItem("ArmFrame");
  title(s, "A1:I1", "Arm × Frame — 共享真值上的冻结运行矩阵");
  s.getRange("A2:I2").values = [["", "", "H", "G", "B", "N", "E", "", ""]];
  s.getRange("A3:I3").values = [["Arm", "角色/公平合同", 4800, 2400, 1200, 1200, 500, "方法运行数", "确认性/支持性"]];
  const rows = [
    ["A", "v20.1 完整治理；冻结下游算子", 1,1,1,1,1,null,"主"],
    ["G*", "D_select 选定的唯一强主基线", 1,1,1,1,1,null,"主"],
    ["C", "独立容器/团队实现等价性", 1,1,1,1,1,null,"主"],
    ["A^-Topo", "去 hazard-barrier topology；同 demand clock", 1,1,0,1,1,null,"机制"],
    ["A^-Ledger", "保留 lineage 表示，去原子生命周期账本", 1,1,1,1,1,null,"机制"],
    ["A^-Scope", "去 sealed ScopeClosure", 1,1,1,1,1,null,"机制"],
    ["M1", "无 provenance 的原始组合", 1,1,0,1,1,null,"消融"],
    ["M2", "lineage-only 去重", 1,1,0,1,1,null,"消融"],
    ["M3", "lineage + lifecycle；无多轴预算", 1,1,1,1,1,null,"消融"],
    ["M4", "M3 + 多轴预算", 1,1,1,1,1,null,"消融"],
    ["PRIMEX-PEV", "provenance lineage/value 基线；等输入预算", 1,1,0,1,1,null,"强基线"],
    ["Cautious/Idempotent", "Shenoy/cautious 家族；相同 BPA 与 clock", 1,1,0,1,1,null,"强基线"],
    ["CI/Unknown-corr", "无共同 root 的统计相关边界基线", 1,1,0,1,1,null,"边界"],
    ["Dempster raw", "未经谱系治理的 normalized conjunctive", 1,1,0,1,1,null,"压力"],
    ["Yager/PCR", "高冲突数值规则；不解决来源重复", 1,1,0,1,1,null,"压力"],
  ];
  s.getRange("A4:I18").values = rows;
  for (let r = 4; r <= 18; r++) s.getRange(`H${r}`).formulas = [[`=SUMPRODUCT(C${r}:G${r},C$3:G$3)`]];
  s.getRange("A20:I21").values = [
    ["合计唯一 physical bundles", null, null, null, null, null, null, null, null],
    ["合计方法运行", null, null, null, null, null, null, null, null],
  ];
  s.getRange("H20").formulas = [["=SUM(C3:G3)"]];
  s.getRange("H21").formulas = [["=SUM(H4:H18)"]];
  header(s, "A3:I3"); grid(s, "A2:I21");
  s.getRange("C3:G3").format.fill = C.amber;
  s.getRange("H4:H21").format.fill = C.paleBlue;
  s.getRange("C4:G18").format.numberFormat = "0";
  finish(s, { A: 22, B: 42, C: 9, D: 9, E: 9, F: 9, G: 9, H: 16, I: 16 }, 3);
}

// PowerSensitivity
{
  const s = wb.worksheets.getItem("PowerSensitivity");
  title(s, "A1:H1", "PowerSensitivity — 配对二分类容量规划（最终以 Monte Carlo gate 为准）");
  s.getRange("A3:H3").values = [["Scenario", "Δ=SESOI", "q=p10+p01", "alpha", "power", "解析 n", "含 SSR/无效率", "24 层平均"]];
  const deltas = [0.015,0.02,0.025,0.03];
  const qs = [0.15,0.25,0.35];
  let row = 4;
  for (const d of deltas) {
    for (const q of qs) {
      s.getRange(`A${row}:E${row}`).values = [[`D${String(d).slice(2)}-Q${String(q).slice(2)}`,d,q,null,null]];
      s.getRange(`D${row}:E${row}`).formulas = [["=Inputs!B4","=Inputs!B5"]];
      s.getRange(`F${row}`).formulas = [[`=((NORM.S.INV(1-D${row})+NORM.S.INV(E${row}))^2*C${row}/(B${row}^2))*Inputs!B8/(1-Inputs!B9)`]];
      s.getRange(`G${row}`).formulas = [[`=ROUNDUP(F${row}*Inputs!B12/Inputs!B10,0)*Inputs!B10`]];
      s.getRange(`H${row}`).formulas = [[`=G${row}/Inputs!B10`]];
      row++;
    }
  }
  s.getRange("A17:H20").values = [
    ["Power-confirm 规则", "完整 gate", "12 个预签 nuisance 点", "MC reps/grid", null, "通过阈值", null, "备注"],
    ["功效", "所有共同主终点 + no-harm", "simultaneous 95% Wilson lower", null, null, ">=0.90", null, "observed power 0.900 本身不够"],
    ["I 类错误", "全局零效应/边界零假设", "simultaneous 95% Wilson upper", null, null, "<=预签 alpha", null, "包含完整选择与 gatekeeping"],
    ["重估", "只用 blinded nuisance", "只上调不下调", null, null, "<= SSR envelope", null, "不得查看方法标签或效应方向"],
  ];
  s.getRange("D18:D19").formulas = [["=Inputs!B13"],["=Inputs!B13"]];
  header(s, "A3:H3"); header(s, "A17:H17"); grid(s, `A3:H${row-1}`); grid(s, "A17:H20");
  s.getRange(`B4:C${row-1}`).format.numberFormat = "0.000";
  s.getRange(`D4:E${row-1}`).format.numberFormat = "0.000";
  s.getRange(`F4:H${row-1}`).format.numberFormat = "0";
  s.getRange(`G4:G${row-1}`).format.fill = C.paleBlue;
  finish(s, { A: 16, B: 14, C: 16, D: 12, E: 12, F: 16, G: 18, H: 30 });
}

// PilotPrecision
{
  const s = wb.worksheets.getItem("PilotPrecision");
  title(s, "A1:G1", "PilotPrecision — 零事件上界与资格精度");
  s.getRange("A3:G3").values = [["合格独立 bundle n", "零事件 95% 上界", "零事件 99% 上界", "若观察 1 次的粗风险", "用途", "能否证明安全", "行动"]];
  const ns = [20,40,60,100,150,300,500,1000];
  for (let i=0;i<ns.length;i++) {
    const r=4+i;
    s.getRange(`A${r}`).values=[[ns[i]]];
    s.getRange(`B${r}`).formulas=[[`=1-0.05^(1/A${r})`]];
    s.getRange(`C${r}`).formulas=[[`=1-0.01^(1/A${r})`]];
    s.getRange(`D${r}`).formulas=[[`=1/A${r}`]];
    s.getRange(`E${r}:G${r}`).values=[["尾部/失败率资格","否","上界高于 margin 时增加 pilot 或保留阻断"]];
  }
  s.getRange("A14:G18").values = [
    ["Pilot 必须估计", "统计对象", "通过条件", "失败动作", "是否可看方法标签", "是否进入主 n", "备注"],
    ["共同无效率", "physical bundle", "UCB <= 预签阈值", "修 generator/场景", "否", "否", "不能按方法各删样本"],
    ["配对不一致 q", "A vs 候选 G*", "区间足以支持 power grid", "扩大 pilot/扩 grid", "仅 D_select 冻结流程", "否", "不得据效应方向挑基线"],
    ["ICC/尾厚", "trajectory/stratum", "设计效应包络覆盖", "增大 DE/改 estimand", "否", "否", "层间异质性进入 MC"],
    ["mapper coverage", "root-level joint mapper", "校准与适用域同时通过", "ABSTAIN_MAPPING/重训", "否", "否", "共享-u 仅敏感性模型"],
  ];
  header(s, "A3:G3"); header(s, "A14:G14"); grid(s, "A3:G11"); grid(s, "A14:G18");
  s.getRange("B4:D11").format.numberFormat = "0.0%";
  finish(s, { A: 22, B: 20, C: 20, D: 20, E: 27, F: 18, G: 38 });
}

// ResourceSummary
{
  const s = wb.worksheets.getItem("ResourceSummary");
  title(s, "A1:F1", "ResourceSummary — 勾稽后的 CPU/GPU/存储/人力包络");
  s.getRange("A3:F17").values = [
    ["资源项", "规划值", "单位", "容量", "利用率/余量", "公式解释"],
    ["唯一 truth bundles", null, "bundle", null, null, "ArmFrame H/G/B/N/E 只计一次"],
    ["方法运行数", null, "run", null, null, "arm×frame 矩阵求和"],
    ["主方法 CPU", null, "CPU-h", null, null, "runs×秒/3600×overhead"],
    ["阶段总 CPU", null, "CPU-h", null, null, "Schedule CPU 合计；含 generator/pilot/external"],
    ["阶段总 GPU", null, "GPU-h", null, null, "主治理不以 GPU 为必要条件"],
    ["truth 存储", null, "GB", null, null, "unique×MB/1024"],
    ["方法输出", null, "GB", null, null, "runs×KB/1024^2"],
    ["审计日志", null, "GB", null, null, "runs×KB/1024^2"],
    ["含复制总存储", null, "TB", null, null, "(truth+output+audit)×replication/1024"],
    ["高包络存储", null, "TB", null, null, "规划值×1.5；须保留 25% 余量"],
    ["总人日", null, "person-day", null, null, "Schedule 与 Personnel 必须相等"],
    ["正式执行", null, "week", null, null, "G0–G9"],
    ["工程缓冲", null, "week", null, null, "不可用于事后改主张"],
    ["\u7b97\u672f\u52fe\u7a3d", null, "PASS/FAIL", null, null, "\u4eba\u65e5\u3001CPU/GPU\u3001\u5b58\u50a8\u4e0e\u5468\u6570\u662f\u5426\u8de8\u8868\u4e00\u81f4"],
  ];
  const formulas = {
    B4:"=ArmFrame!H20", B5:"=ArmFrame!H21",
    B6:"=B5*Inputs!B15/3600*Inputs!B16", B7:"=SUM(Schedule!F4:F13)",
    B8:"=SUM(Schedule!G4:G13)", B9:"=B4*Inputs!B17/1024",
    B10:"=B5*Inputs!B18/1024/1024", B11:"=B5*Inputs!B19/1024/1024",
    B12:"=(B9+B10+B11)*Inputs!B20/1024", B13:"=B12*1.5",
    B14:"=SUM(Schedule!E4:E13)", B15:"=Inputs!B24", B16:"=Inputs!B25",
    B17:'=IF(AND(B14=Personnel!E14,B7=Schedule!F15,B8=Schedule!G15,MAX(Schedule!C4:C13)=Inputs!B24,Schedule!B16=Inputs!B24+1,Schedule!C16=Inputs!B24+Inputs!B25),"PASS","FAIL")',
  };
  for (const [cell, f] of Object.entries(formulas)) s.getRange(cell).formulas=[[f]];
  s.getRange("A18:F18").values = [["\u8d44\u6e90\u5bb9\u91cf\u95e8", null, "PASS/FAIL", null, null, "CPU/GPU \u4e0e\u9ad8\u5305\u7edc\u5b58\u50a8\u5747\u987b\u7559\u8db3\u8d44\u6e90"]];
  s.getRange("B18").formulas = [['=IF(AND(B7<=Inputs!B22,B8<=Inputs!B23,B13<=Inputs!B21*0.75),"PASS","FAIL")']];
  s.getRange("D4:D16").formulas = [
    [""],[""],["=Inputs!B22"],["=Inputs!B22"],["=Inputs!B23"],[""],[""],[""],["=Inputs!B21"],["=Inputs!B21*0.75"],[""],["=Inputs!B24"],["=Inputs!B25"]
  ];
  s.getRange("E6:E8").formulas = [["=B6/D6"],["=B7/D7"],["=B8/D8"]];
  s.getRange("E12:E13").formulas = [["=1-B12/D12"],["=1-B13/D13"]];
  s.getRange("E15:E16").formulas = [["=B15/D15"],["=B16/D16"]];
  header(s, "A3:F3"); grid(s, "A3:F18");
  s.getRange("B4:B18").format.fill = C.paleBlue;
  s.getRange("E6:E16").format.numberFormat = "0.0%";
  s.getRange("B17").format.fill = C.green;
  s.getRange("B18").format.fill = C.red;
  finish(s, { A: 26, B: 18, C: 14, D: 18, E: 18, F: 48 });
}

// Schedule
{
  const s = wb.worksheets.getItem("Schedule");
  title(s, "A1:I1", "Schedule — 24 周执行 + 4 周工程缓冲");
  s.getRange("A3:I3").values = [["Gate", "开始周", "结束周", "退出条件", "人日", "CPU-h", "GPU-h", "确认性 test 可见?", "停止/回退"]];
  const rows = [
    ["G0 合同/P0",1,2,"版本、claim、action/reason、manifest 一致",28,20,0,"否","不一致则停在设计"],
    ["G1 生成器/隔离",1,4,"physical seed 改真值；label/truth 物理隔离",46,300,8,"否","泄漏或伪独立则重构"],
    ["G2 参考实现/资格",2,6,"P0-C/P0-V + 双实现等价",52,180,24,"否","任一不变量失败则阻断"],
    ["G3 场景/arm 冻结",4,7,"24 层资格；D_select、G*、arm×frame 密封",38,60,0,"否","不可达层升版删除"],
    ["G4 独立 pilot",7,10,"coverage、ICC、q、共同无效率、尾部合格",42,420,32,"否","扩大 pilot 或改设计"],
    ["G5 power-confirm/密封",11,12,"simultaneous power/type-I + Allocation/TestManifest",24,120,0,"否","增加 n/扩 grid/降主张"],
    ["G6 确认性生成",13,16,"单次密封 test；共享 truth hash；零选择性重跑",25,null,48,"是","系统失败按预签规则"],
    ["G7 锁定分析",17,18,"paired estimand、no-harm、敏感性与审计表",22,140,0,"是","失败主张降级"],
    ["G8 外部支持",17,20,"独立模拟器/TEP/unseen/shadow-HIL",18,360,16,"仅外部","不补救主结果"],
    ["G9 投稿包",21,24,"主文/S1/S2/代码/数据卡/cover letter 一致",19,40,0,"是","未闭门不投稿"],
  ];
  s.getRange("A4:I13").values=rows;
  s.getRange("F10").formulas=[["=ResourceSummary!B6"]];
  s.getRange("A15:I16").values = [
    ["正式执行合计", null, null, null, null, null, null, null, ""],
    ["缓冲",25,28,"仅吸收工程/排队风险",0,0,0,"否","不得解封新主张或替换基线"],
  ];
  s.getRange("C15").formulas=[["=MAX(C4:C13)"]];
  s.getRange("E15").formulas=[["=SUM(E4:E13)"]];
  s.getRange("F15").formulas=[["=SUM(F4:F13)"]];
  s.getRange("G15").formulas=[["=SUM(G4:G13)"]];
  header(s, "A3:I3"); grid(s, "A3:I16");
  s.getRange("E15:G15").format.fill=C.paleBlue;
  finish(s, { A: 24, B: 10, C: 10, D: 48, E: 12, F: 12, G: 12, H: 18, I: 38 });
}

// Personnel
{
  const s = wb.worksheets.getItem("Personnel");
  title(s, "A1:G1", "Personnel — 角色、独立性与人日承诺");
  s.getRange("A3:G3").values = [["角色", "人数", "人日/人", "计划人日", "合计人日", "独立性/职责", "不可兼任约束"]];
  const rows = [
    ["PI/主笔",1,28,null,null,"主张、版本与投稿包","不得单独裁决安全 oracle"],
    ["融合方法科学家",1,56,null,null,"治理/融合/证明","不得担任独立实现 C 的唯一作者"],
    ["过程安全专家",1,42,null,null,"场景、barrier、ActionTruth","不得看 test 后改 oracle"],
    ["统计学负责人",1,32,null,null,"estimand/power/gate/分析锁定","不得兼任 D_select 结果裁决"],
    ["ML/数据工程",1,44,null,null,"mapper、数据隔离、外部数据","不得把标签写入 method payload"],
    ["软件/基础设施",1,56,null,null,"reference impl、容器、重放/故障注入","不得自行豁免失败运行"],
    ["独立安全复核 A",1,10,null,null,"场景/禁用动作签署","与 B 独立"],
    ["独立安全复核 B",1,10,null,null,"场景/禁用动作签署","与 A 独立"],
    ["研究助理",1,36,null,null,"执行、审计、数据卡","无权解封 test"],
  ];
  s.getRange("A4:G12").values=rows;
  for(let r=4;r<=12;r++){
    s.getRange(`D${r}`).formulas=[[`=B${r}*C${r}`]];
    s.getRange(`E${r}`).formulas=[[`=D${r}`]];
  }
  s.getRange("A14:G14").values=[["合计",null,null,null,null,"Schedule 必须精确相等",""]];
  s.getRange("E14").formulas=[["=SUM(E4:E12)"]];
  header(s, "A3:G3"); grid(s, "A3:G15");
  s.getRange("D4:E14").format.fill=C.paleBlue;
  finish(s, { A: 24, B: 10, C: 12, D: 14, E: 14, F: 38, G: 38 });
}

// Blockers
{
  const s = wb.worksheets.getItem("Blockers");
  title(s, "A1:G1", "Blockers — 确认性数据解封前必须全部关闭");
  s.getRange("A3:G3").values = [["ID", "阻断项", "当前状态", "完成证据", "Owner", "最晚 Gate", "未关闭动作"]];
  const rows = [
    ["B01","v20.1 reference implementation 与 P0 性质测试","OPEN","CI 报告 + container digest","软件/融合","G2","禁止确认性生成"],
    ["B02","physical seed 改变真实动力学而非仅观测噪声","OPEN","generator property tests + truth hashes","数据/过程","G1","重构 generator"],
    ["B03","TEP/CWRU/MVTec label/filename 泄漏物理隔离","OPEN","payload schema audit + negative tests","数据","G1","移除/重导入"],
    ["B04","24 层可达性与 ActionTruth 双人签署","OPEN","ScenarioQualificationManifest","安全复核","G3","删除不可达层并升版"],
    ["B05","G*、SESOI、no-harm、权重、arm×frame 冻结","OPEN","DesignFreezeManifest","统计/PI","G3","禁止 pilot 后择优"],
    ["B06","root-level mapper 联合校准与 coupling family","OPEN","CalibrationCertificate + envelope","ML/融合","G4","ABSTAIN_MAPPING"],
    ["B07","pilot precision/ICC/q/共同无效率合格","OPEN","PilotQualificationReport","统计","G4","扩大 pilot/改设计"],
    ["B08","完整 gate simultaneous power/type-I 合格","OPEN","PowerConfirmReport","统计","G5","增样本或降主张"],
    ["B09","Allocation/TestManifest、分析代码、容器全部密封","OPEN","签名 hash manifest","PI/软件","G5","禁止解封 test"],
    ["B10","独立实现 C 等价与差异裁决流程","OPEN","EquivalenceIUT + adjudication log","独立实现","G2","不得声明表示一致"],
    ["B11","Information Fusion cover letter 六问与 50 refs 上限","OPEN","submission audit","PI","G9","不投稿"],
    ["B12","4 TB \u540d\u4e49\u5b58\u50a8\u5728 25% \u4f59\u91cf\u4e0b\u4e0d\u8db3\u4ee5\u8986\u76d6 v6.7 \u9ad8\u5305\u7edc","OPEN","\u65b0\u589e\u53ef\u7528\u5bb9\u91cf\u6216\u5bc6\u5c01\u538b\u7f29/\u590d\u5236\u65b9\u6848","\u8f6f\u4ef6/PI","G5","\u8d44\u6e90\u95e8 FAIL\uff1b\u7981\u6b62\u89e3\u5c01 test"],
  ];
  s.getRange("A4:G15").values=rows;
  header(s, "A3:G3"); grid(s, "A3:G15");
  s.getRange("C4:C15").format.fill=C.red;
  s.getRange("C4:C15").dataValidation = { rule: { type: "list", values: ["OPEN","CLOSED","WAIVED-NOT-ALLOWED"] } };
  finish(s, { A: 10, B: 42, C: 18, D: 40, E: 18, F: 14, G: 34 });
}

// Sources
{
  const s = wb.worksheets.getItem("Sources");
  title(s, "A1:F1", "Sources — 方法与投稿依据（检索截至 2026-07-14）");
  s.getRange("A3:F3").values = [["类别", "来源", "年份", "标识/链接", "本表用途", "边界"]];
  const rows = [
    ["期刊","Information Fusion — Guide for Authors",2026,"https://www.sciencedirect.com/journal/information-fusion/publish/guide-for-authors","页数/摘要/关键词/50 refs/cover letter","投稿规则可能更新，提交前复核"],
    ["依赖证据","Shenoy, On distinct belief functions",2023,"https://proceedings.mlr.press/v215/shenoy23a.html","幂等/依赖证据强基线","不等同于 provenance lifecycle"],
    ["依赖建模","Su et al., Handling dependence in DST",2017,"https://doi.org/10.1002/int.21695","依赖类型与相关性边界","谱系重复不是全部统计相关"],
    ["溯源","Kowalski & Martin, Provenance across evidence combination",2018,"https://doi.org/10.23919/ICIF.2018.8455764","组合全过程 provenance 对照","需避免声称首次引入 provenance"],
    ["溯源融合","Chang et al., PRIMEX-PEV",2025,"https://isif.org/media/encoding-information-lineage-scalable-distributed-fusion","lineage/value 可扩展基线","同根一次的创新冲突必须正面处理"],
    ["稳健证据","Denoeux, cautious rule",2008,"https://doi.org/10.1016/j.artint.2007.05.008","谨慎/幂等强基线","主要处理可分 belief functions"],
    ["依赖信息","Chebbah et al.",2015,"https://doi.org/10.1016/j.dss.2015.02.017","来源依赖信息的 DST 处理","与审计/生命周期目标不同"],
    ["依赖 ER","Zhang et al.",2023,"https://doi.org/10.1016/j.cja.2023.03.037","依赖 evidential reasoning 比较","应用与假设需公平对齐"],
    ["未知相关","Ajgl & Straka, covariance intersection",2022,"https://doi.org/10.1016/j.automatica.2022.110168","无共同 root 统计相关边界基线","本方法不解决未知 cross-root correlation"],
    ["本地规范","实验设计与执行计划 v6.7",2026,"workspace sibling","样本单位、gate、停止条件","未完成实验"],
  ];
  s.getRange("A4:F13").values=rows;
  header(s, "A3:F3"); grid(s, "A3:F13");
  finish(s, { A: 16, B: 40, C: 10, D: 58, E: 36, F: 38 });
}

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);

const overview = await wb.inspect({ kind: "workbook,sheet,formula", maxChars: 20000, options: { maxResults: 500 } });
const sheets = [];
for (const s of wb.worksheets.items) {
  const used = s.getUsedRange();
  const address = used?.address ?? null;
  const region = address ? await wb.inspect({
    kind: "region,formula", sheetId: s.name, range: address, maxChars: 18000,
    tableMaxRows: 80, tableMaxCols: 12, tableMaxCellChars: 160, options: { maxResults: 400 },
  }) : null;
  const preview = await wb.render({ sheetName: s.name, autoCrop: "all", scale: 1, format: "png" });
  const previewPath = path.join(previewDir, `${s.name}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  sheets.push({ name: s.name, usedRange: address, region: region?.ndjson ?? String(region ?? ""), previewPath });
}
const inspection = {
  outputPath, previewDir,
  overview: overview?.ndjson ?? String(overview),
  sheets,
};
await fs.writeFile(path.join(previewDir, "inspection.json"), JSON.stringify(inspection, null, 2), "utf8");

const errorTokens = ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A"];
const corpus = JSON.stringify(inspection);
const errors = Object.fromEntries(errorTokens.map(t => [t, (corpus.match(new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length]));
console.log(JSON.stringify({ outputPath, previewDir, sheetCount: sheets.length, sheets: sheets.map(x=>({name:x.name, usedRange:x.usedRange, previewPath:x.previewPath})), errors }, null, 2));
process.exitCode = 0;
