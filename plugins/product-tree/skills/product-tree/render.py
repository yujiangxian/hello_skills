#!/usr/bin/env python3
"""从产品树文件生成一张图，并检查编号。

用法：
  python render.py <树文件> [-o 输出.html] [--check] [--editor none|cursor|vscode]

- 不给 -o：写到树文件同目录、同名的 .html。
- --check：只检查，不生成页面；有问题时退出码 1。
- --editor：点击图上的条目时怎么打开树文件。none 复制「路径:行号」（默认），
  cursor / vscode 跳到编辑器里那一行。
- 只用 Python 3 标准库。页面模板是本文件同目录的 viewer.html；
  生成的页面是单个文件，不引外部脚本、样式、字体，双击就能打开。
  页面是一张可展开的思维导图：功能下面是子功能，再下面是入口和重复做法。
  节点只写短名称，不把字段和表格再排一遍。

树文件怎么写见同目录 template.md。脚本靠这些读：
- 标题层级：## 核心功能 / 扩展功能 / 界面与交互 / 待合并 / 已并入与已删除。
- 功能节点：核心功能、扩展功能下的「### 编号 名称」，子功能「#### 编号 名称」。
- 节点字段：「- 字段：值」一行一个（全角冒号），缩进的子行归上一个字段。
- 表格：第一列放编号（列名 #、编号、编号或页面等）；页面表没有编号时用页面名。
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

BRANCHES = (
    ("核心功能", "core"),
    ("扩展功能", "ext"),
    ("界面与交互", "ui"),
    ("待合并", "merge"),
    ("已并入与已删除", "gone"),
)
BRANCH_TAB = {"core": "features", "ext": "features", "ui": "ui", "merge": "merge", "gone": "gone"}
PRODUCT_TITLES = ("产品", "产品描述")
STATUS_CLASSES = (
    ("已上线", "online"),
    ("部分上线", "partial"),
    ("开发中", "dev"),
    ("规划中", "planned"),
    ("未盘点", "unsurveyed"),
)
NO_STATUS = "没写状态"
NAME_HEADERS = ("页面", "名称", "原名称", "原页面", "页面类型", "操作", "对象", "要做成什么", "同一件事")

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
HR = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
FIELD = re.compile(r"^[-*+][ \t]+([^\s：:`*|\[][^：`|]{0,15}?)[ \t]*：[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[-*+][ \t]+(.*)$")
NODE_TITLE = re.compile(r"^([A-Za-z]+[0-9]+(?:\.[0-9]+)*)[ \t]+(.+)$")
ID_CELL = re.compile(r"^[A-Za-z]+[0-9]+(?:\.[0-9]+)*$")
ID_LIKE = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{1,3}[0-9]+(?:\.[0-9]+)*(?![A-Za-z0-9_])")
RUN = re.compile(r"[A-Za-z0-9_]+(?:\.[0-9]+)*")
CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
URL = re.compile(r"https?://[^\s<>()（）「」，。；、]+")
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
PAREN = re.compile(r"（[^（）]*）|\([^()]*\)")
STEP_MARK = re.compile(r"(?:^|(?<=[\s。；;，,]))([0-9]{1,2})[）)]")
NONEISH = re.compile(r"^(无|未盘点|暂无|没有|现在没有|—|–|-)")
PATH_IN_CODE = re.compile(r"`(/[^`\s]*)`")


# ---------- 读文件 ----------

class Line:
    __slots__ = ("text", "file", "no", "abspath", "fenced")

    def __init__(self, text, file, no, abspath):
        self.text, self.file, self.no, self.abspath, self.fenced = text, file, no, abspath, False


class Sec:
    def __init__(self, level, title, line):
        self.level, self.title, self.line = level, title, line
        self.lines, self.children, self.node_keys, self.blocks = [], [], [], []
        self.parent = self.branch = self.node = None


def shown(path):
    try:
        rel = os.path.relpath(path)
    except ValueError:
        rel = str(path)
    if rel.startswith(".."):
        rel = str(path)
    return rel.replace("\\", "/")


def slash(path):
    """绝对路径，正斜杠，盘符保留。给编辑器链接和剪贴板用。"""
    return Path(path).resolve().as_posix()


def plain(s):
    s = MD_LINK.sub(lambda m: m.group(1), s or "")
    return s.replace("**", "").replace("`", "").strip()


def branch_of(title):
    t = plain(title)
    for name, b in BRANCHES:
        if t == name or t.startswith(name):
            return b
    return None


def mark_fences(lines):
    fence = None
    for ln in lines:
        if fence:
            ln.fenced = True
            s = ln.text.strip()
            if s and set(s) == {fence[0]} and len(s) >= len(fence):
                fence = None
            continue
        m = FENCE.match(ln.text)
        if m:
            ln.fenced = True
            fence = m.group(1)


def read_lines(path):
    text = path.read_text(encoding="utf-8-sig")
    ap = slash(path)
    lines = [Line(t, shown(path), i + 1, ap) for i, t in enumerate(text.splitlines())]
    mark_fences(lines)
    return lines


def splice(sub, link_text, path):
    """拆出去的一枝：标题层级对齐到「## 枝名」，没有枝名标题时用链接文字补一个。"""
    heads = [(ln, HEADING.match(ln.text)) for ln in sub if not ln.fenced]
    heads = [(ln, m) for ln, m in heads if m]
    if not branch_of(link_text) and not any(len(m.group(1)) <= 2 and branch_of(m.group(2)) for _, m in heads):
        return None
    out, shift = [], 0
    if heads and branch_of(heads[0][1].group(2)):
        shift = 2 - len(heads[0][1].group(1))
    else:
        out.append(Line("## " + link_text, shown(path), 1, slash(path)))
        if heads and len(heads[0][1].group(1)) <= 2:
            shift = 3 - len(heads[0][1].group(1))
    for ln in sub:
        m = None if ln.fenced else HEADING.match(ln.text)
        if m and shift:
            ln.text = "#" * min(6, max(1, len(m.group(1)) + shift)) + " " + m.group(2)
        out.append(ln)
    return out


def load(main):
    """读总文件；总文件链接到的同目录（或 <文件名>/ 子目录）里的一枝也读进来，接在末尾。"""
    main = main.resolve()
    lines = read_lines(main)
    files = [main]
    base = main.parent
    allowed = {base, base / main.stem}
    for ln in list(lines):
        if ln.fenced:
            continue
        for m in MD_LINK.finditer(ln.text):
            href = m.group(2).split("#", 1)[0]
            if not href.lower().endswith(".md") or "://" in href:
                continue
            target = (base / href).resolve()
            if target in files or not target.is_file() or target.parent not in allowed:
                continue
            part = splice(read_lines(target), plain(m.group(1)), target)
            if part:
                files.append(target)
                lines.extend(part)
    return lines, files


def sectionize(lines):
    root = Sec(0, "", None)
    stack = [root]
    for ln in lines:
        m = None if ln.fenced else HEADING.match(ln.text)
        if m:
            sec = Sec(len(m.group(1)), m.group(2).strip(), ln)
            while stack[-1].level >= sec.level:
                stack.pop()
            sec.parent = stack[-1]
            stack[-1].children.append(sec)
            stack.append(sec)
        else:
            stack[-1].lines.append(ln)
    return root


def assign_branches(sec):
    for c in sec.children:
        b = branch_of(c.title) if c.level <= 2 else None
        if b is None:
            if sec.branch in (None, "head"):
                if c.level == 1:
                    b = "head"
                elif plain(c.title) in PRODUCT_TITLES:
                    b = "product"
                else:
                    b = "other"
            else:
                b = sec.branch
        c.branch = b
        assign_branches(c)


