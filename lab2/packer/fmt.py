"""Форматирование чисел по-русски: пробел между тысячами, запятая в дробях."""


def human(n: float) -> str:
    """12345 → «12 345»."""
    return f'{n:,.0f}'.replace(',', ' ')


def num(x: float, digits: int = 3) -> str:
    """3.14159 → «3,142»."""
    return f'{x:.{digits}f}'.replace('.', ',')


def pct(x: float, digits: int = 1) -> str:
    """63.27 → «63,3 %»."""
    return f'{num(x, digits)} %'
