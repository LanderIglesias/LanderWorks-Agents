# ruff: noqa
# ruleid: debug-true
DEBUG = True
# ok: debug-true
DEBUG = False


def f():
    # ruleid: print-suelto
    print("x")
    # ok: print-suelto
    logger.info("x")


if __name__ == "__main__":
    # ok: print-suelto
    print("main")