def is_blank_or_hr(ln):
    return not ln.fenced and (not ln.text.strip() or HR.match(ln.text))


def trim(lines):
    a, b = 0, len(lines)
    while a < b and is_blank_or_hr(lines[a]):
        a += 1
    while b > a and is_blank_or_hr(lines[b - 1]):
        b -= 1
    return lines[a:b]


def dedent(texts):
    while texts and not texts[-1].strip():
        texts.pop()
    while texts and not texts[0].strip():
        texts.pop(0)
    ind = min((len(t) - len(t.lstrip(" \t")) for t in texts if t.strip()), default=0)
    return [t[ind:] if t.strip() else "" for t in texts]


def split_row(text):
    s = text.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def strip_code(text):
    return URL.sub(" ", CODE_SPAN.sub(" ", text or ""))


def strip_parens(text):
    prev = None
    while prev != text:
        prev, text = text, PAREN.sub(" ", text)
    return text


def ids_in(text, defined):
    """文字里出现的已定义编号，按出现顺序。前后紧挨字母数字的不算（N1 不算进 N10、N4.1）。"""
    out = []
    for m in RUN.finditer(text):
        tok = m.group(0)
        if tok in defined and tok not in out:
            out.append(tok)
    return out


def status_info(text):
    p = plain(text)
    if not p:
        return NO_STATUS, "none"
    label = re.split(r"[（(，,；;。\s]", p, 1)[0] or p
    for name, cls in STATUS_CLASSES:
        if p.startswith(name):
            return name, cls
    return label[:12], "other"


def split_steps(text):
    marks, want = [], 1
    for m in STEP_MARK.finditer(text):
        if int(m.group(1)) == want:
            marks.append(m)
            want += 1
    pieces = []
    if len(marks) >= 2:
        lead = text[:marks[0].start()].strip()
        if lead:
            pieces.append((None, lead))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            pieces.append((int(m.group(1)), text[m.end():end].strip()))
    elif "→" in text:
        pieces = [(i + 1, p.strip()) for i, p in enumerate(t for t in text.split("→") if t.strip())]
    else:
        pieces = [(None, text.strip())]
    return [{"n": n, "text": t, "broken": "断开" in t} for n, t in pieces if t]


def first_paragraph(lines):
    out = []
    for ln in lines:
        t = ln.text.strip()
        skip = (ln.fenced or not t or t.startswith(("|", "#", ">")) or HR.match(t)
                or LIST_ITEM.match(t) or re.match(r"^\d+[.)]\s", t))
        if skip:
            if out:
                break
            continue
        out.append(t)
    return " ".join(out)


def text_em(s):
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in s)


def shorten(s, em):
    if text_em(s) <= em:
        return s
    out = ""
    for ch in s:
        if text_em(out + ch) > em - 1:
            break
        out += ch
    return out + "…"


def table_kind(branch, path):
    last = path[-1] if path else ""
    if branch == "ui":
        if "页面布局" in last or last == "布局":
            return "页面布局"
        if last.startswith("页面"):
            return "页面"
        if "任务流程" in last or last == "流程":
            return "任务流程"
        if "交互模式" in last:
            return "交互模式"
        return last or "界面与交互"
    if branch == "merge":
        return "待合并"
    if branch == "gone":
        return "已并入与已删除"
    return last or "其他"


def heading_path(sec):
    path = []
    s = sec
    while s is not None and s.level > 0:
        if not (s.level == 1 and s.branch == "head"):
            path.append(plain(s.title))
        s = s.parent
    return list(reversed(path))


def col_index(cols, name):
    for i, c in enumerate(cols):
        if plain(c) == name:
            return i
    return -1


# ---------- 解析 ----------

class Tree:
    def __init__(self):
        self.entries, self.order, self.tables, self.problems = {}, [], [], []

    def note(self, level, file, line, msg):
        self.problems.append({"level": level, "file": file, "line": line, "msg": msg})

    def register(self, key, entry):
        if key in self.entries:
            first = self.entries[key]
            self.note("问题", entry["file"], entry["line"],
                      f"{key} 定义了两次，第一处在 {first['file']} 第 {first['line']} 行")
            return False
        self.entries[key] = entry
        self.order.append(key)
        return True

    def walk(self, sec):
        for c in sec.children:
            if c.branch in ("core", "ext") and NODE_TITLE.match(plain(c.title)):
                k = self.node(c, None)
                if k:
                    sec.node_keys.append(k)
            else:
                c.blocks = self.blocks(c)
                self.walk(c)

    def node(self, sec, parent):
        m = NODE_TITLE.match(plain(sec.title))
        key, name = m.group(1), m.group(2).strip()
        sec.node = key
        lines, kids = list(sec.lines), []

        def fold(s):
            for c in s.children:
                if c.branch in ("core", "ext") and NODE_TITLE.match(plain(c.title)):
                    kids.append(c)
                else:
                    c.node = key
                    lines.append(c.line)
                    lines.extend(c.lines)
                    fold(c)

        fold(sec)
        fields, extra, cur = [], [], None
        for ln in trim(lines):
            t = ln.text
            fm = None if ln.fenced else FIELD.match(t)
            if fm:
                cur = {"name": fm.group(1).strip(), "value": fm.group(2).strip(), "body": [],
                       "body_at": [], "line": ln.no}
                fields.append(cur)
            elif cur is not None and (not t.strip() or t[:1] in " \t"):
                cur["body"].append(t)
                cur["body_at"].append(ln.no)
            else:
                cur = None
                extra.append(t)
        for f in fields:
            pairs = list(zip(f["body"], f.get("body_at") or []))
            while pairs and not pairs[-1][0].strip():
                pairs.pop()
            while pairs and not pairs[0][0].strip():
                pairs.pop(0)
            dedented = dedent([p[0] for p in pairs])
            f["body"] = "\n".join(dedented)
            f["lines"] = [{"text": txt, "line": pairs[i][1]} for i, txt in enumerate(dedented)]
            f.pop("body_at", None)
        fmap = {}
        for f in fields:
            fmap.setdefault(f["name"], f)
        status = field_text(fmap.get("状态"))
        label, cls = status_info(status)
        entry = {
            "key": key, "id": key, "kind": "功能", "branch": sec.branch,
            "group": "核心功能" if sec.branch == "core" else "扩展功能", "tab": "features",
            "name": name, "fields": fields, "extra": "\n".join(dedent(list(extra))),
            "effect": fmap["效果"]["value"] if "效果" in fmap else "",
            "status": status, "statusLabel": label, "statusClass": cls,
            "parent": parent, "children": [], "file": sec.line.file, "line": sec.line.no,
            "abspath": sec.line.abspath,
            "text": sec.title + "\n" + "\n".join(ln.text for ln in lines),
        }
        if parent and "状态" not in fmap and parent in self.entries:
            p = self.entries[parent]
            entry.update(status=p["status"], statusLabel=p["statusLabel"], statusClass=p["statusClass"])
        ok = self.register(key, entry)
        for c in kids:
            ck = self.node(c, key if ok else parent)
            if ck and ok:
                entry["children"].append(ck)
        return key if ok else None

    def blocks(self, sec):
        lines = trim(sec.lines)
        out, buf, i = [], [], 0

        def flush():
            body = trim(buf)
            if body:
                out.append({"t": "md", "text": "\n".join(ln.text for ln in body)})
            buf.clear()

        while i < len(lines):
            ln = lines[i]
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if (not ln.fenced and ln.text.lstrip().startswith("|") and nxt is not None and not nxt.fenced
                    and "-" in nxt.text and TABLE_SEP.match(nxt.text)):
                flush()
                j = i + 2
                while j < len(lines) and not lines[j].fenced and lines[j].text.lstrip().startswith("|"):
                    j += 1
                out.append({"t": "table", "i": self.table(sec, ln, lines[i + 2:j])})
                i = j
                continue
            buf.append(ln)
            i += 1
        flush()
        return out

    def table(self, sec, head, rows):
        cols = split_row(head.text)
        data = [(ln, (split_row(ln.text) + [""] * len(cols))[:len(cols)]) for ln in rows]
        path = heading_path(sec)
        kind = table_kind(sec.branch, path)
        ti = len(self.tables)
        h0 = plain(cols[0]) if cols else ""
        id_col = h0 in ("#", "id", "ID") or "编号" in h0 or any(ID_CELL.match(plain(c[0])) for _, c in data)
        name_col = next((col_index(cols, h) for h in NAME_HEADERS if col_index(cols, h) > 0), -1)
        if name_col < 0 and not id_col:
            name_col = 0
        if name_col < 0 and len(cols) > 1:
            name_col = 1
        status_col = col_index(cols, "状态")
        steps_col = col_index(cols, "步骤") if kind == "任务流程" else -1
        heading = path[-1] if path else ""
        t = {"i": ti, "columns": cols, "rows": [c for _, c in data], "keys": [], "kind": kind,
             "branch": sec.branch, "heading": heading, "file": head.file, "line": head.no,
             "rowLine": [ln.no for ln, _ in data],
             "rowFile": [ln.abspath for ln, _ in data]}
        if steps_col >= 0:
            t["steps"] = [split_steps(c[steps_col]) for _, c in data]
        self.tables.append(t)
        for ri, (ln, cells) in enumerate(data):
            c0 = plain(cells[0]) if cells else ""
            key, is_id = None, False
            if ID_CELL.match(c0):
                key, is_id = c0, True
            elif c0 and not NONEISH.match(c0) and ((kind == "页面" and not id_col) or h0 == "编号或页面"):
                key = c0
            if key:
                name = plain(cells[name_col]) if name_col >= 0 else key
                if len(name) > 60:
                    name = name[:59] + "…"
                entry = {
                    "key": key, "id": key if is_id else None, "kind": kind, "branch": sec.branch,
                    "group": heading or kind, "tab": BRANCH_TAB.get(sec.branch, "other"),
                    "name": name or key, "table": ti, "row": ri, "file": ln.file, "line": ln.no,
                    "abspath": ln.abspath,
                    "text": " | ".join(cells),
                }
                if status_col >= 0:
                    entry["status"] = cells[status_col]
                    entry["statusLabel"] = (re.split(r"[。；;，,（(]", plain(cells[status_col]), 1)[0] or "")[:14]
                    entry["statusClass"] = "plain"
                if not self.register(key, entry):
                    key = None
            t["keys"].append(key)
        return ti


