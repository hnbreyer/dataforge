"""Tiny arithmetic language interpreted as an AST; no eval, calls or attributes."""

import ast
from decimal import Decimal, DecimalException, localcontext

from dataforge.engines.values import Row, decimal_text, number
from dataforge.errors import InputError


class Expression:
    def __init__(self, text: str, columns: list[str]):
        if len(text) > 500:
            raise InputError("Expression is too long")
        try:
            self.tree = ast.parse(text, mode="eval")
        except (SyntaxError, RecursionError) as exc:
            raise InputError("Invalid arithmetic expression") from exc
        nodes = list(ast.walk(self.tree))
        if len(nodes) > 64:
            raise InputError("Expression exceeds 64 syntax nodes")
        allowed = (
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.UAdd,
            ast.USub,
            ast.Name,
            ast.Load,
            ast.Constant,
        )
        for node in nodes:
            if not isinstance(node, allowed):
                raise InputError(
                    "Expressions support only column names, numeric constants, +, -, *, / and parentheses"
                )
            if isinstance(node, ast.Name) and node.id not in columns:
                raise InputError(f"Unknown expression column: {node.id}")
            if isinstance(node, ast.Constant):
                literal = ast.get_source_segment(text, node)
                if (
                    isinstance(node.value, bool)
                    or not isinstance(node.value, (int, float))
                    or literal is None
                ):
                    raise InputError("Only decimal numeric constants are supported")
                # Read source text rather than the AST's binary float representation.
                node.decimal_value = number(literal)

    def evaluate(self, row: Row) -> str:
        try:
            with localcontext() as ctx:
                ctx.prec = 160
                result = self._visit(self.tree.body, row)
                return decimal_text(number(result))
        except DecimalException as exc:
            raise InputError("Arithmetic failed (division by zero or numeric overflow)") from exc

    def _visit(self, node, row: Row) -> Decimal:
        if isinstance(node, ast.Constant):
            return node.decimal_value
        if isinstance(node, ast.Name):
            return number(row[node.id])
        if isinstance(node, ast.UnaryOp):
            value = self._visit(node.operand, row)
            return -value if isinstance(node.op, ast.USub) else value
        left, right = self._visit(node.left, row), self._visit(node.right, row)
        if isinstance(node.op, ast.Add):
            return number(left + right)
        if isinstance(node.op, ast.Sub):
            return number(left - right)
        if isinstance(node.op, ast.Mult):
            return number(left * right)
        with localcontext() as context:
            context.prec = 28
            return left / right
