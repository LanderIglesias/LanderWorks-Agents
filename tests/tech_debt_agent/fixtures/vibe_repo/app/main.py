import sqlite3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DEBUG = True

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])


@app.get("/users")
def get_user(name: str):
    print("buscando usuario", name)
    try:
        conn = sqlite3.connect("app.db")
        rows = conn.execute(f"SELECT * FROM users WHERE name = '{name}'").fetchall()
        return {"rows": rows}
    except Exception as e:
        return {"error": str(e)}
