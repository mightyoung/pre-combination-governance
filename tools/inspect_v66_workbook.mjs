import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workspace = process.cwd();
const inputPath = path.join(workspace, "实验资源与样本量预算v6.6.xlsx");
const outputDir = path.join(workspace, "outputs", "v66-workbook-preview");
await fs.mkdir(outputDir, { recursive: true });

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table,drawing,definedName",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 10,
  tableMaxCellChars: 120,
});

const sheets = [];
for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange();
  const address = used?.address ?? null;
  const region = address
    ? await workbook.inspect({
        kind: "region,formula,computedStyle",
        sheetId: sheet.name,
        range: address,
        maxChars: 8000,
        tableMaxRows: 12,
        tableMaxCols: 12,
        tableMaxCellChars: 120,
        options: { maxResults: 120 },
      })
    : null;

  const preview = await workbook.render({
    sheetName: sheet.name,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const safeName = sheet.name.replace(/[<>:"/\\|?*]/g, "_");
  const previewPath = path.join(outputDir, `${safeName}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

  sheets.push({
    name: sheet.name,
    usedRange: address,
    region: region?.ndjson ?? String(region ?? ""),
    previewPath,
  });
}

const result = {
  inputPath,
  outputDir,
  overview: overview?.ndjson ?? String(overview),
  sheets,
};
await fs.writeFile(
  path.join(outputDir, "inspection.json"),
  JSON.stringify(result, null, 2),
  "utf8",
);
console.log(JSON.stringify({
  inputPath,
  outputDir,
  sheetCount: sheets.length,
  sheets: sheets.map(({ name, usedRange, previewPath }) => ({ name, usedRange, previewPath })),
}, null, 2));
