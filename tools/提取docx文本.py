# -*- coding: utf-8 -*-
"""
把本文件夹（仅根目录，不含 academic-research-skills）下的所有 .docx
转成 .txt，输出到子文件夹 _docx文本提取，供后续按路径读取。
纯标准库实现，无需 pip 安装任何东西。
运行方式（任选其一）：
  1) 打开 Anaconda Prompt / 命令提示符，cd 到本文件夹，执行:  python 提取docx文本.py
  2) 右键本文件 -> 用 Python 运行 / 通过 IDLE 打开后按 F5
"""
import zipfile, re, os, glob

def docx_to_text(path):
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return f"[无法打开该docx: {e}]"
    names = z.namelist()
    order = ['word/document.xml']
    order += sorted(n for n in names
                    if re.match(r'word/(header\d*|footer\d*|footnotes|endnotes)\.xml$', n))
    chunks = []
    for name in order:
        if name not in names:
            continue
        xml = z.read(name).decode('utf-8', errors='ignore')
        xml = xml.replace('</w:p>', '\n')
        xml = xml.replace('<w:br/>', '\n').replace('<w:br />', '\n')
        xml = xml.replace('<w:tab/>', '\t').replace('<w:tab />', '\t')
        text = re.sub(r'<[^>]+>', '', xml)
        for a, b in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                     ('&quot;', '"'), ('&apos;', "'"), ('&#160;', ' ')]:
            text = text.replace(a, b)
        text = re.sub(r'\n[ \t]+\n', '\n\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        chunks.append(text.strip())
    return '\n\n'.join(c for c in chunks if c)

folder = os.path.dirname(os.path.abspath(__file__))
outdir = os.path.join(folder, '_docx文本提取')
os.makedirs(outdir, exist_ok=True)

n = 0
for path in sorted(glob.glob(os.path.join(folder, '*.docx'))):
    txt = docx_to_text(path)
    base = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(outdir, base + '.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(txt)
    n += 1
    print('OK ->', out, f'({len(txt)} 字符)')

print(f'\n完成：共转换 {n} 个 docx，输出目录：{outdir}')