def field_text(f):
    if not f:
        return ""
    return (f["value"] + "\n" + f["body"]).strip()


# ---------- 关系、检查 ----------

def build(tree):
    E, order = tree.entries, tree.order
    ids = {k for k in order if E[k]["id"]}
    for k in order:
        E[k]["mentions"] = [x for x in ids_in(strip_code(E[k]["text"]), ids) if x != k]
        E[k]["mentionedBy"] = []
    for k in order:
        for x in E[k]["mentions"]:
            E[x]["mentionedBy"].append(k)

    edges, seen = [], set()

    def add_edge(etype, a, b):
        if (etype, a, b) not in seen:
            seen.add((etype, a, b))
            edges.append({"type": etype, "from": a, "to": b})

    def typed(k, label, text, want):
        e = E[k]
        clean = strip_code(text)
        for tok in dict.fromkeys(m.group(0) for m in ID_LIKE.finditer(clean)):
            if tok not in E:
                tree.note("问题", e["file"], e["line"], f"{k}「{label}」里的 {tok} 没有定义")
        out = []
        for x in ids_in(strip_parens(clean), ids):
            if x == k:
                continue
            if want and E[x]["kind"] != want:
                tree.note("提醒", e["file"], e["line"], f"{k}「{label}」里的 {x} 不是{want}，是{E[x]['kind']}")
                continue
            out.append(x)
        return out

    for k in order:
        e = E[k]
        if e["kind"] == "功能":
            dep = next((f for f in e["fields"] if f["name"] == "依赖"), None)
            for x in typed(k, "依赖", field_text(dep), "功能") if dep else []:
                add_edge("dep", x, k)
            continue
        t = tree.tables[e["table"]]
        cells = t["rows"][e["row"]]
        for label, etype, want in (("合并到", "merge", None), ("用到的功能", "flow", "功能"), ("布局", "layout", "页面布局")):
            ci = col_index(t["columns"], label)
            if ci < 0 or (etype == "layout" and e["kind"] != "页面"):
                continue
            for x in typed(k, label, cells[ci], want):
                add_edge(etype, k, x)

    # 页面入口：节点「入口」里写到的页面路径或页面编号
    page_paths = {}
    for k in order:
        e = E[k]
        if e["kind"] != "页面":
            continue
        t = tree.tables[e["table"]]
        ci = col_index(t["columns"], "路径")
        if ci < 0:
            continue
        cell = t["rows"][e["row"]][ci]
        paths = PATH_IN_CODE.findall(cell) or re.findall(r"(?<![\w/])(/[^\s、，,；;）)]*)", cell)
        for p in paths:
            page_paths.setdefault(p.split("?")[0], k)
    by_len = sorted(page_paths, key=len, reverse=True)

    def page_of(path):
        path = path.split("?")[0]
        if path in page_paths:
            return page_paths[path]
        for p in by_len:
            if len(p) > 1 and path.startswith(p + "/"):
                return page_paths[p]
        return None

    for k in order:
        e = E[k]
        if e["kind"] != "功能":
            continue
        f = next((f for f in e["fields"] if f["name"] == "入口"), None)
        e["entryLines"] = []
        if not f:
            continue
        text = field_text(f)
        items = [f["value"]] if f["value"].strip() else []
        for ln in f["body"].split("\n"):
            m = LIST_ITEM.match(ln)
            if m:
                items.append(m.group(1))
        for it in items:
            v = re.sub(r"^[^：`]{1,12}：\s*", "", it, count=1)
            if plain(v) and not NONEISH.match(plain(v)):
                e["entryLines"].append(it)
        for p in PATH_IN_CODE.findall(text):
            pk = page_of(p)
            if pk:
                add_edge("entry", k, pk)
        for x in ids_in(strip_code(text), ids):
            if E[x]["kind"] == "页面":
                add_edge("entry", k, x)

    for k in order:
        e = E[k]
        e.update(deps=[], depBy=[], pages=[], pageFeatures=[], layouts=[], layoutPages=[], uses=[], dups=[], dupCount=0)
    for ed in edges:
        a, b, t = ed["from"], ed["to"], ed["type"]
        if t == "dep":
            E[b]["deps"].append(a)
            E[a]["depBy"].append(b)
        elif t == "entry":
            E[a]["pages"].append(b)
            E[b]["pageFeatures"].append(a)
        elif t == "layout":
            E[a]["layouts"].append(b)
            E[b]["layoutPages"].append(a)
        elif t == "flow":
            E[a]["uses"].append(b)
        elif t == "merge":
            E[b]["dups"].append(a)
            if "已合并" not in plain(E[a].get("status", "")):
                E[b]["dupCount"] += 1
    for k in order:
        e = E[k]
        if e["kind"] == "功能":
            e["entryCount"] = len(e["entryLines"])

    # 只提醒的几类
    for k in order:
        e = E[k]
        if e["kind"] != "功能":
            continue
        names = {f["name"] for f in e["fields"]}
        if "效果" not in names:
            tree.note("提醒", e["file"], e["line"], f"{k} 没写「效果」")
        if not e["parent"] and "状态" not in names:
            tree.note("提醒", e["file"], e["line"], f"{k} 没写「状态」")
        if e["branch"] == "ext" and not e["parent"] and not e["deps"]:
            dep = next((f for f in e["fields"] if f["name"] == "依赖"), None)
            how = f"「依赖」写的是「{plain(field_text(dep))}」" if dep else "没写「依赖」"
            tree.note("提醒", e["file"], e["line"], f"{k} 是扩展功能，{how}；扩展功能要写依赖哪个核心功能")
        if e["branch"] == "core":
            for x in e["deps"]:
                if E[x]["branch"] == "ext":
                    tree.note("提醒", e["file"], e["line"], f"{k} 是核心功能，却依赖扩展功能 {x}")
    return edges


