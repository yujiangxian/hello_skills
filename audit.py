#!/usr/bin/env python3
"""产品树的实现就绪检查。

`render.py --check` 只保证编号引用不断；这个脚本检查的是
「照这棵树能不能把前端做完整」：

- 功能节点有没有验收标准，验收是不是可观察的
- 页面有没有写数据来源和加载/空/错误三态
- 每个接口有没有契约，前后端字段名从哪来
- 功能入口和页面表是否闭环（有页面没入口、有入口没页面）
- 数据源里的表有没有界面入口（数据产生了但看不见）
- 枚举值有没有登记使用点（加一个实体类型，前端映射漏掉）
- 导航和页面表的菜单位置是否一致

用法：
    python audit.py docs/product-tree.md
    python audit.py docs/product-tree.md --strict   # 提醒也算失败

退出码：有「问题」时 1；--strict 时提醒也返回 1。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 功能节点必须写全的字段。界面/入口可以写「无」，但字段本身要在。
FEATURE_FIELDS = ["效果", "数据源", "核心实现", "界面", "入口", "验收", "状态"]
# 页面表必须有的列。
PAGE_COLUMNS = ["页面", "路径", "给谁用", "回答什么问题", "布局", "菜单位置", "数据", "状态"]
# 页面规格每一节必须覆盖的状态。
PAGE_STATES = ["加载", "空", "错误"]
# 验收里出现这些词说明写得不可观察。
VAGUE_WORDS = [
    "体验好", "体验流畅", "功能完整", "功能完善", "正常运行", "稳定运行",
    "友好", "流畅", "合理", "美观", "完善", "良好",
]

problems = []


def note(level, file, line, msg):
    problems.append({"level": level, "file": str(file), "line": line, "msg": msg})


def problem(file, line, msg):
    note("问题", file, line, msg)


def warn(file, line, msg):
    note("提醒", file, line, msg)


def cell(entry, tree, column):
    """按列名取表格里这一行的单元格。列不存在时返回 None。"""
    table = tree.tables[entry["table"]]
    index = render.col_index(table["columns"], column)
    if index < 0:
        return None
    cells = table["rows"][entry["row"]]
    return render.plain(cells[index]) if index < len(cells) else ""


def raw_cell(entry, tree, column):
    """保留反引号的单元格原文。接口和字段名都在反引号里。"""
    table = tree.tables[entry["table"]]
    index = render.col_index(table["columns"], column)
    if index < 0:
        return None
    cells = table["rows"][entry["row"]]
    return cells[index] if index < len(cells) else ""


def field_map(entry):
    return {f["name"]: f for f in entry.get("fields") or []}


def field_body(entry, name):
    f = field_map(entry).get(name)
    return render.field_text(f) if f else ""


def entries_of(tree, kind):
    return [tree.entries[k] for k in tree.order if tree.entries[k]["kind"] == kind]


def table_rows(tree, kind):
    """按表格类型取行。导航、枚举、用词表第一列不是编号，不会进 entries。"""
    out = []
    for table in tree.tables:
        if table["kind"] != kind:
            continue
        for index, cells in enumerate(table["rows"]):
            out.append({
                "file": table["file"],
                "line": table["rowLine"][index],
                "columns": table["columns"],
                "cells": cells,
            })
    return out


def row_cell(row, column):
    index = render.col_index(row["columns"], column)
    if index < 0 or index >= len(row["cells"]):
        return ""
    return render.plain(row["cells"][index])


def backticked(text):
    return [m.group(1).strip() for m in re.finditer(r"`([^`]+)`", text or "")]


def page_paths(text):
    """从一段文字里取页面路径：反引号里的 /xxx，排除 /api/ 开头的接口。"""
    out = []
    for token in backticked(text):
        if token.startswith("/api/"):
            continue
        if re.fullmatch(r"/[A-Za-z0-9\-_/{}:.]*", token):
            out.append(token)
    return out


def api_paths(text):
    """入口里可能写成 `GET /api/x`，也可能只写路径。"""
    out = []
    for token in backticked(text):
        match = re.match(r"^(?:GET|POST|PUT|DELETE|PATCH|WS|WebSocket)\s+(/api/\S+)$", token)
        path = match.group(1) if match else token
        if path.startswith("/api/"):
            out.append(path)
    return out


# ---------------------------------------------------------------- 规格文件

def find_spec_file(tree_path, heading):
    """在 `### <heading>` 小节下找 `- 文件：<path>`。

    这一节只挂一个字段、不是表格，所以直接读原文，不走条目索引。
    """
    text = Path(tree_path).read_text(encoding="utf-8")
    pattern = rf"^###\s+{re.escape(heading)}\s*$(.*?)(?=^###\s|\Z)"
    section = re.search(pattern, text, re.M | re.S)
    if not section:
        return None
    field = re.search(r"^-\s*文件[：:]\s*(.+?)\s*$", section.group(1), re.M)
    if not field:
        return None
    value = field.group(1).strip()
    link = re.match(r"^\[([^\]]+)\]\([^)]*\)$", value)
    return link.group(1) if link else value


def read_spec(tree_file, relative):
    if not relative:
        return None
    path = Path(tree_file).parent.parent / relative
    if not path.is_file():
        path = Path(tree_file).parent / relative
    if not path.is_file():
        note("问题", tree_file, 0, f"规格文件不存在：{relative}")
        return None
    return path.read_text(encoding="utf-8")


def spec_sections(text):
    """按 `## 页面名` / `### 页面名` 切小节，返回 {名称: 正文}。"""
    out = {}
    current, buf = None, []
    for line in (text or "").splitlines():
        m = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if m:
            if current:
                out[current] = "\n".join(buf)
            current, buf = m.group(1).strip(), []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf)
    return out


# ---------------------------------------------------------------- 检查

def check_features(tree):
    for entry in entries_of(tree, "功能"):
        fields = field_map(entry)
        missing = [name for name in FEATURE_FIELDS if name not in fields]
        if missing:
            problem(entry["file"], entry["line"],
                    f"{entry['key']} {entry['name']} 缺字段：{'、'.join(missing)}")
            continue

        acceptance = field_body(entry, "验收").strip()
        if not acceptance:
            problem(entry["file"], entry["line"],
                    f"{entry['key']} 的「验收」是空的")
            continue

        items = [line.strip(" -•\t") for line in acceptance.splitlines()
                 if line.strip(" -•\t")]
        if len(items) < 2:
            warn(entry["file"], entry["line"],
                 f"{entry['key']} 只有 {len(items)} 条验收，至少写 2 条可观察的结果")
        for item in items:
            for word in VAGUE_WORDS:
                if word in item:
                    problem(entry["file"], entry["line"],
                            f"{entry['key']} 的验收「{item[:30]}」含不可观察的词「{word}」")


def check_pages(tree, page_spec):
    pages = entries_of(tree, "页面")
    if not pages:
        return []
    table = tree.tables[pages[0]["table"]]
    missing_cols = [c for c in PAGE_COLUMNS
                    if render.col_index(table["columns"], c) < 0]
    if missing_cols:
        problem(table["file"], table["line"],
                f"页面表缺列：{'、'.join(missing_cols)}"
                "（数据=这页读什么接口；状态=加载/空/错误怎么显示）")

    spec = spec_sections(page_spec)

    for entry in pages:
        name = cell(entry, tree, "页面") or entry["name"]
        path = cell(entry, tree, "路径") or ""
        data = cell(entry, tree, "数据")
        states = cell(entry, tree, "状态")

        if not path.strip():
            problem(entry["file"], entry["line"], f"页面「{name}」没有路径")
        if data is not None and not data.strip():
            problem(entry["file"], entry["line"],
                    f"页面「{name}」没有写「数据」：这页读哪些接口和字段")
        if states is not None and not states.strip():
            problem(entry["file"], entry["line"],
                    f"页面「{name}」没有写「状态」：加载/空/错误各显示什么")

        if page_spec is not None:
            body = spec.get(name)
            if body is None:
                problem(entry["file"], entry["line"],
                        f"页面「{name}」在页面规格里没有对应小节")
                continue
            for state in PAGE_STATES:
                if state not in body:
                    problem(entry["file"], entry["line"],
                            f"页面规格「{name}」没有写「{state}」状态")
    return pages


tree_path_holder = [""]


def check_api_contract(tree, contract, pages):
    defined = set()
    if contract:
        for line in contract.splitlines():
            m = re.match(r"^\|\s*`?(/api/[^`|\s]+)`?\s*\|", line)
            if m:
                defined.add(m.group(1))

    used = set()
    for entry in entries_of(tree, "功能"):
        for path in api_paths(field_body(entry, "入口")):
            used.add(path.split("?")[0])
            if contract is not None and path.split("?")[0] not in defined:
                problem(entry["file"], entry["line"],
                        f"{entry['key']} 的接口 `{path}` 没有写进接口契约")
    head_file = tree.h1.file if tree.h1 else str(tree_path_holder[0])
    head_line = tree.h1.no if tree.h1 else 0
    # 页面「数据」列引用的接口也算在用：页面是入口的呈现层。
    for entry in pages:
        for path in api_paths(raw_cell(entry, tree, "数据") or ""):
            used.add(path.split("?")[0])

    for path in defined - used:
        warn(head_file, head_line, f"接口契约里的 `{path}` 没有任何功能入口或页面在用")


def check_entry_pages(tree, pages):
    """功能入口提到的页面，页面表里要有；页面表里的页面，至少被一个入口提到。"""
    page_names = {cell(e, tree, "页面") or e["name"] for e in pages}
    mentioned = set()
    for entry in entries_of(tree, "功能"):
        body = field_body(entry, "入口")
        for name in page_names:
            if name and name in body:
                mentioned.add(name)
        for path in page_paths(body):
            matched = [n for n, e in
                       ((cell(e, tree, "页面") or e["name"], e) for e in pages)
                       if (cell(e, tree, "路径") or "") == path]
            if not matched:
                problem(entry["file"], entry["line"],
                        f"{entry['key']} 的入口写了页面 `{path}`，页面表里没有")
    for entry in pages:
        name = cell(entry, tree, "页面") or entry["name"]
        if name not in mentioned:
            warn(entry["file"], entry["line"],
                 f"页面「{name}」没有被任何功能入口引用：要么补入口，要么删页面")


def contract_table_map(contract):
    """接口契约的「涉及表」列 → {表名: {接口}}。"""
    mapping = {}
    for line in contract.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0].startswith("/api/"):
            continue
        for table in re.split(r"[、,，\s]+", cells[4]):
            table = table.strip().strip("`")
            if table:
                mapping.setdefault(table, set()).add(cells[0])
    return mapping


def check_data_visibility(tree, pages, page_spec, contract):
    """每张表至少有一个页面在通过接口读它。

    页面的「数据」列写接口，「涉及表」在接口契约里。两者都没有时无法判断，
    直接跳过——比报一堆假问题更有用。
    """
    if contract is None:
        return
    table_paths = contract_table_map(contract)
    if not table_paths:
        return

    visible_paths = set()
    for entry in pages:
        for path in api_paths(raw_cell(entry, tree, "数据") or ""):
            visible_paths.add(path.split("?")[0])
    if page_spec:
        for body in spec_sections(page_spec).values():
            for path in api_paths(body):
                visible_paths.add(path.split("?")[0])

    for entry in entries_of(tree, "功能"):
        for token in backticked(field_body(entry, "数据源")):
            if not re.fullmatch(r"[a-z_][a-z0-9_.]*", token):
                continue
            paths = table_paths.get(token)
            if paths is None:
                # 不是契约里登记过的表：可能是配置键、文件名或 source_id，
                # 这一层判断不了，交给人工核对。
                continue
            if not (paths & visible_paths):
                warn(entry["file"], entry["line"],
                     f"{entry['key']} 的数据源 `{token}` 没有任何页面在读"
                     "：数据产生了但看不见")


def check_glossary(tree, pages):
    """只核对会显示给用户的页面名。

    功能节点名是设计文档用词，不直接出现在界面上；对它们做子串匹配
    会把「情报捕获」这类合法命名全部误判。两字以内的禁用词只做完全匹配，
    避免「报告」「指标」这类本身也是合法概念的词互相误伤。
    """
    banned = {}
    for row in table_rows(tree, "用词"):
        words = row_cell(row, "不要叫")
        prefer = row_cell(row, "界面上叫") or row_cell(row, "概念")
        for word in re.split(r"[、,，/]", words):
            word = word.strip()
            if word:
                banned[word] = prefer

    for entry in pages:
        name = cell(entry, tree, "页面") or entry["name"]
        for word, prefer in banned.items():
            hit = name == word if len(word) <= 2 else word in name
            if hit:
                warn(entry["file"], entry["line"],
                     f"页面名「{name}」和用词表冲突：不要叫「{word}」，"
                     f"应该叫「{prefer}」。确认这是不是一个新概念")


def check_enums(tree):
    for row in table_rows(tree, "枚举"):
        name = row_cell(row, "枚举") or "（未命名）"
        values = row_cell(row, "取值")
        uses = row_cell(row, "用在哪")
        count = len([v for v in re.split(r"[、,，]", values) if v.strip()])
        use_count = len([u for u in re.split(r"[、,，；;]", uses) if u.strip()])
        if count == 0:
            problem(row["file"], row["line"], f"枚举「{name}」没有写取值")
        if use_count < 2:
            problem(row["file"], row["line"],
                    f"枚举「{name}」只登记了 {use_count} 个使用点；"
                    "取值变化时至少要在页面筛选和展示映射两处同步")


def check_nav(tree, pages):
    nav = {}
    for row in table_rows(tree, "导航"):
        top = row_cell(row, "一级")
        sub = row_cell(row, "二级")
        path = row_cell(row, "路径")
        if path:
            nav[path] = (top, sub)

    if not nav:
        head_file = tree.h1.file if tree.h1 else str(tree_path_holder[0])
        head_line = tree.h1.no if tree.h1 else 0
        warn(head_file, head_line,
             "没有「导航」表：页面的菜单位置无法和实际导航核对")
        return

    for entry in pages:
        name = cell(entry, tree, "页面") or entry["name"]
        path = (cell(entry, tree, "路径") or "").strip()
        if not path:
            continue
        where = (cell(entry, tree, "菜单位置") or "").strip()
        if where in ("—", "-"):
            # 详情页这类不常驻导航的页面明确标了「—」，不用出现在导航表。
            continue
        if not where:
            problem(entry["file"], entry["line"],
                    f"页面「{name}」的菜单位置为空；不进导航就写「—」")
            continue
        if path not in nav:
            problem(entry["file"], entry["line"],
                    f"页面「{name}」({path}) 的菜单位置是「{where}」，但导航表里没有这个路径")
            continue
        top, sub = nav[path]
        if where != top and where != sub:
            problem(entry["file"], entry["line"],
                    f"页面「{name}」的菜单位置写的是「{where}」，导航表里在「{top} / {sub}」")


# ---------------------------------------------------------------- 主流程

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    strict = "--strict" in sys.argv
    tree_path = Path(sys.argv[1])
    if not tree_path.is_file():
        print(f"找不到树文件：{tree_path}")
        return 2

    tree_path_holder[0] = str(tree_path)
    data, base_problems, tree = render.parse(tree_path)
    problems.extend(base_problems)

    page_spec_path = find_spec_file(tree_path, "页面规格")
    page_spec = read_spec(tree_path, page_spec_path) if page_spec_path else None
    contract_path = find_spec_file(tree_path, "接口契约")
    contract = read_spec(tree_path, contract_path) if contract_path else None

    check_features(tree)
    pages = check_pages(tree, page_spec)
    check_entry_pages(tree, pages)
    check_api_contract(tree, contract, pages)
    check_data_visibility(tree, pages, page_spec, contract)
    check_glossary(tree, pages)
    check_enums(tree)
    check_nav(tree, pages)

    problems.sort(key=lambda p: (p["level"] != "问题", p["file"], p["line"]))
    n_err = sum(1 for p in problems if p["level"] == "问题")
    n_warn = len(problems) - n_err

    print(render.summary_line(data["stats"]))
    for level in ("问题", "提醒"):
        items = [p for p in problems if p["level"] == level]
        if not items:
            continue
        print(f"\n{level}（{len(items)} 条）：")
        for p in items:
            where = f"{p['file']}:{p['line']}" if p["line"] else p["file"]
            print(f"  {where}  {p['msg']}")

    print(f"\n检查完：问题 {n_err} 条，提醒 {n_warn} 条。")
    return 1 if n_err or (strict and n_warn) else 0


if __name__ == "__main__":
    raise SystemExit(main())
