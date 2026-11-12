# ruff: noqa
import asyncio
import os
import pickle
import subprocess
from subprocess import run

import jwt
import yaml
from fastapi.middleware.cors import CORSMiddleware
from flask_cors import CORS
from sqlalchemy import text

TABLE = "users"
placeholders = "?,?"


def evals(user_input, x):
    # ruleid: eval-exec-dinamico
    eval(user_input)
    # ruleid: eval-exec-dinamico
    eval(f"1+{x}")
    # ruleid: eval-exec-dinamico
    exec(user_input)
    # ok: eval-exec-dinamico
    eval("1+1")


def sql(conn, cur, name, ids):
    # ruleid: sql-por-string
    conn.execute(f"SELECT * FROM users WHERE name = '{name}'")
    # ruleid: sql-por-string
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    # ruleid: sql-por-string
    cur.execute("SELECT * FROM users WHERE name = '%s'" % name)
    # ruleid: sql-por-string
    cur.execute(f"SELECT * FROM users WHERE name = '{name}'")
    # ruleid: sql-por-string
    cur.executemany(f"INSERT INTO t VALUES ({name})", [])
    # ruleid: sql-por-string
    cur.executescript(f"DROP TABLE {name}")
    # ruleid: sql-por-string
    conn.execute(f"SELECT * FROM {TABLE} WHERE name = '{name}'")
    # ok: sql-por-string
    conn.execute(f"SELECT * FROM {TABLE}")
    # ok: sql-por-string
    conn.execute(f"SELECT * FROM t WHERE id IN ({placeholders})", ids)
    # ok: sql-por-string
    conn.execute(f"SELECT * FROM t WHERE id IN ({','.join('?' * len(ids))})", ids)
    # ok: sql-por-string
    conn.execute("SELECT * FROM users WHERE name = ?", (name,))


def sql_text(name):
    # ruleid: sql-text-por-string
    text(f"SELECT * FROM users WHERE name = '{name}'")
    # ok: sql-text-por-string
    text("SELECT * FROM users WHERE name = :name")


def pickles(data):
    # ruleid: pickle-load
    pickle.loads(data)
    # ok: pickle-load
    pickle.dumps(data)


def yamls(x):
    # ruleid: yaml-load-inseguro
    yaml.load(x)
    # ruleid: yaml-load-inseguro
    yaml.unsafe_load(x)
    # ruleid: yaml-load-inseguro
    yaml.load(x, Loader=yaml.Loader)
    # ok: yaml-load-inseguro
    yaml.load(x, Loader=yaml.SafeLoader)
    # ok: yaml-load-inseguro
    yaml.load(x, Loader=SafeLoader)
    # ok: yaml-load-inseguro
    yaml.safe_load(x)


def shells(cmd, name):
    # ruleid: subprocess-shell-variable
    subprocess.run(cmd, shell=True)
    # ruleid: subprocess-shell-variable
    subprocess.run(f"ls {name}", shell=True)
    # ruleid: subprocess-shell-variable
    os.system(cmd)
    # ruleid: subprocess-shell-variable
    os.system(f"rm {name}")
    # ruleid: subprocess-shell-variable
    os.popen(cmd)
    # ruleid: subprocess-shell-variable
    asyncio.create_subprocess_shell(cmd)
    # ruleid: subprocess-shell-variable
    run(cmd, shell=True)
    # ok: subprocess-shell-variable
    subprocess.run(["ls", cmd])


def shells_literal():
    # ruleid: subprocess-shell-literal
    subprocess.run("ls -la", shell=True)
    # ruleid: subprocess-shell-literal
    os.system("ls")
    # ok: subprocess-shell-literal
    subprocess.run(["ls"])


# ruleid: cors-fastapi-abierto
app.add_middleware(CORSMiddleware, allow_origins=["*"])
# ruleid: cors-fastapi-abierto
app.add_middleware(CORSMiddleware, allow_origin_regex=".*")
# ok: cors-fastapi-abierto
app.add_middleware(CORSMiddleware, allow_origins=["https://a.com"])
# ruleid: cors-fastapi-credenciales
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)
# ruleid: cors-flask-abierto
CORS(app)
# ruleid: cors-flask-abierto
CORS(app, origins="*")
# ok: cors-flask-abierto
CORS(app, origins=["https://a.com"])
# ruleid: cors-flask-credenciales
CORS(app, supports_credentials=True)
# ok: cors-flask-credenciales
CORS(app, supports_credentials=True, origins=["https://a.com"])


def jwts(token, key):
    # ruleid: jwt-sin-verificacion
    jwt.decode(token, key, verify=False)
    # ruleid: jwt-sin-verificacion
    jwt.decode(token, options={"verify_signature": False})
    # ruleid: jwt-sin-verificacion
    jwt.decode(token, key, algorithms=["none"])
    # ok: jwt-sin-verificacion
    jwt.decode(token, key, algorithms=["HS256"])
