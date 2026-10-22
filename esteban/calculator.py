"""Calculator.

Alfred evaluates expressions with GCMathParser (REA evidence:
+[GCMathParser evaluate:], "Evaluated %@ to %@", "Expression failed to evaluate",
features.calculator.* for input/output formatting, and `.copytoclipboard`).
This module implements a safe equivalent: arithmetic, unary minus, parentheses,
^ and common functions, evaluated via an AST whitelist.
"""
from __future__ import annotations

import ast
import math
import operator

OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "exp": math.exp, "abs": abs,
    "round": round, "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "e": math.e,
}


def evaluate(expr: str, decimal_separator: str = ".") -> float | int | None:
    if not expr:
        return None
    text = expr.replace(decimal_separator, ".") if decimal_separator != "." else expr
    # Alfred's calculator is a math parser, not a Python evaluator: restrict nodes.
    try:
        tree = ast.parse(text.replace("^", "**"), mode="eval")
    except SyntaxError:
        return None
    return _eval(tree.body)


def _eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("bad constant")
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise ValueError("bad call")
        return FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in FUNCS:
            return FUNCS[node.id]
        raise ValueError("bad name")
    raise ValueError("bad node")


def format_result(value, show_thousands: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = f"{value:,}" if show_thousands else str(value)
    return s