# ---------- 依赖图布局 ----------

BOX_W, BOX_H, GAP_X, GAP_Y, DUMMY_H, MARGIN = 188, 52, 84, 14, 6, 20


def layout_graph(E, order, edges):
    dep = [(e["from"], e["to"]) for e in edges if e["type"] == "dep"]
    feats = [k for k in order if E[k]["kind"] == "功能"]
    involved = {a for a, _ in dep} | {b for _, b in dep}
    nodes = [k for k in feats if k in involved]
    isolated = [k for k in feats if k not in involved and not E[k]["parent"]]
    result = {"nodes": [], "edges": [], "isolated": isolated, "cycles": [], "width": 0, "height": 0,
              "box": [BOX_W, BOX_H]}
    if not nodes:
        return result

    out = {k: [] for k in nodes}
    for a, b in dep:
        out[a].append(b)
    color, back = {k: 0 for k in nodes}, set()
    for s in nodes:
        if color[s]:
            continue
        color[s], stack, path = 1, [(s, iter(out[s]))], [s]
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                color[u] = 2
                stack.pop()
                path.pop()
            elif color[v] == 0:
                color[v] = 1
                stack.append((v, iter(out[v])))
                path.append(v)
            elif color[v] == 1:
                back.add((u, v))
                result["cycles"].append(path[path.index(v):] + [v])
    dag = [(a, b) for a, b in dep if (a, b) not in back]

    pred = {k: [] for k in nodes}
    succ = {k: [] for k in nodes}
    indeg = {k: 0 for k in nodes}
    for a, b in dag:
        succ[a].append(b)
        pred[b].append(a)
        indeg[b] += 1
    layer, queue = {}, [k for k in nodes if indeg[k] == 0]
    while queue:
        u = queue.pop(0)
        layer[u] = max((layer[p] + 1 for p in pred[u]), default=0)
        for v in succ[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)

    n_layers = max(layer.values()) + 1
    layers = [[] for _ in range(n_layers)]
    for k in nodes:
        layers[layer[k]].append(k)
    real = set(nodes)
    up = {k: [] for k in nodes}
    down = {k: [] for k in nodes}
    chains = []
    for a, b in dag:
        chain = [a]
        for lv in range(layer[a] + 1, layer[b]):
            d = f"~{a}>{b}@{lv}"
            up[d], down[d] = [], []
            layers[lv].append(d)
            chain.append(d)
        chain.append(b)
        for x, y in zip(chain, chain[1:]):
            down[x].append(y)
            up[y].append(x)
        chains.append((a, b, chain))

    def positions():
        return {k: i for lay in layers for i, k in enumerate(lay)}

    def crossings():
        p, total = positions(), 0
        for lv in range(n_layers - 1):
            es = [(p[x], p[y]) for x in layers[lv] for y in down[x]]
            for i in range(len(es)):
                for j in range(i + 1, len(es)):
                    if (es[i][0] - es[j][0]) * (es[i][1] - es[j][1]) < 0:
                        total += 1
        return total

    def sweep(levels, nbrs):
        for lv in levels:
            p = positions()

            def bary(item):
                i, k = item
                ns = [p[n] for n in nbrs[k]]
                return (sum(ns) / len(ns) if ns else i, i)

            layers[lv] = [k for _, k in sorted(enumerate(layers[lv]), key=bary)]

    best, best_c = [list(x) for x in layers], crossings()
    for it in range(24):
        if it % 2 == 0:
            sweep(range(1, n_layers), up)
        else:
            sweep(range(n_layers - 2, -1, -1), down)
        c = crossings()
        if c < best_c:
            best, best_c = [list(x) for x in layers], c
    layers[:] = best

    def h(k):
        return BOX_H if k in real else DUMMY_H

    def gap(a, b):
        return GAP_Y if a in real and b in real else 8

    def offsets(lay, s, e):
        offs = [0.0]
        for j in range(s + 1, e + 1):
            offs.append(offs[-1] + h(lay[j - 1]) + gap(lay[j - 1], lay[j]))
        return offs

    y = {}
    for lay in layers:
        cur = 0.0
        for i, k in enumerate(lay):
            if i:
                cur += gap(lay[i - 1], k)
            y[k] = cur + h(k) / 2
            cur += h(k)

    def place(lay, want):
        blocks = []
        for i, k in enumerate(lay):
            blocks.append([i, i, want[k] - h(k) / 2])
            while len(blocks) > 1:
                pa, cu = blocks[-2], blocks[-1]
                po = offsets(lay, pa[0], pa[1])
                bottom = pa[2] + po[-1] + h(lay[pa[1]])
                if bottom + gap(lay[pa[1]], lay[cu[0]]) <= cu[2]:
                    break
                s, e = pa[0], cu[1]
                offs = offsets(lay, s, e)
                top = sum(want[lay[j]] - offs[j - s] - h(lay[j]) / 2 for j in range(s, e + 1)) / (e - s + 1)
                blocks[-2:] = [[s, e, top]]
        for s, e, top in blocks:
            offs = offsets(lay, s, e)
            for j in range(s, e + 1):
                y[lay[j]] = top + offs[j - s] + h(lay[j]) / 2

    for it in range(10):
        if it % 2 == 0:
            levels, nbrs = range(1, n_layers), up
        else:
            levels, nbrs = range(n_layers - 2, -1, -1), down
        for lv in levels:
            lay = layers[lv]
            want = {k: (sum(y[n] for n in nbrs[k]) / len(nbrs[k]) if nbrs[k] else y[k]) for k in lay}
            place(lay, want)

    top = min(y[k] - h(k) / 2 for lay in layers for k in lay)
    for k in y:
        y[k] += MARGIN - top
    lx = {k: MARGIN + lv * (BOX_W + GAP_X) for lv, lay in enumerate(layers) for k in lay}

    out_port, in_port = {}, {}
    for k in nodes:
        outs = sorted((c for c in chains if c[0] == k), key=lambda c: y[c[2][1]])
        ins = sorted((c for c in chains if c[1] == k), key=lambda c: y[c[2][-2]])
        for group, ports in ((outs, out_port), (ins, in_port)):
            n = len(group)
            step = min(8.0, (BOX_H - 16) / max(n, 1))
            for i, c in enumerate(group):
                ports[(c[0], c[1])] = y[k] + (i - (n - 1) / 2) * step

    def num(v):
        return f"{v:.1f}".rstrip("0").rstrip(".")

    def curve(x1, y1, x2, y2):
        mx = (x1 + x2) / 2
        return f" C{num(mx)},{num(y1)} {num(mx)},{num(y2)} {num(x2)},{num(y2)}"

    for a, b, chain in chains:
        px, py = lx[a] + BOX_W, out_port[(a, b)]
        d = f"M{num(px)},{num(py)}"
        for k in chain[1:-1]:
            d += curve(px, py, lx[k], y[k]) + f" L{num(lx[k] + BOX_W)},{num(y[k])}"
            px, py = lx[k] + BOX_W, y[k]
        d += curve(px, py, lx[b] - 1, in_port[(a, b)])
        result["edges"].append({"from": a, "to": b, "d": d})
    for a, b in back:
        x1, y1, x2, y2 = lx[a] + BOX_W, y[a], lx[b], y[b]
        d = f"M{num(x1)},{num(y1)} C{num(x1 + 60)},{num(y1 + 60)} {num(x2 - 60)},{num(y2 + 60)} {num(x2 - 1)},{num(y2)}"
        result["edges"].append({"from": a, "to": b, "d": d, "back": True})

    for k in nodes:
        result["nodes"].append({"key": k, "x": round(lx[k], 1), "y": round(y[k] - BOX_H / 2, 1),
                                "short": shorten(E[k]["name"], 12.4)})
    result["width"] = int(MARGIN * 2 + n_layers * BOX_W + (n_layers - 1) * GAP_X)
    result["height"] = int(max(y[k] + h(k) / 2 for k in y) + MARGIN)
    return result


