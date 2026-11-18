"""Bounded interpretation of numeric expressions and structured numeric arrays."""
import ast
import math
import operator
import re
from time import monotonic

MAX_VALUE = 10**12
MAX_NODES = 96
MAX_EXPONENT = 32
_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_FUNCTIONS = {
    "sqrt": (math.sqrt, 1, 1), "log": (math.log, 1, 2), "exp": (math.exp, 1, 1),
    "abs": (abs, 1, 1), "min": (min, 2, 8), "max": (max, 2, 8), "round": (round, 1, 2),
}

# Match bounded numeric notation without consuming adjacent prose, table cells,
# or list delimiters. Include common unsupported operators so they are reported.
_DISPLAY_NUMBER = r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?:[eE][+-]?\d+)?"
_DISPLAY_TOKEN = rf"(?>[A-Za-z_]\w*\(|{_DISPLAY_NUMBER}|[(),+−–*/×÷%√^-])"
_DISPLAY_SIDE = rf"{_DISPLAY_TOKEN}(?:[^\S\r\n]*{_DISPLAY_TOKEN})*+"
_DISPLAY_EQUATION = re.compile(
    rf"(?<![\w.,]){_DISPLAY_SIDE}(?:[^\S\r\n]*=[^\S\r\n]*{_DISPLAY_SIDE})+(?!\w|[.,]\d)"
)
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_GROUPED_DIGITS = re.compile(r"(?<![\d.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")
_DISPLAY_SYMBOLS = str.maketrans({"−": "-", "–": "-", "×": "*", "÷": "/"})


def displayed_equations(text):
    """Yield exact spans and independently evaluable sides of numeric equalities."""
    # A comma between digits is a decimal separator in displayed math. Other
    # commas separate function arguments inside parentheses or clauses outside.
    scan = list(text)
    depth = 0
    for mark in re.finditer(r"[(),;|\n]", text):
        index = mark.start()
        if mark[0] == "(":
            depth += 1
        elif mark[0] == ")":
            depth = max(0, depth - 1)
        elif mark[0] != ",":
            depth = 0
        elif not depth and not (0 < index < len(text) - 1
                                and text[index - 1].isdigit() and text[index + 1].isdigit()):
            scan[index] = ";"
    for match in _DISPLAY_EQUATION.finditer("".join(scan)):
        sides = match[0].split("=")
        if not all(re.search(r"\d", side) for side in sides):
            continue
        normalized = tuple(
            _DECIMAL_COMMA.sub(".", _GROUPED_DIGITS.sub(lambda m: "".join(m[0].split()), side))
            .translate(_DISPLAY_SYMBOLS).strip()
            for side in sides
        )
        yield match.span(), normalized


def _number(value):
    if type(value) not in (int, float) or not -MAX_VALUE <= value <= MAX_VALUE:
        raise ValueError("numeric magnitude or type outside verifier limits")
    return value


def arithmetic(expression: str, *, timeout: float = .05, operands: set | None = None):
    """Return a number without evaluating Python source. Commas separate arguments."""
    if not expression.strip() or len(expression) > 256:
        raise ValueError("expression length outside verifier limits")
    deadline = monotonic() + timeout
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
            raise ValueError("too many expression nodes")

        def visit(node):
            if monotonic() >= deadline:
                raise ValueError("arithmetic deadline exceeded")
            if isinstance(node, ast.Constant):
                value = _number(node.value)
                if operands is not None:
                    operands.add(value)
                return value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                return _number(-visit(node.operand))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
                return visit(node.operand)
            if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                    raise ValueError("exponent outside verifier limits")
                return _number(_OPERATORS[type(node.op)](left, right))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in _FUNCTIONS and not node.keywords):
                function, minimum, maximum = _FUNCTIONS[node.func.id]
                if minimum <= len(node.args) <= maximum:
                    arguments = [visit(arg) for arg in node.args]
                    if node.func.id == "round" and len(arguments) == 2:
                        digits = arguments[1]
                        if type(digits) is not int or abs(digits) > 12:
                            raise ValueError("round precision outside verifier limits")
                    return _number(function(*arguments))
            raise ValueError("unsupported arithmetic syntax")

        result = visit(tree.body)
        if monotonic() >= deadline:
            raise ValueError("arithmetic deadline exceeded")
        return result
    except (ArithmeticError, SyntaxError, RecursionError) as exc:
        raise ValueError("invalid arithmetic expression") from exc


def numeric_array(operation: str, arrays):
    """Fixed validators for mean, dot product and matrix multiplication."""
    def vector(values):
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 32:
            raise ValueError("invalid vector size")
        return [_number(value) for value in values]

    def dot(left, right):
        return _number(math.fsum(a * b for a, b in zip(left, right, strict=True)))

    if operation == "mean" and len(arrays) == 1:
        return _number(math.fsum(vector(arrays[0])) / len(arrays[0]))
    if operation == "dot" and len(arrays) == 2:
        return dot(*(vector(values) for values in arrays))
    if operation == "matmul" and len(arrays) == 2:
        left, right = arrays
        if not 1 <= len(left) <= 16 or not 1 <= len(right) <= 16:
            raise ValueError("invalid matrix size")
        columns = list(zip(*(vector(row) for row in right), strict=True))
        if len(columns) > 16:
            raise ValueError("invalid matrix width")
        return [[dot(vector(row), column) for column in columns] for row in left]
    raise ValueError("unsupported numeric array operation")
