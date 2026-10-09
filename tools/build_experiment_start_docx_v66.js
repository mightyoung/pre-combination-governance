const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  Header,
  HeadingLevel,
  LevelFormat,
  Packer,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableOfContents,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const root = path.resolve(__dirname, "..");
const input = path.join(root, "实验启动计划v6.6-双机执行与资源预算.md");
const output = path.join(root, "实验启动计划v6.6-双机执行与资源预算.docx");
const lines = fs.readFileSync(input, "utf8").replace(/\r\n/g, "\n").split("\n");

const contentWidth = 9026;
const border = { style: BorderStyle.SINGLE, size: 1, color: "B7B7B7" };
const borders = { top: border, bottom: border, left: border, right: border };
const numbering = [];
let listCounter = 0;

function inline(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/\S+)/g;
  let last = 0;
  for (const match of text.matchAll(re)) {
    if (match.index > last) out.push(new TextRun({ text: text.slice(last, match.index), ...base }));
    const token = match[0];
    if (token.startsWith("**")) {
      out.push(new TextRun({ text: token.slice(2, -2), bold: true, ...base }));
    } else if (token.startsWith("`")) {
      out.push(new TextRun({ text: token.slice(1, -1), font: "Consolas", color: "7F6000", ...base }));
    } else {
      const clean = token.replace(/[),.;，。；]+$/, "");
      const suffix = token.slice(clean.length);
      out.push(new ExternalHyperlink({
        link: clean,
        children: [new TextRun({ text: clean, style: "Hyperlink", ...base })],
      }));
      if (suffix) out.push(new TextRun({ text: suffix, ...base }));
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out.length ? out : [new TextRun({ text, ...base })];
}

function listRef(format) {
  const reference = `${format}-${++listCounter}`;
  numbering.push({
    reference,
    levels: [{
      level: 0,
      format: format === "bullet" ? LevelFormat.BULLET : LevelFormat.DECIMAL,
      text: format === "bullet" ? "•" : "%1.",
      alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } },
    }],
  });
  return reference;
}

function makeTable(rows) {
  const cols = Math.max(...rows.map((r) => r.length));
  const baseWidth = Math.floor(contentWidth / cols);
  const widths = Array(cols).fill(baseWidth);
  widths[cols - 1] += contentWidth - baseWidth * cols;
  return new Table({
    width: { size: contentWidth, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((row, rowIndex) => new TableRow({
      cantSplit: true,
      tableHeader: rowIndex === 0,
      children: widths.map((width, colIndex) => new TableCell({
        width: { size: width, type: WidthType.DXA },
        borders,
        shading: rowIndex === 0 ? { fill: "4472C4", type: ShadingType.CLEAR } : undefined,
        margins: { top: 80, bottom: 80, left: 100, right: 100 },
        children: [new Paragraph({
          spacing: { after: 0 },
          children: inline(row[colIndex] || "", {
            bold: rowIndex === 0,
            color: rowIndex === 0 ? "FFFFFF" : "000000",
            size: 18,
          }),
        })],
      })),
    })),
  });
}

function parseTable(start) {
  const rows = [];
  let i = start;
  while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
    const cells = lines[i].trim().slice(1, -1).split("|").map((x) => x.trim());
    if (!cells.every((x) => /^:?-{3,}:?$/.test(x))) rows.push(cells);
    i += 1;
  }
  return { table: makeTable(rows), next: i };
}

function parse() {
  const children = [];
  let i = 0;
  let activeList = null;
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line) {
      activeList = null;
      i += 1;
      continue;
    }
    if (/^\|.*\|$/.test(line) && i + 1 < lines.length && /^\|\s*:?-{3,}/.test(lines[i + 1])) {
      const parsed = parseTable(i);
      children.push(parsed.table, new Paragraph({ spacing: { after: 80 } }));
      i = parsed.next;
      activeList = null;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      children.push(new Paragraph({
        heading: [HeadingLevel.TITLE, HeadingLevel.HEADING_1, HeadingLevel.HEADING_2][level - 1],
        pageBreakBefore: level === 2 && !heading[2].startsWith("Material Passport") && children.length > 5,
        children: inline(heading[2]),
      }));
      if (level === 1) {
        children.push(new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 240 },
          children: [new TextRun({ text: "基于 v20 / v6.5 | 2026-07-14", color: "5B6573", italics: true })],
        }));
        children.push(new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }));
      }
      activeList = null;
      i += 1;
      continue;
    }
    const bullet = raw.match(/^\s*-\s+(.*)$/);
    const numbered = raw.match(/^\s*\d+\.\s+(.*)$/);
    if (bullet || numbered) {
      const kind = bullet ? "bullet" : "number";
      if (!activeList || activeList.kind !== kind) activeList = { kind, ref: listRef(kind) };
      children.push(new Paragraph({
        numbering: { reference: activeList.ref, level: 0 },
        spacing: { after: 80 },
        children: inline((bullet || numbered)[1]),
      }));
      i += 1;
      continue;
    }
    if (/^`[^`]+`。?$/.test(line) || /^n ≈/.test(line)) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 80, after: 120 },
        shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
        children: [new TextRun({ text: line.replace(/`/g, ""), font: "Consolas", color: "7F6000" })],
      }));
    } else {
      children.push(new Paragraph({
        spacing: { after: 120, line: 360 },
        alignment: AlignmentType.JUSTIFIED,
        children: inline(line),
      }));
    }
    activeList = null;
    i += 1;
  }
  return children;
}

const children = parse();
const doc = new Document({
  numbering: { config: numbering },
  styles: {
    default: { document: { run: { font: "Microsoft YaHei", size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 40, bold: true, font: "Microsoft YaHei", color: "17365D" },
        paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 120, after: 160 }, outlineLevel: 0 } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Microsoft YaHei", color: "17365D" },
        paragraph: { spacing: { before: 240, after: 140 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "4472C4", space: 1 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Microsoft YaHei", color: "2F5597" },
        paragraph: { spacing: { before: 180, after: 100 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: "Microsoft YaHei", color: "44546A" },
        paragraph: { spacing: { before: 140, after: 80 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1134, right: 1440, bottom: 1134, left: 1440 },
      },
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "B4C6E7", space: 1 } },
        children: [new TextRun({ text: "实验启动计划 v6.6 | PLANNING-ONLY", color: "5B6573", size: 18 })],
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        children: [new TextRun({ text: "第 ", color: "5B6573", size: 18 }), new TextRun({ children: [PageNumber.CURRENT], color: "5B6573", size: 18 }), new TextRun({ text: " 页", color: "5B6573", size: 18 })],
      })] }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(output, buffer);
  console.log(output);
});