# ---------- 汇总 ----------

def product_info(root, tree_path):
    head = next((c for c in root.children if c.level == 1), None)
    name = ""
    if head:
        t = plain(head.title)
        m = re.match(r"^(?:产品树|功能树)\s*[：:]\s*(.+)$", t)
        if m:
            name = m.group(1).strip()
        elif t not in ("产品树", "功能树", "产品", "功能清单"):
            name = t
    if not name:
        d = tree_path.resolve().parent
        if d.name.lower() in ("docs", "doc") or d.name == tree_path.stem:
            d = d.parent
        name = d.name

    def find(sec):
        for c in sec.children:
            if c.branch == "product":
                return c
            r = find(c)
            if r:
                return r
        return None

    prod = find(root)
    src = prod.lines if prod else (head.lines if head else root.lines)
    return name, first_paragraph(src)


def ser(sec, with_children=True):
    return {
        "title": sec.title, "level": sec.level, "branch": sec.branch,
        "line": sec.line.no if sec.line else 0, "blocks": sec.blocks, "nodes": sec.node_keys,
        "children": [ser(c) for c in sec.children if c.node is None] if with_children else [],
    }


def tops_of(root):
    tops = []
    if root.blocks:
        tops.append({"title": "", "level": 0, "branch": "head", "line": 0, "blocks": root.blocks,
                     "nodes": [], "children": []})
    for c in root.children:
        if c.level == 1 and c.branch == "head":
            tops.append(ser(c, False))
            tops.extend(ser(cc) for cc in c.children if cc.node is None)
        else:
            tops.append(ser(c))
    return tops


def stats_of(tree):
    E, order = tree.entries, tree.order
    feats = [k for k in order if E[k]["kind"] == "功能"]
    counts = {}
    for k in feats:
        key = (E[k]["statusLabel"], E[k]["statusClass"])
        counts[key] = counts.get(key, 0) + 1
    rank = {cls: i for i, (_, cls) in enumerate(STATUS_CLASSES)}
    by_status = sorted(counts.items(), key=lambda kv: (rank.get(kv[0][1], 90 if kv[0][1] != "none" else 99)))
    flows = [k for k in order if E[k]["kind"] == "任务流程"]
    broken = 0
    for k in flows:
        steps = tree.tables[E[k]["table"]].get("steps")
        if steps and any(s["broken"] for s in steps[E[k]["row"]]):
            broken += 1
    merge_tables = [t for t in tree.tables if t["branch"] == "merge"]
    with_target = [t for t in merge_tables if col_index(t["columns"], "合并到") >= 0]
    pending, rows = 0, 0
    for t in (with_target or merge_tables):
        sc = col_index(t["columns"], "状态")
        for r in t["rows"]:
            rows += 1
            st = plain(r[sc]) if sc >= 0 else ""
            if (with_target and "已合并" not in st) or (not with_target and not st.startswith("已")):
                pending += 1
    return {
        "features": len(feats), "subFeatures": sum(1 for k in feats if E[k]["parent"]),
        "byStatus": [{"label": lb, "cls": cls, "count": n} for (lb, cls), n in by_status],
        "pages": sum(1 for k in order if E[k]["kind"] == "页面"),
        "flows": len(flows), "brokenFlows": broken,
        "mergeRows": rows, "pendingMerge": pending,
    }


def summary_line(st):
    parts = []
    if st["features"]:
        detail = "、".join(f"{b['label']} {b['count']}" for b in st["byStatus"])
        sub = f"，含子功能 {st['subFeatures']} 个" if st["subFeatures"] else ""
        parts.append(f"功能 {st['features']} 个（{detail}{sub}）")
    parts.append(f"页面 {st['pages']} 个")
    flows = f"任务流程 {st['flows']} 条"
    if st["brokenFlows"]:
        flows += f"（{st['brokenFlows']} 条有断开的步骤）"
    parts.append(flows)
    parts.append(f"待合并 {st['pendingMerge']} 条未合并")
    return "，".join(parts)


HEAD_NAMES = ("核心功能", "扩展功能", "界面与交互", "页面", "页面布局", "任务流程", "交互模式",
              "使用者", "待合并", "重复做法", "找活面残留")
DRAW_KINDS = ("功能", "页面", "页面布局", "任务流程", "交互模式")
TIP_COL = {"页面": "回答什么问题", "任务流程": "要做成什么", "页面布局": "结构", "交互模式": "做法"}
PATH_TOKEN = re.compile(r"(?<![\w/])(/[A-Za-z0-9_.:~-]+)")
PARAM = re.compile(r":[A-Za-z_]\w*")


def one_line(text, n):
    s = re.sub(r"\s+", " ", plain(text or "")).strip()
    if len(s) > n:
        return s[:n] + "…"
    return s


def first_sentence(text, n=60):
    s = re.sub(r"\s+", " ", plain(text or "")).strip()
    s = re.split(r"[。！？!?]", s, 1)[0].strip()
    if len(s) > n:
        return s[:n] + "…"
    return s


def short_name(name, limit=8):
    raw = plain(name or "")
    s = re.sub(r"\s+", " ", strip_parens(raw)).strip()
    if not s:
        s = raw
    if text_em(s) <= limit:
        return s
    out = ""
    for ch in s:
        if text_em(out + ch) > limit - 1:
            break
        out += ch
    return (out or s[:1]) + "…"


def cell_of(tree, entry, col):
    if not col or entry.get("kind") == "功能" or "table" not in entry:
        return ""
    t = tree.tables[entry["table"]]
    i = col_index(t["columns"], col)
    if i < 0 or entry["row"] >= len(t["rows"]):
        return ""
    return t["rows"][entry["row"]][i]


def norm_path(p):
    p = (p or "").split("?", 1)[0].strip()
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return PARAM.sub(":*", p)


