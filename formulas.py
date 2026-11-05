"""Формулы для чата MAX: переводим LaTeX ($x^2$, \\frac{1}{2}, \\sqrt{x}) в обычный текст: x², 1/2, √x."""
import re

SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUBSCRIPT = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

SYMBOLS = {
    r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\le": "≤", r"\leq": "≤", r"\ge": "≥", r"\geq": "≥", r"\ne": "≠", r"\neq": "≠",
    r"\approx": "≈", r"\infty": "∞", r"\pi": "π", r"\alpha": "α", r"\beta": "β",
    r"\gamma": "γ", r"\Delta": "Δ", r"\delta": "δ", r"\theta": "θ", r"\varphi": "φ",
    r"\phi": "φ", r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω",
    r"\in": "∈", r"\notin": "∉", r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
    r"\Rightarrow": "⇒", r"\Leftrightarrow": "⇔", r"\iff": "⇔", r"\Leftarrow": "⇐", r"\implies": "⇒",
    r"\to": "→", r"\rightarrow": "→", r"\angle": "∠",
    r"\circ": "°", r"\degree": "°", r"\perp": "⊥", r"\parallel": "∥",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tg", r"\tg": "tg", r"\ctg": "ctg",
    r"\cot": "ctg", r"\log": "log", r"\ln": "ln", r"\lg": "lg",
    r"\left": "", r"\right": "", r"\,": " ", r"\;": " ", r"\quad": "  ", r"\!": "",
}


def _group(s: str, i: int) -> tuple[str, int]:
    """Читает {…} или один символ начиная с позиции i, возвращает (содержимое, новая позиция)."""
    if i < len(s) and s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    return (s[i], i + 1) if i < len(s) else ("", i)


def _wrap(x: str) -> str:
    return x if re.fullmatch(r"[\w.,²³]+", x) else f"({x})"


def latex_to_text(expr: str) -> str:
    s = expr
    # \frac{a}{b} и \sqrt{x} — с вложенными скобками
    for cmd in (r"\dfrac", r"\tfrac", r"\frac"):
        while cmd in s:
            i = s.index(cmd)
            num, j = _group(s, i + len(cmd))
            den, k = _group(s, j)
            # смешанное число 2\frac{1}{2} → «2 1/2», а не «21/2»
            space = " " if i > 0 and s[i - 1].isdigit() else ""
            s = s[:i] + f"{space}{_wrap(latex_to_text(num))}/{_wrap(latex_to_text(den))}" + s[k:]
    while r"\sqrt" in s:
        i = s.index(r"\sqrt")
        j = i + 5
        root = ""
        if j < len(s) and s[j] == "[":
            end = s.index("]", j)
            root, j = s[j + 1:end], end + 1
        arg, k = _group(s, j)
        prefix = {"3": "∛", "4": "∜"}.get(root, f"{root}√" if root else "√")
        s = s[:i] + prefix + _wrap(latex_to_text(arg)) + s[k:]
    for name in sorted(SYMBOLS, key=len, reverse=True):
        s = re.sub(re.escape(name) + r"(?![a-zA-Z])", lambda _m, v=SYMBOLS[name]: v, s)
    s = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\{([^{}]*)\}", r"\1", s)

    def script(m: re.Match, table) -> str:
        body = m.group(1) or m.group(2)
        converted = body.translate(table)
        if all(c in "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎," for c in converted):
            return converted
        return ("^" if table is SUPERSCRIPT else "_") + _wrap(body)

    s = re.sub(r"\^\{([^{}]*)\}|\^(\w)", lambda m: script(m, SUPERSCRIPT), s)
    s = re.sub(r"_\{([^{}]*)\}|_(\w)", lambda m: script(m, SUBSCRIPT), s)
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    s = re.sub(r"(?<=\S) - (?=\S)", " − ", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


LATEX_HINT = re.compile(r"\\[a-zA-Z]+|sqrt|\^\{|_\{")


def clean(text: str) -> str:
    """Убирает LaTeX из ответа ИИ: в MAX формулы не отрисовываются и выглядят как {sqrt}, \\frac и т. п.

    Модель иногда пишет формулы в LaTeX, даже когда её просят этого не делать, поэтому
    подстраховываемся: формулы в $...$ и строки с LaTeX-командами переводим в обычный текст.
    """
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: latex_to_text(m.group(1)), text, flags=re.S)
    text = re.sub(r"\\\[(.+?)\\\]", lambda m: latex_to_text(m.group(1)), text, flags=re.S)
    text = re.sub(r"\$([^$\n]+?)\$", lambda m: latex_to_text(m.group(1)), text)
    text = re.sub(r"\\\((.+?)\\\)", lambda m: latex_to_text(m.group(1)), text)

    lines = []
    for line in text.split("\n"):
        if LATEX_HINT.search(line):
            # «{sqrt}», «sqrt{...}» без обратной косой черты → нормальный \sqrt
            line = re.sub(r"\{\\?sqrt\}", lambda _m: "\\sqrt", line)
            line = re.sub(r"(?<!\\)\bsqrt\b", lambda _m: "\\sqrt", line)
            line = latex_to_text(line)
        if re.fullmatch(r"\s*([*_\-—=])\1{2,}\s*", line):
            continue                    # разделители *** и --- в мессенджере выглядят как мусор
        lines.append(logs(line))
    return "\n".join(lines)


# Нижние индексы есть в Юникоде не для всех букв (например, для b и c их нет)
SUBSCRIPT_CHARS = dict(zip("0123456789aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))


def log_base(base: str) -> str:
    """«log» с основанием: log₂, logₐ — или log_b, если для буквы нет нижнего индекса."""
    if all(c in SUBSCRIPT_CHARS for c in base):
        return "log" + "".join(SUBSCRIPT_CHARS[c] for c in base)
    return f"log_{base}"


def logs(line: str) -> str:
    """Логарифмы: модель пишет «log_aa», «log_am+log_an» — это не читается.
    Превращаем в «logₐ(a)», «logₐ(m)+logₐ(n)»: основание индексом, аргумент в скобках."""
    # 1. log_a(b) или log_{10} (b) — аргумент уже в скобках, меняем только основание
    line = re.sub(r"log_\{?([a-z0-9]{1,2})\}?(?=\s*\()", lambda m: log_base(m.group(1)), line)
    # 2. log_am, log_aa, log_amⁿ — основание из одного символа, сразу за ним аргумент без скобок
    line = re.sub(r"log_([a-z0-9])([a-zA-Z0-9ⁿ²³·]+)",
                  lambda m: f"{log_base(m.group(1))}({m.group(2)})", line)
    # 3. log_a b — аргумент отделён пробелом, оставляем как есть
    line = re.sub(r"log_([a-z0-9]{1,2})\b", lambda m: log_base(m.group(1)), line)
    return line
