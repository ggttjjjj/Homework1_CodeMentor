"""简单计算器：支持加、减、乘、除四则运算"""


def add(a: float, b: float) -> float:
    """加法"""
    return a + b


def subtract(a: float, b: float) -> float:
    """减法"""
    return a - b


def multiply(a: float, b: float) -> float:
    """乘法"""
    return a * b


def divide(a: float, b: float) -> float:
    """除法（除数为 0 时抛出 ValueError）"""
    if b == 0:
        raise ValueError("除数不能为 0")
    return a / b


OPERATIONS = {
    "+": add,
    "-": subtract,
    "*": multiply,
    "/": divide,
}


def calculate(a: float, op: str, b: float) -> float:
    """根据运算符执行计算"""
    if op not in OPERATIONS:
        raise ValueError(f"不支持的运算符: {op}，仅支持 + - * /")
    return OPERATIONS[op](a, b)


def main() -> None:
    """命令行交互入口"""
    print("=== 简易计算器 ===")
    print("输入格式: 数字 运算符 数字，例如: 3 + 5（输入 q 退出）")
    while True:
        text = input("> ").strip()
        if text.lower() in ("q", "quit", "exit"):
            print("再见！")
            break
        parts = text.split()
        if len(parts) != 3:
            print("格式错误，示例: 3 + 5")
            continue
        try:
            a, op, b = float(parts[0]), parts[1], float(parts[2])
            result = calculate(a, op, b)
            # 整数结果去掉小数点，更美观
            if result == int(result):
                result = int(result)
            print(f"= {result}")
        except ValueError as e:
            print(f"错误: {e}")


if __name__ == "__main__":
    main()