def path_score(raw, pat):
    a = norm_path(raw).split("/")
    b = pat.split("/")
    if len(b) < 2:
        return 0
    if len(a) == len(b) and all(x == y or x == ":*" or y == ":*" for x, y in zip(a, b)):
        return 3
    if len(a) > len(b) and all(x == y or y == ":*" or x == ":*" for x, y in zip(a[:len(b)], b)):
        return 1
    return 0


def page_index(tree):
    pages = []
    for k in tree.order:
        e = tree.entries[k]
        if e["kind"] != "页面":
            continue
        cell = cell_of(tree, e, "路径")
        raws = PATH_IN_CODE.findall(cell) or re.findall(r"(?<![\w/])(/[^\s、，,；;）)]*)", cell)
        norms = []
        for p in raws:
            n = norm_path(p)
            if n and n not in norms:
                norms.append(n)
        match = re.sub(r"\s+", " ", strip_parens(plain(e["name"]))).strip()
        pages.append({"id": k, "norms": norms, "match": match})
    return pages


def match_step_pages(text, pages):
    found, any_hit = [], False
    for raw in PATH_TOKEN.findall(text or ""):
        best_id, best_sc, best_len = None, 0, -1
        for pg in pages:
            for pat in pg["norms"]:
                sc = path_score(raw, pat)
                if sc > best_sc or (sc == best_sc and sc > 0 and len(pat) > best_len):
                    best_sc, best_len, best_id = sc, len(pat), pg["id"]
        if best_sc > 0 and best_id:
            any_hit = True
            if best_id not in found:
                found.append(best_id)
    if any_hit:
        return found
    t = plain(text or "")
    cands = []
    for pg in pages:
        nm = pg["match"]
        if len(nm) < 2:
            continue
        start = 0
        while True:
            i = t.find(nm, start)
            if i < 0:
                break
            cands.append((i, i + len(nm), pg["id"]))
            start = i + len(nm)
    cands.sort(key=lambda c: (c[0], -(c[1] - c[0])))
    taken = []
    for a, b, pid in cands:
        if any(not (b <= ta or a >= tb) for ta, tb, _pid in taken):
            continue
        taken.append((a, b, pid))
        if pid not in found:
            found.append(pid)
    return found


def collect_heads(sec, acc):
    if sec.line:
        t = plain(sec.title)
        for h in HEAD_NAMES:
            if t == h or t.startswith(h + "（") or t.startswith(h + "("):
                acc.setdefault(h, sec.line)
                break
    for c in sec.children:
        collect_heads(c, acc)


def loc_of(line):
    if not line:
        return {"file": "", "line": 0, "fileName": ""}
    return {"file": line.abspath, "line": line.no, "fileName": Path(line.abspath).name}


def status_of(entry):
    if entry.get("kind") != "功能":
        return "", "none"
    cls = entry.get("statusClass") or "none"
    label = entry.get("statusLabel") or ""
    if cls == "none" or label == NO_STATUS:
        return "", "none"
    if label == "未开始":
        cls = "planned"
    return label, cls


def clip_chars(text, n):
    s = re.sub(r"\s+", " ", plain(text or "")).strip()
    if len(s) <= n:
        return s
    return s[:n - 1] + "…"


def entry_parts(etype, rest):
    """一行一类。同类多个位置用「；」。接口行里多个反引号用「、」分开。叶子不要「→」后面。"""
    rest = re.split(r"\s*(?:→|->)\s*", rest or "", maxsplit=1)[0].strip()
    if etype == "接口":
        codes = [m.group(2).strip() for m in CODE_SPAN.finditer(rest)]
        if len(codes) >= 2:
            return [c for c in codes if c]
    return [p.strip() for p in re.split(r"[；;]", rest) if p.strip()]


def parse_entry_items(field):
    if not field:
        return []
    rows = []
    if field.get("value", "").strip():
        rows.append((field["value"], field.get("line") or 0))
    for ln in field.get("lines") or []:
        rows.append((ln.get("text") or "", ln.get("line") or field.get("line") or 0))
    out = []
    for raw, lineno in rows:
        text = re.sub(r"^[-*+]\s*", "", (raw or "").strip())
        m = re.match(r"^([^：:]{1,12})[：:]\s*(.*)$", text)
        if not m:
            continue
        etype, rest = m.group(1).strip(), m.group(2).strip()
        if not etype or etype == "入口":
            continue
        for part in entry_parts(etype, rest):
            shown = plain(part)
            if not shown or NONEISH.match(shown):
                continue
            out.append({"type": etype, "text": shown, "line": lineno})
    return out


