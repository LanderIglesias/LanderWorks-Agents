# ruff: noqa
def f(url):
    # ruleid: parseo-manual-de-url
    a = url.split("?")[0]
    # ruleid: parseo-manual-de-url
    b = url.split("://")[1]
    # ok: parseo-manual-de-url
    c = url.split(",")
    return a, b, c
