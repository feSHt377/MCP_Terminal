"""Agent 命令聚合校验。

Agent 倾向于把多条命令用 ``;``/``&&``/``||`` 串成一条、或用 heredoc 内嵌
多行脚本后一次性提交。这样 GUI 终端只能看到一大段混合输出，用户无法逐步
观察执行过程，失败时也难以定位出错步骤。本模块在工具层拦截这类「高聚合」
命令，返回带教学信息的错误，引导 Agent 拆成多次单命令调用。

扫描是带引号/转义/``$( )`` 子 shell 感知的启发式解析，不是完整 shell 解析
器；设计取向是宁可对花哨写法误拒（可拆分重试），也不放过真实聚合。
"""

from __future__ import annotations

from typing import Any

# 顶层命令连接符（; && || 及连接式后台 &）最多允许的数量。
# 保留 1 个是为了放行 `cd <目录> && <命令>` 这类单目的形式——
# 每次执行都是全新进程，cd 不会跨调用持久，没有它无法在指定目录执行。
MAX_CONNECTORS = 1


def _scan(command: str) -> dict[str, Any]:
    """扫描命令，返回聚合特征（引号外的顶层结构才计入）。"""
    stripped = command.strip()
    result: dict[str, Any] = {
        "multiline": False,
        "heredoc": False,
        "connectors": [],  # 顶层 ; && || & 连接符，按出现顺序
        "pipes": 0,
        "background": False,  # 末尾 & 后台运行（单命令后台，允许）
    }
    if not stripped:
        return result

    if "\n" in stripped or "\r" in stripped:
        result["multiline"] = True

    n = len(stripped)
    i = 0
    in_single = False
    in_double = False
    in_backtick = False
    depth = 0  # $( ) 命令替换嵌套深度

    while i < n:
        ch = stripped[i]

        # 单引号内一切字面，只关心闭合引号
        if in_single:
            if ch == "'":
                in_single = False
            i += 1
            continue

        # 反斜杠转义（双引号内外一致地吞掉下一个字符）
        if not in_backtick and ch == "\\":
            i += 2
            continue

        if in_double:
            if ch == '"':
                in_double = False
            elif ch == "$" and i + 1 < n and stripped[i + 1] == "(":
                depth += 1
                i += 2
                continue
            i += 1
            continue

        if in_backtick:
            if ch == "`":
                in_backtick = False
            i += 1
            continue

        two = stripped[i : i + 2]

        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "`":
            in_backtick = True
            i += 1
            continue
        if ch == "$" and two == "$(":
            depth += 1
            i += 2
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            i += 1
            continue

        if depth > 0:
            i += 1
            continue

        # ---- 以下均为顶层未加引号字符 ----
        if two == "&&":
            result["connectors"].append("&&")
            i += 2
            continue
        if two == "||":
            result["connectors"].append("||")
            i += 2
            continue
        if ch == ";":
            result["connectors"].append(";")
            i += 1
            continue
        if ch == "|":
            if i + 1 < n and stripped[i + 1] == "&":  # |& 管道 stderr
                result["pipes"] += 1
                i += 2
                continue
            result["pipes"] += 1
            i += 1
            continue
        if ch == "&":
            if i + 1 < n and stripped[i + 1] == "&":  # 已在上面 && 分支捕获，兜底
                result["connectors"].append("&&")
                i += 2
                continue
            if i + 1 < n and stripped[i + 1] == ">":  # &> 重定向
                i += 2
                continue
            if i > 0 and stripped[i - 1] == ">":  # >& 重定向（如 2>&1）
                i += 1
                continue
            if stripped[i + 1 :].strip():  # 后面还有命令 → 连接式后台
                result["connectors"].append("&")
            else:
                result["background"] = True
            i += 1
            continue
        if two == "<<":
            if i + 2 < n and stripped[i + 2] == "<":  # <<< here-string，单行
                i += 3
                continue
            result["heredoc"] = True
            i += 2
            continue
        i += 1

    return result


def check_agent_command(command: str) -> dict[str, Any] | None:
    """校验 Agent 提交的命令是否为高聚合命令。

    返回 None 表示允许执行；否则返回::

        {"reason": "aggregated_command", "issues": [...], "message": ...}
    """
    scan = _scan(command)
    issues: list[str] = []

    if scan["multiline"]:
        issues.append("多行命令（含换行）")
    if scan["heredoc"]:
        issues.append("heredoc（<<）多行输入")
    connectors = scan["connectors"]
    if len(connectors) > MAX_CONNECTORS:
        unique = " ".join(dict.fromkeys(connectors))
        issues.append(f"{len(connectors)} 个命令连接符（{unique}）")

    if not issues:
        return None

    message = (
        f"命令被拒绝：{'、'.join(issues)}，属于高聚合命令。\n"
        "原因：把多条命令塞进一次调用，用户在终端上只能看到一大段混合输出，"
        "无法逐步观察执行过程，失败时也难以定位出错步骤。\n"
        "正确做法：\n"
        "  1. 每次 ssh_exec/proxy_command 只提交一条命令，等本次结果返回后再"
        "决定下一条；连接符至多 1 个（如 cd <目录> && <命令>）。\n"
        "  2. 需要运行多行脚本时，先用 upload_file 上传脚本文件，再用单行命令执行。\n"
        "  3. 管道（a | b）和单命令后台（cmd &）不受影响，可正常使用。"
    )
    return {
        "reason": "aggregated_command",
        "issues": issues,
        "message": message,
    }
