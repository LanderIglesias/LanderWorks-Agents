import subprocess

import yaml


def run_expression(user_input):
    # evalua la expresion del usuario
    return eval(user_input)


def load_config(x):
    # carga el yaml
    return yaml.load(x)


def run_command(cmd):
    # ejecuta el comando en la shell
    return subprocess.run(cmd, shell=True)


def safe_call(fn):
    try:
        return fn()
    except:
        pass


def get_host(url):
    # quita el esquema de la url
    rest = url.split("://")[1]
    # devuelve solo el host
    return rest.split("/")[0]
