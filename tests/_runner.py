r"""测试运行器：各测试文件共用（原先 10 份重复实现）。

为什么要独立出来
----------------
1. **跳过被计为通过**：live 用例在缺 Key 时 `return`，旧 runner 打 `[PASS]`，
   报表显示"全绿"，掩盖了它们从未运行。现在跳过必须显式 `raise SkipTest(...)`，
   runner 单独统计 SKIP，并**不把 SKIP 计入通过数**。
2. 顺带消掉每个测试文件里那份 ~20 行的重复 runner。

用法（测试文件末尾）：

    from _runner import SkipTest, run_tests

    def main() -> int:
        return run_tests(globals())

live 用例写法（缺 Key 时）：

    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SkipTest("未设置 DEEPSEEK_API_KEY")
"""

import traceback

__all__ = ["SkipTest", "run_tests"]


class SkipTest(Exception):
    """用例声明「本次不执行」（例如缺少 API Key）。

    它**既不算通过也不算失败**；runner 会单列 SKIP 并从通过率里剔除。
    """


def run_tests(namespace, *, quiet: bool = False) -> int:
    """收集 namespace 里的 `test_*` 函数逐个执行，返回进程退出码。

    因为测试文件都是「脚本 + 函数」风格（无 pytest），这里靠 `globals()` 收集。
    """
    tests = [
        value
        for name, value in sorted(namespace.items())
        if name.startswith("test_") and callable(value)
    ]

    passed = failed = skipped = 0
    for test in tests:
        name = getattr(test, "__name__", repr(test))
        print(f"[RUN ] {name}")
        try:
            test()
        except SkipTest as exc:
            skipped += 1
            reason = f"：{exc}" if str(exc) else ""
            print(f"[SKIP] {name}{reason}")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"[PASS] {name}")

    total = len(tests)
    print(f"\n结果：{passed} 通过 / {failed} 失败 / {skipped} 跳过（共 {total} 个用例）")
    if skipped:
        print(f"注意：{skipped} 条未执行，未计入通过数。")
    return 1 if failed else 0
