#!/usr/bin/env python3
"""Build the editable v6.6 experiment resource and power-planning workbook."""

from __future__ import annotations

from itertools import product
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "实验资源与样本量预算v6.6.xlsx"

NAVY = "17365D"
BLUE = "4472C4"
LIGHT_BLUE = "D9EAF7"
LIGHT_GREEN = "E2F0D9"
YELLOW = "FFF2CC"
RED = "F4CCCC"
GRAY = "E7E6E6"
WHITE = "FFFFFF"
INPUT_BLUE = "0000FF"
BLACK = "000000"
GREEN = "008000"
thin = Side(style="thin", color="B7B7B7")


def title(ws, text: str, end_col: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    cell = ws.cell(1, 1, text)
    cell.font = Font(name="Arial", size=16, bold=True, color=WHITE)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28


def header(ws, row: int, headers: list[str]) -> None:
    for col, value in enumerate(headers, 1):
        c = ws.cell(row, col, value)
        c.font = Font(name="Arial", bold=True, color=WHITE)
        c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(top=thin, bottom=thin, left=thin, right=thin)


def style_table(ws, start_row: int, end_row: int, start_col: int, end_col: int) -> None:
    for row in ws.iter_rows(min_row=start_row, max_row=end_row, min_col=start_col, max_col=end_col):
        for c in row:
            c.font = c.font.copy(name="Arial", size=10, color=c.font.color or BLACK)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(top=thin, bottom=thin, left=thin, right=thin)


def input_cell(cell, source: str | None = None) -> None:
    cell.font = Font(name="Arial", size=10, color=INPUT_BLUE)
    cell.fill = PatternFill("solid", fgColor=YELLOW)
    if source:
        cell.comment = Comment(source, "Codex")


def formula_cell(cell) -> None:
    cell.font = Font(name="Arial", size=10, color=BLACK)


def autosize(ws, widths: dict[int, float]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A4"
    ws.sheet_view.showGridLines = False


def build_readme(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "说明"
    title(ws, "实验资源与样本量预算 v6.6", 4)
    rows = [
        ("状态", "PLANNING-ONLY；不是正式功效冻结或 TestManifest", "当前 v6.5 的 SESOI、no-harm 界和 pilot kernel 尚未签署。", "黄色单元格为可编辑输入。"),
        ("主结论", "T4 已足够承担神经基线；主确认实验由 CPU/RAM/NVMe 决定。", "本机仅用于开发与审计。", "服务器 CPU/RAM/磁盘必须用探针实测。"),
        ("推荐资源", "32 逻辑线程、128 GB RAM、2 TB 可用 NVMe、1×NVIDIA T4", "约 169 人日", "约 0–80 T4 GPU-h；约 0.87k CPU-h 中央估计。"),
        ("样本量", "confirm 暂定 n_H=2,400–7,200；n_G=600–1,800；n_B=600–1,800", "中央工作点 4,800/1,200/1,200", "正式 n 只允许在独立 pilot 与 MC confirm 后冻结。"),
        ("使用顺序", "先改“假设输入”与“设备判定”", "再查看“阶段资源”和“功效敏感性”", "最后在 G6 将工作点替换为独立功效模拟结果。"),
    ]
    header(ws, 3, ["项目", "结论/数值", "依据/限制", "动作"])
    for r, values in enumerate(rows, 4):
        for c, value in enumerate(values, 1):
            ws.cell(r, c, value)
    style_table(ws, 4, 8, 1, 4)
    ws[4][1].fill = PatternFill("solid", fgColor=RED)
    ws[5][1].fill = PatternFill("solid", fgColor=LIGHT_GREEN)
    autosize(ws, {1: 18, 2: 46, 3: 48, 4: 44})


def build_inputs(wb: Workbook) -> None:
    ws = wb.create_sheet("假设输入")
    title(ws, "可编辑资源与运行假设", 5)
    header(ws, 3, ["参数", "低档", "推荐", "高档", "含义/来源"])
    data = [
        ("hazard_confirm_bundles", 2400, 4800, 7200, "正式 n_H 的工作范围；非功效冻结"),
        ("benign_confirm_bundles", 600, 1200, 1800, "正式 n_G 的工作范围；非功效冻结"),
        ("budget_confirm_bundles", 600, 1200, 1800, "正式 n_B 的工作范围；非功效冻结"),
        ("hazard_methods", 4, 4, 5, "A、G*、A^-Topo、C；高档加入支持性方法"),
        ("benign_methods", 2, 2, 3, "A、G*；高档加入对照"),
        ("budget_methods", 2, 2, 3, "M3、M4；高档加入压力对照"),
        ("variants", 2, 3, 4, "冻结 variant panel"),
        ("algorithm_seeds", 2, 3, 5, "嵌套 seed，不增加统计 n"),
        ("pretest_method_runs", 160000, 237600, 400000, "train/select/smoke/pilot 的工程工作量"),
        ("external_method_runs", 20000, 43200, 100000, "IDAES/TEP/攻击外部支持"),
        ("qualification_runs", 10000, 20000, 50000, "property/fault/conformance tests"),
        ("cpu_seconds_per_method_run", 1, 5, 20, "必须由 G5 微基准替换"),
        ("power_sim_cpu_hours", 50, 150, 500, "R_search/R_confirm 与 nuisance grid"),
        ("retained_mb_per_method_run", 0.1, 0.5, 2.0, "压缩后的原始轨迹+日志；端点表另计"),
        ("storage_replication_factor", 2, 3, 3, "工作副本、只读归档与备份"),
        ("gpu_hours", 0, 80, 200, "仅 IFNet/AE/LSTM/evidential-DL 等学习基线"),
        ("server_logical_threads", 16, 32, 64, "服务器实测值应覆盖所选档位"),
        ("parallel_efficiency", 0.60, 0.70, 0.75, "容器/IO/尾任务损失"),
        ("person_days", 100, 169, 250, "实现+安全+统计+复现+外部验证"),
    ]
    for r, row in enumerate(data, 4):
        for c, value in enumerate(row, 1):
            ws.cell(r, c, value)
        for c in range(2, 5):
            input_cell(ws.cell(r, c), f"Source: v6.5 protocol and v6.6 planning assumptions, 2026-07-14; replace after pilot/benchmark for {row[0]}.")
    style_table(ws, 4, 3 + len(data), 1, 5)
    for col in range(2, 5):
        for row in range(4, 3 + len(data) + 1):
            ws.cell(row, col).number_format = "0.00"
    autosize(ws, {1: 34, 2: 14, 3: 14, 4: 14, 5: 56})


def input_ref(param: str, scenario_col: str) -> str:
    mapping = {
        "hazard_confirm_bundles": 4,
        "benign_confirm_bundles": 5,
        "budget_confirm_bundles": 6,
        "hazard_methods": 7,
        "benign_methods": 8,
        "budget_methods": 9,
        "variants": 10,
        "algorithm_seeds": 11,
        "pretest_method_runs": 12,
        "external_method_runs": 13,
        "qualification_runs": 14,
        "cpu_seconds_per_method_run": 15,
        "power_sim_cpu_hours": 16,
        "retained_mb_per_method_run": 17,
        "storage_replication_factor": 18,
        "gpu_hours": 19,
        "server_logical_threads": 20,
        "parallel_efficiency": 21,
        "person_days": 22,
    }
    return f"'假设输入'!{scenario_col}{mapping[param]}"


def build_resource_summary(wb: Workbook) -> None:
    ws = wb.create_sheet("总资源")
    title(ws, "低/推荐/高三档总资源估算", 5)
    header(ws, 3, ["指标", "低档", "推荐", "高档", "解释"])
    scenarios = {"B": "低", "C": "推荐", "D": "高"}
    metrics = [
        ("confirm_method_runs", "=hazard*hazard_methods*variants*seeds + benign*benign_methods*variants*seeds + budget*budget_methods*variants*seeds", "正式 test 的嵌套运行次数"),
        ("all_method_runs", "=confirm + pretest + external + qualification", "全部方法运行次数"),
        ("CPU_h_method_runs", "=all_runs*seconds_per_run/3600", "不含功效模拟"),
        ("CPU_h_total", "=CPU_h_method_runs+power_sim_cpu_hours", "资源排期使用"),
        ("ideal_wall_h", "=CPU_h_total/(threads*parallel_efficiency)", "仅计算排队后墙钟；不含阶段依赖"),
        ("retained_storage_GB", "=all_runs*MB_per_run/1024*replication_factor", "包含归档/备份倍率"),
        ("T4_GPU_h", "=gpu_hours", "主方法可为 0"),
        ("person_days", "=person_days", "人工是主要成本"),
    ]
    for idx, (name, _, note) in enumerate(metrics, 4):
        ws.cell(idx, 1, name)
        ws.cell(idx, 5, note)
    for col, scenario in scenarios.items():
        out_col = {"B": 2, "C": 3, "D": 4}[col]
        hazard = input_ref("hazard_confirm_bundles", col)
        benign = input_ref("benign_confirm_bundles", col)
        budget = input_ref("budget_confirm_bundles", col)
        hm = input_ref("hazard_methods", col)
        gm = input_ref("benign_methods", col)
        bm = input_ref("budget_methods", col)
        variants = input_ref("variants", col)
        seeds = input_ref("algorithm_seeds", col)
        ws.cell(4, out_col, f"={hazard}*{hm}*{variants}*{seeds}+{benign}*{gm}*{variants}*{seeds}+{budget}*{bm}*{variants}*{seeds}")
        ws.cell(5, out_col, f"={get_column_letter(out_col)}4+{input_ref('pretest_method_runs', col)}+{input_ref('external_method_runs', col)}+{input_ref('qualification_runs', col)}")
        ws.cell(6, out_col, f"={get_column_letter(out_col)}5*{input_ref('cpu_seconds_per_method_run', col)}/3600")
        ws.cell(7, out_col, f"={get_column_letter(out_col)}6+{input_ref('power_sim_cpu_hours', col)}")
        ws.cell(8, out_col, f"={get_column_letter(out_col)}7/({input_ref('server_logical_threads', col)}*{input_ref('parallel_efficiency', col)})")
        ws.cell(9, out_col, f"={get_column_letter(out_col)}5*{input_ref('retained_mb_per_method_run', col)}/1024*{input_ref('storage_replication_factor', col)}")
        ws.cell(10, out_col, f"={input_ref('gpu_hours', col)}")
        ws.cell(11, out_col, f"={input_ref('person_days', col)}")
        for row in range(4, 12):
            formula_cell(ws.cell(row, out_col))
            ws.cell(row, out_col).number_format = "#,##0.0"
    style_table(ws, 4, 11, 1, 5)
    ws[7][2].fill = ws[7][3].fill = ws[7][4].fill = PatternFill("solid", fgColor=LIGHT_GREEN)
    ws[9][2].fill = ws[9][3].fill = ws[9][4].fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    autosize(ws, {1: 30, 2: 16, 3: 16, 4: 16, 5: 48})


def build_power(wb: Workbook) -> None:
    ws = wb.create_sheet("功效敏感性")
    title(ws, "确认性样本量敏感性（仅用于资源上限，不是正式功效冻结）", 7)
    ws[3] = ["类型", "配对不一致率 q / 标准化效应 dz", "规划真值越过 margin 的间隔 g", "单侧 alpha", "目标 power", "近似 n", "解释"]
    header(ws, 3, [c.value for c in ws[3]])
    row = 4
    for q, gap in product([0.10, 0.20, 0.30], [0.02, 0.03, 0.04, 0.05]):
        ws.cell(row, 1, "paired_binary")
        ws.cell(row, 2, q)
        ws.cell(row, 3, gap)
        ws.cell(row, 4, 0.025)
        ws.cell(row, 5, 0.90)
        ws.cell(row, 6, f"=ROUNDUP(((NORM.S.INV(1-D{row})+NORM.S.INV(E{row}))^2*B{row})/(C{row}^2),0)")
        ws.cell(row, 7, "McNemar/配对风险差的保守正态近似；g 是规划真值超过 SESOI/no-harm margin 的额外距离，不是 SESOI 本身。")
        for col in [2, 3, 4, 5]:
            input_cell(ws.cell(row, col), "Planning sensitivity grid; replace with held-out pilot kernel and simulation-based power.")
            ws.cell(row, col).number_format = "0.0%"
        formula_cell(ws.cell(row, 6))
        row += 1
    for dz in [0.10, 0.15, 0.20, 0.25]:
        ws.cell(row, 1, "paired_delay")
        ws.cell(row, 2, dz)
        ws.cell(row, 3, "-")
        ws.cell(row, 4, 0.025)
        ws.cell(row, 5, 0.90)
        ws.cell(row, 6, f"=ROUNDUP(((NORM.S.INV(1-D{row})+NORM.S.INV(E{row}))/B{row})^2,0)")
        ws.cell(row, 7, "标准化配对差近似；正式分析必须模拟截尾、miss mass、分层权重、variant/batch 相关和联合 IUT。")
        for col in [2, 4, 5]:
            input_cell(ws.cell(row, col), "Planning sensitivity grid only.")
        ws.cell(row, 2).number_format = "0.00"
        ws.cell(row, 4).number_format = ws.cell(row, 5).number_format = "0.0%"
        formula_cell(ws.cell(row, 6))
        row += 1
    style_table(ws, 4, row - 1, 1, 7)
    chart = LineChart()
    chart.title = "配对二元终点：n 对 margin 越界间隔的敏感性"
    chart.y_axis.title = "近似 n"
    chart.x_axis.title = "敏感性网格行（按 q 分组）"
    data = Reference(ws, min_col=6, min_row=3, max_row=15)
    chart.add_data(data, titles_from_data=True)
    chart.height = 7
    chart.width = 14
    ws.add_chart(chart, "I4")
    autosize(ws, {1: 18, 2: 23, 3: 25, 4: 14, 5: 14, 6: 14, 7: 72})


def build_strata(wb: Workbook) -> None:
    ws = wb.create_sheet("场景分层")
    title(ws, "建议的 24 个危险科学层与 pilot 分配", 8)
    header(ws, 3, ["stratum_id", "拓扑", "事故路径族", "严重度", "smoke n", "kernel-fit n", "held-out n", "pilot hazard 合计"])
    topologies = [
        ("T1", "独立联锁 ESD + 紧急冷却/泄压屏障链"),
        ("T2", "共享检测/执行公共原因 + 备用淬灭/围堵屏障链"),
    ]
    paths = [
        ("P1", "冷却/换热能力丧失或退化"),
        ("P2", "进料流量、浓度或反应活性突增"),
        ("P3", "搅拌/传热退化导致局部热积累"),
        ("P4", "传感器/控制器偏置、执行器饱和或延迟"),
    ]
    severities = [("L", "可恢复偏离"), ("M", "多屏障 demand"), ("H", "接近 top-event/containment 边界")]
    row = 4
    for topo, path, sev in product(topologies, paths, severities):
        ws.cell(row, 1, f"{topo[0]}-{path[0]}-{sev[0]}")
        ws.cell(row, 2, f"{topo[0]}：{topo[1]}")
        ws.cell(row, 3, f"{path[0]}：{path[1]}")
        ws.cell(row, 4, f"{sev[0]}：{sev[1]}")
        ws.cell(row, 5, 5)
        ws.cell(row, 6, 40)
        ws.cell(row, 7, 20)
        ws.cell(row, 8, f"=SUM(E{row}:G{row})")
        for col in range(5, 8):
            input_cell(ws.cell(row, col), "Provisional coverage allocation; not confirmatory n.")
        formula_cell(ws.cell(row, 8))
        row += 1
    ws.cell(row, 1, "TOTAL")
    for col in range(5, 9):
        letter = get_column_letter(col)
        ws.cell(row, col, f"=SUM({letter}4:{letter}{row-1})")
        formula_cell(ws.cell(row, col))
    for col in range(1, 9):
        ws.cell(row, col).fill = PatternFill("solid", fgColor=LIGHT_GREEN)
        ws.cell(row, col).font = Font(name="Arial", bold=True)
    style_table(ws, 4, row, 1, 8)
    autosize(ws, {1: 16, 2: 48, 3: 44, 4: 34, 5: 12, 6: 14, 7: 14, 8: 18})


def build_stage_resources(wb: Workbook) -> None:
    ws = wb.create_sheet("阶段资源")
    title(ws, "G0–G10 执行阶段、退出门与推荐资源", 11)
    header(ws, 3, ["Gate", "周", "任务", "关键产物", "退出条件", "主角色", "人日", "CPU-h", "T4 GPU-h", "工作存储GB", "状态"])
    rows = [
        ("G0", "W1", "冻结研究主张、版本 DAG、资源上限", "NormativeReleaseManifest / ClaimRegister", "主张/范围/版本唯一", "PI+方法负责人", 8, 10, 0, 10, "READY-TO-START"),
        ("G1", "W1–2", "两拓扑、24层、集合动作真值、权限矩阵", "ScenarioSupport / ActionTruth / access matrix", "两名独立安全复核签署", "过程安全+复核者", 18, 20, 0, 20, "BLOCKED-REVIEWERS"),
        ("G2", "W2–6", "实现 v20 compiler/runtime、P0-C、攻击/性质测试", "property report / SBOM / hashes", "所有 conformance oracle 通过", "编译器+复现工程", 42, 120, 0, 80, "BLOCKED-IMPLEMENTATION"),
        ("G3", "W2–6", "两类 CSTR 物理模型、guard、barrier lifecycle、fault injection", "CSTRQualificationReport", "守恒/边界/时序独立复核通过", "过程仿真工程师", 32, 200, 0, 120, "BLOCKED-MODEL"),
        ("G4", "W5–7", "强基线、信息集公平、容器化", "MethodRegistry / InformationSetDiff", "A/G/C/消融/M0–M4 全冻结", "基线+复现工程", 22, 90, 24, 100, "BLOCKED-BASELINES"),
        ("G5", "W7–9", "train/select/smoke/kernel-fit/held-out pilot", "G* selection / pilot lock", "G* 唯一、kernel/ICC/覆盖合格", "统计+实验工程", 18, 160, 36, 250, "BLOCKED-PILOT"),
        ("G6", "W9–10", "联合功效、I类错误、SSR查表、compute benchmark", "power search/confirm / SSR", "全部主张 simultaneous power 下限≥0.90", "统计负责人", 14, 150, 0, 60, "BLOCKED-INPUTS"),
        ("G7", "W11", "预注册、容器 digest、test seed 密封", "preregistration / TestManifest", "一次 dry-run hash 一致", "PI+复现工程", 8, 20, 0, 20, "BLOCKED-G0-G6"),
        ("G8", "W12–13", "确认性 paired test 一次执行", "RunLedger / raw outputs", "无协议外 rerun、ledger 完整", "实验工程", 8, 250, 8, 500, "BLOCKED-G7"),
        ("G9", "W14", "盲态分析、独立容器复算、一次解盲", "BundleEndpointTable / attestation", "两容器 hash 一致", "统计+独立复算者", 10, 60, 0, 80, "BLOCKED-G8"),
        ("G10", "W14–15", "IDAES second simulator + TEP 分组盲测/攻击支持", "ExternalValidationManifest", "至少一项外部支持闭合", "外部验证负责人", 17, 120, 12, 200, "BLOCKED-IMPLEMENTATION"),
        ("Paper", "W16", "主文/补充材料/匿名数据与代码包", "submission bundle", "数据声明与永久标识草案完成", "PI+数据管家", 10, 20, 0, 40, "BLOCKED-G9-G10"),
    ]
    for r, values in enumerate(rows, 4):
        for c, value in enumerate(values, 1):
            ws.cell(r, c, value)
        if values[-1] == "READY-TO-START":
            ws.cell(r, 11).fill = PatternFill("solid", fgColor=LIGHT_GREEN)
        else:
            ws.cell(r, 11).fill = PatternFill("solid", fgColor=RED)
    total_row = 4 + len(rows)
    ws.cell(total_row, 1, "TOTAL")
    for col in [7, 8, 9, 10]:
        letter = get_column_letter(col)
        ws.cell(total_row, col, f"=SUM({letter}4:{letter}{total_row-1})")
    style_table(ws, 4, total_row, 1, 11)
    for col in range(1, 12):
        ws.cell(total_row, col).fill = PatternFill("solid", fgColor=LIGHT_GREEN)
        ws.cell(total_row, col).font = Font(name="Arial", bold=True)
    autosize(ws, {1: 10, 2: 12, 3: 42, 4: 38, 5: 38, 6: 24, 7: 10, 8: 10, 9: 12, 10: 14, 11: 24})


def build_people(wb: Workbook) -> None:
    ws = wb.create_sheet("人力预算")
    title(ws, "角色、人日与可选成本输入", 7)
    header(ws, 3, ["角色", "低档人日", "推荐人日", "高档人日", "日费率 RMB（输入）", "推荐成本 RMB", "职责"])
    rows = [
        ("PI/方法负责人", 10, 15, 25, None, "主张、范围、裁决、论文"),
        ("v20 compiler/runtime 工程师", 20, 35, 55, None, "工件编译、状态机、隔离、容器"),
        ("CSTR/过程安全工程师", 20, 30, 50, None, "机理模型、屏障、ActionTruth"),
        ("实验与复现工程师", 16, 25, 40, None, "运行器、ledger、CI、数据包"),
        ("统计/功效负责人", 10, 18, 30, None, "kernel、覆盖、功效、SSR、SAP"),
        ("基线/ML 工程师", 6, 12, 20, None, "IFNet/HEFR/AE/LSTM 等"),
        ("独立安全复核者×2", 8, 12, 20, None, "动作集合、边界、物理资格"),
        ("外部验证负责人", 5, 12, 20, None, "IDAES/TEP/攻击/transport"),
        ("数据管家/论文整合", 5, 10, 15, None, "归档、DOI、表图、数据声明"),
    ]
    for r, row in enumerate(rows, 4):
        ws.cell(r, 1, row[0])
        for c, value in enumerate(row[1:4], 2):
            ws.cell(r, c, value)
            input_cell(ws.cell(r, c), "Planning person-day estimate; replace with team commitments.")
        ws.cell(r, 5, row[4])
        input_cell(ws.cell(r, 5), "Optional user-entered internal or contractor day rate; left blank to avoid inventing prices.")
        ws.cell(r, 6, f'=IF(E{r}="","",C{r}*E{r})')
        formula_cell(ws.cell(r, 6))
        ws.cell(r, 7, row[5])
    total = 4 + len(rows)
    ws.cell(total, 1, "TOTAL")
    for col in [2, 3, 4, 6]:
        letter = get_column_letter(col)
        ws.cell(total, col, f"=SUM({letter}4:{letter}{total-1})")
    style_table(ws, 4, total, 1, 7)
    for col in range(1, 8):
        ws.cell(total, col).fill = PatternFill("solid", fgColor=LIGHT_GREEN)
        ws.cell(total, col).font = Font(name="Arial", bold=True)
    for row in range(4, total + 1):
        ws.cell(row, 5).number_format = ws.cell(row, 6).number_format = '¥#,##0;[Red](¥#,##0);-'
    autosize(ws, {1: 30, 2: 14, 3: 14, 4: 14, 5: 20, 6: 20, 7: 52})


def build_devices(wb: Workbook) -> None:
    ws = wb.create_sheet("设备判定")
    title(ws, "双机职责与 T4 服务器资格阈值", 7)
    header(ws, 3, ["设备", "指标", "已知/实测", "最低", "推荐", "判定", "说明"])
    rows = [
        ("本机", "CPU", "Intel i5-1340P / 16 logical", 16, 32, "DEV-ONLY", "可开发、测试、审计；不作为确认试验主运行节点"),
        ("本机", "RAM GB", 15.7, 64, 128, "FAIL-CONFIRM", "仅约 2 GB 可用（体检时），不适合并行容器"),
        ("本机", "D盘可用 GB", 85.7, 1000, 2000, "FAIL-CONFIRM", "不得保存正式 raw run archive"),
        ("本机", "NVIDIA GPU", "无", "可选", "可选", "OK-DEV", "主方法不要求 GPU"),
        ("T4服务器", "GPU", "NVIDIA T4（用户提供）", "T4 16GB", "T4 16GB", "PASS-GPU", "官方规格：16GB GDDR6；用于学习基线/推理"),
        ("T4服务器", "逻辑线程", None, 16, 32, "PENDING-PROBE", "主仿真容量关键项"),
        ("T4服务器", "RAM GB", None, 64, 128, "PENDING-PROBE", "少于64GB时需降低并发或增加节点"),
        ("T4服务器", "可用 NVMe GB", None, 1000, 2000, "PENDING-PROBE", "推荐2TB；高档约需3TB归档/备份"),
        ("T4服务器", "容器运行时", None, "Docker/Podman", "rootless + digest pin", "PENDING-PROBE", "确认试验必须固定镜像 digest"),
        ("T4服务器", "OS/驱动", None, "Linux/Windows均可", "Ubuntu LTS + CUDA与驱动冻结", "PENDING-PROBE", "GPU信息必须入 RunManifest"),
    ]
    for r, row in enumerate(rows, 4):
        for c, value in enumerate(row, 1):
            ws.cell(r, c, value)
        if row[0] == "T4服务器" and row[2] is None:
            input_cell(ws.cell(r, 3), "Populate from tools/probe_experiment_server_v66.py on the T4 server.")
        ws.cell(r, 6).fill = PatternFill("solid", fgColor=LIGHT_GREEN if "PASS" in row[5] or "OK" in row[5] else RED if "FAIL" in row[5] else YELLOW)
    style_table(ws, 4, 3 + len(rows), 1, 7)
    autosize(ws, {1: 16, 2: 22, 3: 28, 4: 18, 5: 24, 6: 20, 7: 54})


def build_risks(wb: Workbook) -> None:
    ws = wb.create_sheet("阻断清单")
    title(ws, "正式 confirm test 前的阻断项", 7)
    header(ws, 3, ["优先级", "阻断项", "当前证据", "关闭动作", "Owner", "目标 Gate", "状态"])
    rows = [
        ("P0", "v20 尚未在 risk-fusion-bench 实现", "9 tests pass，但代码仍是 v5 骨架", "实现 SafetyArtifactIR、mapping、setwise eligibility、root-global runtime 与隔离", "compiler/runtime", "G2", "OPEN"),
        ("P0", "SESOI/no-harm margins 未签署", "v6.5 power JSON 全为 null", "业务+安全+统计三方签署；不能从 test 反推", "PI/safety/stats", "G0/G6", "OPEN"),
        ("P0", "ActionTruth 与 24 层未双复核", "无签名 manifest", "两名独立安全复核者完成集合动作、禁止动作与屏障向量", "safety reviewers", "G1", "OPEN"),
        ("P0", "CSTR 物理资格未建立", "无守恒/边界/oracle 报告", "两拓扑建模并由独立过程安全人员复核", "CSTR engineer", "G3", "OPEN"),
        ("P0", "T4服务器 CPU/RAM/NVMe 未知", "仅知有 NVIDIA T4", "运行环境探针并回填设备判定", "resource owner", "G0/G6", "OPEN"),
        ("P1", "G* 强基线与公平合同未实现", "当前仓库无 IFNet/HEFR/多准则折扣容器", "冻结候选库、预算、信息集与 tie-break", "baseline engineer", "G4/G5", "OPEN"),
        ("P1", "joint endpoint kernel/功效不存在", "无独立 pilot", "kernel-fit + held-out pilot；5000 search/10000 confirm MC", "statistician", "G5/G6", "OPEN"),
        ("P1", "外部效度未闭合", "仅一个建模生态", "IDAES second simulator；TEP按simulationRun分组；攻击层独立", "external validation", "G10", "OPEN"),
    ]
    for r, row in enumerate(rows, 4):
        for c, value in enumerate(row, 1):
            ws.cell(r, c, value)
        ws.cell(r, 1).fill = PatternFill("solid", fgColor=RED if row[0] == "P0" else YELLOW)
        ws.cell(r, 7).fill = PatternFill("solid", fgColor=RED)
    style_table(ws, 4, 3 + len(rows), 1, 7)
    autosize(ws, {1: 10, 2: 38, 3: 42, 4: 58, 5: 22, 6: 14, 7: 14})


def build_sources(wb: Workbook) -> None:
    ws = wb.create_sheet("研究依据")
    title(ws, "近期研究与官方要求对实验设计的影响", 5)
    header(ws, 3, ["来源", "年份", "DOI/URL", "本项目实验改变", "证据类型"])
    rows = [
        ("Shenoy, On distinct belief functions in Dempster–Shafer theory", 2023, "https://proceedings.mlr.press/v215/shenoy23a.html", "正交操纵来源依赖×数值冲突；加入低冲突重复源和高冲突独立源反例", "原始论文"),
        ("Guo et al., uncertainty reasoning and quantification survey", 2024, "https://doi.org/10.1016/j.inffus.2023.101987", "分开报告 vacuity/epistemic、discord/conflict、aleatoric，不用单一总不确定度判胜", "Information Fusion"),
        ("Wang et al., IFNet", 2025, "https://doi.org/10.1016/j.inffus.2024.102750", "加入未知相关学习基线，报告相关结构 OOD 与校准", "Information Fusion"),
        ("Dong et al., multi-criteria conflict evidence combination", 2024, "https://doi.org/10.1016/j.inffus.2024.102346", "纳入强冲突折扣基线并单测依赖泄漏攻击", "Information Fusion"),
        ("Zhang et al., large-scale multi-source fusion", 2025, "https://doi.org/10.1016/j.inffus.2024.102754", "单独验证 Observation-to-BPA；增加源数×焦元数、内存、吞吐和尾延迟", "Information Fusion"),
        ("Barhoumi et al., empirical uncertainty measures", 2025, "https://doi.org/10.1016/j.inffus.2025.103106", "禁止仅以不确定度下降判胜；复合终点必须披露组件", "Information Fusion"),
        ("ACCESS assurance-case engineering", 2024, "https://doi.org/10.1016/j.jss.2024.112034", "保存 claim→adapter→BPA→certificate→commit→action 全链路并测试版本漂移失效", "JSS原始论文"),
        ("Additional Tennessee Eastman Process Simulation Data", 2017, "https://doi.org/10.7910/DVN/6C3JR1", "按 simulationRun 分组，不按时间点随机切分；保留故障类型/seed盲测", "官方数据集"),
        ("IDAES CSTR model", 2026, "https://idaes-pse.readthedocs.io/en/stable/reference_guides/model_libraries/generic/unit_models/cstr.html", "作为第二机理模拟域；dynamic/holdup/物料能量动量平衡/传热/反应包", "官方文档"),
        ("NVIDIA T4 datasheet", 2026, "https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/tesla-t4/t4-tensor-core-datasheet-951643.pdf", "T4 16GB用于神经基线/推理；主CSTR仿真保持CPU可复现", "官方硬件规格"),
        ("Information Fusion Guide for Authors", 2026, "https://www.sciencedirect.com/journal/information-fusion/publish/guide-for-authors", "从首轮运行冻结数据、代码、模型、容器、seed并准备仓库/数据声明", "期刊官方要求"),
    ]
    for r, row in enumerate(rows, 4):
        for c, value in enumerate(row, 1):
            ws.cell(r, c, value)
        ws.cell(r, 3).font = Font(name="Arial", size=10, color=GREEN, underline="single")
    style_table(ws, 4, 3 + len(rows), 1, 5)
    autosize(ws, {1: 52, 2: 10, 3: 72, 4: 72, 5: 20})


def main() -> None:
    wb = Workbook()
    build_readme(wb)
    build_inputs(wb)
    build_resource_summary(wb)
    build_power(wb)
    build_strata(wb)
    build_stage_resources(wb)
    build_people(wb)
    build_devices(wb)
    build_risks(wb)
    build_sources(wb)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
    wb.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
