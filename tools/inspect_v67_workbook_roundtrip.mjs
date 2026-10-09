import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "file:///C:/Users/might/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workspace = process.argv[2];
if (!workspace) throw new Error("Usage: node inspect_v67_workbook_roundtrip.mjs <workspace>");
const inputPath = path.join(workspace, "实验资源与样本量预算v6.7.xlsx");
const outputDir = path.join(workspace, "outputs", "v67-workbook-roundtrip-preview");
await fs.mkdir(outputDir, { recursive: true });

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const overview = await workbook.inspect({
  kind: "workbook,sheet,formula",
  maxChars: 10000,
  tableMaxRows: 10,
  tableMaxCols: 10,
  options: { maxResults: 250 },
});
const sheets = [];
for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange();
  const address = used?.address ?? null;
  const region = address ? await workbook.inspect({
    kind: "region,formula",
    sheetId: sheet.name,
    range: address,
    maxChars: 14000,
    tableMaxRows: 80,
    tableMaxCols: 12,
    tableMaxCellChars: 160,
    options: { maxResults: 350 },
  }) : null;
  const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
  const previewPath = path.join(outputDir, `${sheet.name}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  sheets.push({ name: sheet.name, usedRange: address, region: region?.ndjson ?? String(region ?? ""), previewPath });
}

const critical = {
  planningN: workbook.worksheets.getItem("Inputs").getRange("B29:B30").values,
  armFrameTotals: workbook.worksheets.getItem("ArmFrame").getRange("H20:H21").values,
  resourceGates: workbook.worksheets.getItem("ResourceSummary").getRange("A17:B18").values,
  resourceValues: workbook.worksheets.getItem("ResourceSummary").getRange("A4:B16").values,
  personnelTotal: workbook.worksheets.getItem("Personnel").getRange("E14").values,
  scheduleTotals: workbook.worksheets.getItem("Schedule").getRange("C15:G16").values,
};
const inspection = { inputPath, outputDir, overview: overview?.ndjson ?? String(overview), sheets, critical };
await fs.writeFile(path.join(outputDir, "inspection.json"), JSON.stringify(inspection, null, 2), "utf8");

const corpus = JSON.stringify(inspection);
const tokens = ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A"];
const errors = Object.fromEntries(tokens.map(t => [t, corpus.split(t).length - 1]));
const result = { inputPath, outputDir, sheetCount: sheets.length, errors, critical };
console.log(JSON.stringify(result, null, 2));
process.exitCode = Object.values(errors).some(n => n > 0) ? 1 : 0;