def view_of(tree, data, editor, tree_path):
    """页面只拿这些画图。不放字段原文，页面排不出文档。"""
    E = tree.entries
    pages = page_index(tree)
    page_by = {p["id"]: p for p in pages}

    def file_of(entry):
        ap = entry.get("abspath") or ""
        return ap, entry.get("line") or 0, (Path(ap).name if ap else "")

    def pack(nid, kind, label, **kw):
        node = {
            "id": nid, "kind": kind, "label": label,
            "status": kw.get("status") or "",
            "statusClass": kw.get("statusClass") or "none",
            "file": kw.get("file") or "",
            "line": kw.get("line") or 0,
            "fileName": kw.get("fileName") or "",
            "tip": kw.get("tip") or "",
            "entryType": kw.get("entryType") or "",
            "broken": bool(kw.get("broken")),
            "link": kw.get("link") or "",
            "src": kw.get("src") or "",
            "find": kw.get("find") or "",
            "kids": kw.get("kids") or [],
        }
        return node

    def link_to(target, prefix):
        e = E.get(target)
        if not e:
            return None
        ap, line, fn = file_of(e)
        short = short_name(e.get("name") or target)
        label = target if target == short else (target + " " + short)
        st, sc = status_of(e) if e.get("kind") == "功能" else ("", "none")
        return pack(prefix + ":" + target, "链接", label, status=st, statusClass=sc,
                    file=ap, line=line, fileName=fn, link=target, find=target + " " + (e.get("name") or ""))

    def dup_leaves(entry):
        out = []
        for did in entry.get("dups") or []:
            d = E.get(did)
            if not d:
                continue
            st = plain(d.get("status") or "")
            if "已合并" in st or "已清" in st:
                continue
            what = clip_chars(cell_of(tree, d, "同一件事") or d.get("name") or did, 16)
            ap, line, fn = file_of(d)
            out.append(pack("hang:" + entry["id"] + ":" + did, "重复做法", did + " " + what,
                            file=ap, line=line, fileName=fn, src=did, find=did + " " + what,
                            statusClass="dup"))
        return out

    def entry_leaves(entry):
        field = next((f for f in entry.get("fields") or [] if f["name"] == "入口"), None)
        out = []
        for i, item in enumerate(parse_entry_items(field)):
            label = clip_chars(item["type"] + " · " + item["text"], 24)
            ap, _, fn = file_of(entry)
            out.append(pack("in:" + entry["id"] + ":" + str(i), "入口", label,
                            file=ap, line=item["line"], fileName=fn, entryType=item["type"],
                            tip=clip_chars(item["text"], 60), find=item["type"] + " " + item["text"]))
        return out

    impl_split = re.compile(r"\s*\+\s*|[、；;]")
    impl_token = re.compile(r"[A-Za-z][A-Za-z0-9_:.-]*")

    def impl_leaves(entry):
        """「核心实现」字段里的模块路径，一个实现挂一个叶子。"""
        field = next((f for f in entry.get("fields") or [] if f["name"] == "核心实现"), None)
        if not field:
            return []
        text = " ".join([field.get("value") or ""] +
                        [ln.get("text") or "" for ln in field.get("lines") or []])
        names = []
        for part in impl_split.split(text):
            m = impl_token.search(part)
            if not m:
                continue
            tok = m.group(0).strip(".-")
            if len(tok) < 6 or ("::" not in tok and "-" not in tok):
                continue
            if tok not in names:
                names.append(tok)
        ap, _, fn = file_of(entry)
        out = []
        for i, p in enumerate(names[:4]):
            out.append(pack("impl:" + entry["id"] + ":" + str(i), "实现", p,
                            file=ap, line=field.get("line") or 0, fileName=fn,
                            tip="核心实现：" + p, find=p))
        return out

    def feature_node(entry):
        ap, line, fn = file_of(entry)
        kind = "子功能" if entry.get("parent") else "功能"
        st, sc = status_of(entry)
        tip = first_sentence(entry.get("effect") or "")
        if not tip:
            f = next((f for f in entry.get("fields") or [] if f["name"] == "效果"), None)
            tip = first_sentence(field_text(f) if f else "")
        kids = []
        for cid in entry.get("children") or []:
            child = E.get(cid)
            if child:
                kids.append(feature_node(child))
        kids.extend(entry_leaves(entry))
        kids.extend(impl_leaves(entry))
        kids.extend(dup_leaves(entry))
        name = entry.get("name") or entry["id"]
        return pack(entry["id"], kind, entry["id"] + " " + short_name(name),
                    status=st, statusClass=sc, file=ap, line=line, fileName=fn, tip=tip,
                    find=entry["id"] + " " + name, kids=kids)

    def page_node(entry):
        ap, line, fn = file_of(entry)
        eid = entry.get("id") or entry.get("key")
        name = entry.get("name") or eid
        kids = []
        for fid in entry.get("pageFeatures") or []:
            lk = link_to(fid, "lp:" + eid)
            if lk:
                kids.append(lk)
        kids.extend(dup_leaves(entry))
        shown = short_name(name) if eid == name else (eid + " " + short_name(name))
        return pack(eid, "页面", shown, file=ap, line=line, fileName=fn,
                    tip=first_sentence(cell_of(tree, entry, "回答什么问题")),
                    find=eid + " " + name, kids=kids)

    def layout_node(entry):
        ap, line, fn = file_of(entry)
        name = entry.get("name") or entry["id"]
        kids = []
        for pid in entry.get("layoutPages") or []:
            lk = link_to(pid, "ll:" + entry["id"])
            if lk:
                kids.append(lk)
        kids.extend(dup_leaves(entry))
        return pack(entry["id"], "布局", entry["id"] + " " + short_name(name),
                    file=ap, line=line, fileName=fn,
                    tip=first_sentence(cell_of(tree, entry, "结构")),
                    find=entry["id"] + " " + name, kids=kids)

    def circled(n):
        if isinstance(n, int) and 1 <= n <= 20:
            return chr(0x2460 + n - 1)
        return str(n or "")

    def flow_node(entry):
        ap, line, fn = file_of(entry)
        name = entry.get("name") or entry["id"]
        steps_raw = []
        if "table" in entry:
            t = tree.tables[entry["table"]]
            got = t.get("steps") or []
            if entry["row"] < len(got):
                steps_raw = got[entry["row"]]
        kids, broken = [], False
        for i, s in enumerate(steps_raw):
            tx = s.get("text") or ""
            is_broken = bool(s.get("broken"))
            if is_broken:
                broken = True
            pids = match_step_pages(tx, pages)
            n = s.get("n") or (i + 1)
            if pids and page_by.get(pids[0]):
                pg = E.get(pids[0])
                bit = short_name(pg.get("name") or pids[0]) if pg else pids[0]
            else:
                bit = clip_chars(plain(tx), 8)
            mark = "✕ " if is_broken else ""
            label = (mark + circled(n) + " " + bit).strip()
            kids.append(pack("step:" + entry["id"] + ":" + str(n), "步骤", label,
                            file=ap, line=line, fileName=fn, broken=is_broken,
                            statusClass="dup" if is_broken else "none",
                            tip=one_line(tx, 80), find=plain(tx)))
        uses = []
        for uid in entry.get("uses") or []:
            lk = link_to(uid, "lu:" + entry["id"])
            if lk:
                uses.append(lk)
        if uses:
            kids.append(pack("uses:" + entry["id"], "分枝", "用到的功能", kids=uses,
                            file=ap, line=line, fileName=fn))
        return pack(entry["id"], "流程", entry["id"] + " " + short_name(name),
                    file=ap, line=line, fileName=fn, broken=broken,
                    tip=first_sentence(cell_of(tree, entry, "要做成什么")),
                    find=entry["id"] + " " + name + " " + plain(cell_of(tree, entry, "谁")),
                    kids=kids)

    def mode_node(entry):
        ap, line, fn = file_of(entry)
        name = entry.get("name") or entry["id"]
        return pack(entry["id"], "交互模式", entry["id"] + " " + short_name(name),
                    file=ap, line=line, fileName=fn,
                    tip=first_sentence(cell_of(tree, entry, "做法")),
                    find=entry["id"] + " " + name, kids=dup_leaves(entry))

    def branch(bid, label, kids, line=None):
        kw = {}
        if line:
            kw = {"file": line.abspath, "line": line.no, "fileName": Path(line.abspath).name}
        return pack(bid, "分枝", label, kids=[k for k in kids if k], **kw)

    groups = {"核心功能": [], "扩展功能": [], "页面": [], "页面布局": [], "任务流程": [], "交互模式": []}
    for k in tree.order:
        e = E[k]
        if e["kind"] == "功能" and not e.get("parent"):
            groups["核心功能" if e["branch"] == "core" else "扩展功能"].append(feature_node(e))
        elif e["kind"] == "页面":
            groups["页面"].append(page_node(e))
        elif e["kind"] == "页面布局":
            groups["页面布局"].append(layout_node(e))
        elif e["kind"] == "任务流程":
            groups["任务流程"].append(flow_node(e))
        elif e["kind"] == "交互模式":
            groups["交互模式"].append(mode_node(e))

    def table_rows(t):
        rows = []
        sc = col_index(t["columns"], "状态")
        what_i = col_index(t["columns"], "同一件事")
        if what_i < 0:
            what_i = col_index(t["columns"], "对象")
        merge_i = col_index(t["columns"], "合并到")
        for ri, key in enumerate(t["keys"]):
            if not key:
                continue
            e = E.get(key)
            cells = t["rows"][ri]
            st = plain(cells[sc]) if sc >= 0 and sc < len(cells) else ""
            done = ("已合并" in st) or ("已清" in st)
            what = ""
            if what_i >= 0 and what_i < len(cells):
                what = clip_chars(cells[what_i], 16)
            if not what and e:
                what = short_name(e.get("name") or "")
            label = (key + " " + what).strip()
            ap = t["rowFile"][ri] if ri < len(t.get("rowFile") or []) else ""
            lineno = t["rowLine"][ri] if ri < len(t.get("rowLine") or []) else 0
            kids = []
            if merge_i >= 0 and merge_i < len(cells):
                for tok in dict.fromkeys(m.group(0) for m in ID_LIKE.finditer(strip_parens(cells[merge_i]))):
                    if tok in E:
                        lk = link_to(tok, "lm:" + key)
                        if lk:
                            kids.append(lk)
            rows.append(pack(key, "待合并行", label, file=ap, line=lineno,
                            fileName=Path(ap).name if ap else "",
                            statusClass="none" if done else "dup",
                            tip=clip_chars(st, 40), find=key + " " + what + " " + st, kids=kids, src=key))
        return rows

    merge_nodes = []
    merge_tables = [t for t in tree.tables if t["branch"] == "merge"]
    named = [t for t in merge_tables if t.get("heading") and t["heading"] not in ("待合并", "")]
    if len(merge_tables) > 1 or named:
        for t in merge_tables:
            title = t.get("heading") or "待合并"
            if title == "待合并":
                merge_nodes.extend(table_rows(t))
            else:
                merge_nodes.append(branch("b:" + title, title, table_rows(t),
                                          tree.heads.get(title)))
    else:
        for t in merge_tables:
            merge_nodes.extend(table_rows(t))

    role_nodes = []
    for t in tree.tables:
        if t.get("heading") != "使用者":
            continue
        ri_role = col_index(t["columns"], "角色")
        if ri_role < 0:
            ri_role = 0
        ri_do = col_index(t["columns"], "要做成的事")
        if ri_do < 0:
            ri_do = col_index(t["columns"], "要做成什么")
        for ri, cells in enumerate(t["rows"]):
            role = plain(cells[ri_role]) if ri_role < len(cells) else ""
            if not role or role in ("角色", "—"):
                continue
            tip = first_sentence(cells[ri_do]) if ri_do >= 0 and ri_do < len(cells) else ""
            ap = t["rowFile"][ri] if ri < len(t.get("rowFile") or []) else ""
            lineno = t["rowLine"][ri] if ri < len(t.get("rowLine") or []) else 0
            role_nodes.append(pack("role:" + str(ri) + ":" + role, "角色", short_name(role, 12) or role,
                                   file=ap, line=lineno, fileName=Path(ap).name if ap else "",
                                   tip=tip, find=role))
        break

    deps = []
    seen = set()
    for k in tree.order:
        e = E[k]
        if e["kind"] != "功能":
            continue
        for d in e.get("deps") or []:
            if d in E and d != k and (d, k) not in seen:
                seen.add((d, k))
                deps.append([d, k])

    counts = {}
    for k in tree.order:
        e = E[k]
        if e["kind"] != "功能" or e.get("parent"):
            continue
        label, cls = status_of(e)
        if not label:
            label, cls = "没写状态", "none"
        counts[(label, cls)] = counts.get((label, cls), 0) + 1
    rank = {c: i for i, (_, c) in enumerate(STATUS_CLASSES)}
    by_status = [{"label": lb, "cls": c, "count": n} for (lb, c), n in sorted(
        counts.items(), key=lambda kv: rank.get(kv[0][1], 90))]

    l1 = []
    if role_nodes:
        l1.append(branch("b:使用者", "使用者", role_nodes, tree.heads.get("使用者")))
    if groups["核心功能"]:
        l1.append(branch("b:核心功能", "核心功能", groups["核心功能"], tree.heads.get("核心功能")))
    if groups["扩展功能"]:
        l1.append(branch("b:扩展功能", "扩展功能", groups["扩展功能"], tree.heads.get("扩展功能")))
    ui = []
    for name in ("页面", "页面布局", "任务流程", "交互模式"):
        if groups[name]:
            ui.append(branch("b:" + name, name, groups[name], tree.heads.get(name)))
    if ui:
        l1.append(branch("b:界面与交互", "界面与交互", ui, tree.heads.get("界面与交互")))
    if merge_nodes:
        l1.append(branch("b:待合并", "待合并", merge_nodes, tree.heads.get("待合并")))

    h1 = loc_of(getattr(tree, "h1", None))
    root = pack("root", "分枝", data["meta"]["name"], kids=l1, **h1)
    st = data["stats"]
    return {
        "name": data["meta"]["name"],
        "editor": editor or "none",
        "file": slash(tree_path),
        "stats": {"byStatus": by_status, "dupRows": st["pendingMerge"], "brokenFlows": st["brokenFlows"]},
        "root": root,
        "deps": deps,
    }


def parse(tree_path):
    lines, files = load(tree_path)
    root = sectionize(lines)
    assign_branches(root)
    tree = Tree()
    root.blocks = tree.blocks(root)
    tree.walk(root)
    edges = build(tree)
    graph = layout_graph(tree.entries, tree.order, edges)
    for cyc in graph["cycles"]:
        e = tree.entries[cyc[0]]
        tree.note("提醒", e["file"], e["line"], "依赖成环：" + " → ".join(cyc))
    name, desc = product_info(root, tree_path)
    tree.heads = {}
    collect_heads(root, tree.heads)
    h1 = next((c for c in root.children if c.level == 1 and c.line), None)
    tree.h1 = h1.line if h1 else None
    data = {
        "meta": {"name": name, "description": desc, "files": [shown(f) for f in files],
                 "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")},
        "stats": stats_of(tree),
        "tops": tops_of(root),
        "tables": tree.tables,
        "entries": tree.entries,
        "order": tree.order,
        "edges": edges,
        "graph": graph,
    }
    tree.problems.sort(key=lambda p: (p["level"] != "问题", p["file"], p["line"]))
    return data, tree.problems, tree


def write_html(view, out_path):
    template_path = Path(__file__).resolve().parent / "viewer.html"
    if not template_path.is_file():
        sys.exit(f"找不到页面模板 {template_path}，它应该和 render.py 放在同一个目录。")
    template = template_path.read_text(encoding="utf-8")
    payload = json.dumps(view, ensure_ascii=False, separators=(",", ":"))
    payload = (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    page = template.replace("__TITLE__", html.escape((view.get("name") or "") + " 产品树"), 1)
    page = page.replace("__TREE_DATA__", payload, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


def print_problems(problems):
    for level in ("问题", "提醒"):
        items = [p for p in problems if p["level"] == level]
        if items:
            print(f"{level}（{len(items)} 条）：")
            for p in items:
                print(f"  {p['file']}:{p['line']}  {p['msg']}")


def main():
    ap = argparse.ArgumentParser(description="从产品树文件生成一张图，或检查编号。")
    ap.add_argument("tree", help="树文件，例如 docs/product-tree.md")
    ap.add_argument("-o", "--output", help="输出的 HTML 文件；不给时写到树文件同目录、同名 .html")
    ap.add_argument("--check", action="store_true", help="只检查，不生成页面；有问题时退出码 1")
    ap.add_argument("--editor", choices=("none", "cursor", "vscode"), default="none",
                    help="点击条目时：none 复制位置（默认），cursor 或 vscode 跳到那一行")
    args = ap.parse_args()

    tree_path = Path(args.tree)
    if not tree_path.is_file():
        sys.exit(f"找不到树文件：{args.tree}")
    data, problems, tree = parse(tree_path)
    n_err = sum(1 for p in problems if p["level"] == "问题")
    n_warn = len(problems) - n_err

    if args.check:
        print(summary_line(data["stats"]))
        print_problems(problems)
        print(f"检查完：问题 {n_err} 条，提醒 {n_warn} 条。")
        sys.exit(1 if n_err else 0)

    out = Path(args.output) if args.output else tree_path.with_suffix(".html")
    write_html(view_of(tree, data, args.editor, tree_path), out)
    print(f"{summary_line(data['stats'])}；已写到 {shown(out.resolve())}")
    if not args.output:
        print("生成的文件不要提交：放进 .gitignore，或用 -o 写到忽略的目录。")
    print(f"问题 {n_err} 条，提醒 {n_warn} 条" + ("（加 --check 看明细）" if problems else ""))


if __name__ == "__main__":
    main()
