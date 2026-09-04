import sqlite3

import pytest

from backend.agents.taller_mecanico import db as tm_db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "taller_mecanico.db"
    monkeypatch.setattr(tm_db, "DB_PATH", db_path)
    connection = tm_db.get_conn()
    yield connection
    connection.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, dict]:
    # pragma_table_info(?) en vez de f"PRAGMA table_info({table})": aunque
    # aquí `table` siempre es un literal fijo, este es exactamente el
    # patrón que se copia a una herramienta de introspección real más
    # adelante, donde sí llegaría de fuera — se usa la forma parametrizable
    # desde ya para no propagar el hábito de interpolar SQL.
    cols = {}
    for row in connection.execute("SELECT * FROM pragma_table_info(?)", (table,)).fetchall():
        cols[row["name"]] = {"type": row["type"], "notnull": row["notnull"], "pk": row["pk"]}
    return cols


def _seed_cliente(connection: sqlite3.Connection, telefono_hash: str = "hash-600111222") -> int:
    # Los tests de esquema no pasan por crypto_utils: solo verifican
    # constraints de la BD (UNIQUE/NOT NULL/FK), así que los valores
    # "encrypted" son placeholders opacos, no ciphertext real. El
    # roundtrip de cifrado real se prueba en test_crypto_utils.py.
    cur = connection.execute(
        "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) "
        "VALUES ('placeholder-nombre', 'placeholder-telefono', ?)",
        (telefono_hash,),
    )
    connection.commit()
    return cur.lastrowid


def _seed_vehiculo(connection: sqlite3.Connection, cliente_id: int | None = None) -> int:
    if cliente_id is None:
        cliente_id = _seed_cliente(connection)
    cur = connection.execute(
        "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) VALUES (?, '1234ABC', 'Seat', 'Ibiza')",
        (cliente_id,),
    )
    connection.commit()
    return cur.lastrowid


def _seed_cita(connection: sqlite3.Connection, vehiculo_id: int | None = None) -> int:
    if vehiculo_id is None:
        vehiculo_id = _seed_vehiculo(connection)
    cur = connection.execute(
        "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-09-01 10:00', 'Ruido al frenar')",
        (vehiculo_id,),
    )
    connection.commit()
    return cur.lastrowid


_TABLAS_ESPERADAS = {
    "clientes",
    "vehiculos",
    "citas",
    "piezas",
    "presupuestos",
    "presupuesto_piezas",
    "quejas",
    "decision_log",
}


class TestSchemaCreation:
    def test_all_tables_exist(self, conn):
        assert _TABLAS_ESPERADAS.issubset(_table_names(conn))

    def test_init_db_is_idempotent(self, conn):
        # Llamar init_db otra vez sobre una conexión ya inicializada no debe fallar.
        tm_db.init_db(conn)
        assert _TABLAS_ESPERADAS.issubset(_table_names(conn))

    def test_foreign_keys_pragma_is_enabled(self, conn):
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


class TestClientes:
    def test_columns(self, conn):
        cols = _columns(conn, "clientes")
        assert cols["nombre_encrypted"]["notnull"] == 1
        assert cols["telefono_encrypted"]["notnull"] == 1
        assert cols["telefono_hash"]["notnull"] == 1
        assert cols["email_encrypted"]["notnull"] == 0
        assert cols["direccion_encrypted"]["notnull"] == 0
        assert cols["id"]["pk"] == 1
        # No debe existir ninguna columna de PII en claro.
        assert "nombre" not in cols
        assert "telefono" not in cols
        assert "email" not in cols
        assert "direccion" not in cols

    def test_telefono_hash_unique(self, conn):
        _seed_cliente(conn, telefono_hash="hash-600111222")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_cliente(conn, telefono_hash="hash-600111222")

    def test_telefono_encrypted_no_unique_directo(self, conn):
        # telefono_encrypted (Fernet, no determinista) no lleva UNIQUE:
        # dos filas con el mismo ciphertext "coincidente por accidente" y
        # distinto hash deben poder coexistir sin que la BD las rechace
        # (la unicidad real vive en telefono_hash, ver test anterior).
        conn.execute(
            "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) "
            "VALUES ('enc-Ana', 'mismo-ciphertext', 'hash-a')"
        )
        conn.execute(
            "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) "
            "VALUES ('enc-Bea', 'mismo-ciphertext', 'hash-b')"
        )
        conn.commit()

    def test_nombre_encrypted_required(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO clientes (telefono_encrypted, telefono_hash) "
                "VALUES ('enc-600111222', 'hash-600111222')"
            )

    def test_telefono_hash_required(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO clientes (nombre_encrypted, telefono_encrypted) "
                "VALUES ('enc-Ana', 'enc-600111222')"
            )


class TestVehiculos:
    def test_columns(self, conn):
        cols = _columns(conn, "vehiculos")
        assert cols["cliente_id"]["notnull"] == 1
        assert cols["matricula"]["notnull"] == 1
        assert cols["marca"]["notnull"] == 1
        assert cols["modelo"]["notnull"] == 1

    def test_vehiculo_requires_existing_cliente(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) "
                "VALUES (999, '1234ABC', 'Seat', 'Ibiza')"
            )

    def test_vehiculo_matricula_unique(self, conn):
        cliente_id = _seed_cliente(conn)
        conn.execute(
            "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) "
            "VALUES (?, '1234ABC', 'Seat', 'Ibiza')",
            (cliente_id,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) "
                "VALUES (?, '1234ABC', 'Renault', 'Clio')",
                (cliente_id,),
            )

    def test_kilometraje_no_negativo(self, conn):
        cliente_id = _seed_cliente(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo, kilometraje) "
                "VALUES (?, '1234ABC', 'Seat', 'Ibiza', -1)",
                (cliente_id,),
            )

    def test_deleting_cliente_with_vehiculo_is_restricted(self, conn):
        cliente_id = _seed_cliente(conn)
        conn.execute(
            "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) "
            "VALUES (?, '1234ABC', 'Seat', 'Ibiza')",
            (cliente_id,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))


class TestCitas:
    def test_cita_requires_existing_vehiculo(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) "
                "VALUES (999, '2026-09-01 10:00', 'Ruido al frenar')"
            )

    def test_estado_default_pendiente(self, conn):
        vehiculo_id = _seed_vehiculo(conn)
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) "
            "VALUES (?, '2026-09-01 10:00', 'Ruido al frenar')",
            (vehiculo_id,),
        )
        conn.commit()
        row = conn.execute("SELECT estado FROM citas").fetchone()
        assert row["estado"] == "pendiente"

    def test_estado_invalido_rechazado(self, conn):
        vehiculo_id = _seed_vehiculo(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
                "VALUES (?, '2026-09-01 10:00', 'Ruido al frenar', 'inventado')",
                (vehiculo_id,),
            )

    def test_duracion_minutos_default_60(self, conn):
        vehiculo_id = _seed_vehiculo(conn)
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-09-01 10:00', 'x')",
            (vehiculo_id,),
        )
        conn.commit()
        row = conn.execute("SELECT duracion_minutos FROM citas").fetchone()
        assert row["duracion_minutos"] == 60

    def test_duracion_minutos_debe_ser_positiva(self, conn):
        vehiculo_id = _seed_vehiculo(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, duracion_minutos) "
                "VALUES (?, '2026-09-01 10:00', 'x', 0)",
                (vehiculo_id,),
            )


class TestPiezas:
    def test_columns(self, conn):
        cols = _columns(conn, "piezas")
        assert cols["nombre"]["notnull"] == 1
        assert cols["precio_unitario"]["notnull"] == 1

    def test_stock_minimo_default_cero(self, conn):
        conn.execute("INSERT INTO piezas (nombre, precio_unitario) VALUES ('Pastillas', 30.0)")
        conn.commit()
        row = conn.execute("SELECT stock_minimo FROM piezas").fetchone()
        assert row["stock_minimo"] == 0

    def test_stock_minimo_no_negativo(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO piezas (nombre, precio_unitario, stock_minimo) "
                "VALUES ('Pastillas', 30.0, -1)"
            )

    def test_stock_no_negativo(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO piezas (nombre, precio_unitario, stock) VALUES ('Pastillas', 30.0, -1)"
            )

    def test_precio_no_negativo(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO piezas (nombre, precio_unitario) VALUES ('Pastillas', -5.0)")

    def test_referencia_unique_cuando_presente(self, conn):
        conn.execute(
            "INSERT INTO piezas (nombre, referencia, precio_unitario) VALUES ('Pastillas', 'REF-1', 30.0)"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO piezas (nombre, referencia, precio_unitario) VALUES ('Discos', 'REF-1', 60.0)"
            )

    def test_es_compatible_default_cero(self, conn):
        conn.execute("INSERT INTO piezas (nombre, precio_unitario) VALUES ('Pastillas', 30.0)")
        conn.commit()
        row = conn.execute("SELECT es_compatible FROM piezas").fetchone()
        assert row["es_compatible"] == 0

    def test_es_compatible_solo_acepta_0_o_1(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO piezas (nombre, precio_unitario, es_compatible) VALUES ('Pastillas', 30.0, 2)"
            )


def _seed_pieza(connection: sqlite3.Connection, es_compatible: int = 0) -> int:
    cur = connection.execute(
        "INSERT INTO piezas (nombre, precio_unitario, es_compatible) VALUES ('Pastillas', 30.0, ?)",
        (es_compatible,),
    )
    connection.commit()
    return cur.lastrowid


def _seed_presupuesto(connection: sqlite3.Connection, cita_id: int | None = None) -> int:
    if cita_id is None:
        cita_id = _seed_cita(connection)
    cur = connection.execute(
        "INSERT INTO presupuestos (cita_id, total) VALUES (?, 100.0)", (cita_id,)
    )
    connection.commit()
    return cur.lastrowid


class TestPresupuestoPiezas:
    def test_columns(self, conn):
        cols = _columns(conn, "presupuesto_piezas")
        assert cols["presupuesto_id"]["notnull"] == 1
        assert cols["pieza_id"]["notnull"] == 1
        assert cols["cantidad"]["notnull"] == 1
        assert cols["precio_unitario_aplicado"]["notnull"] == 1

    def test_requiere_presupuesto_existente(self, conn):
        pieza_id = _seed_pieza(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO presupuesto_piezas (presupuesto_id, pieza_id, cantidad, precio_unitario_aplicado) "
                "VALUES (999, ?, 1, 30.0)",
                (pieza_id,),
            )

    def test_requiere_pieza_existente(self, conn):
        presupuesto_id = _seed_presupuesto(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO presupuesto_piezas (presupuesto_id, pieza_id, cantidad, precio_unitario_aplicado) "
                "VALUES (?, 999, 1, 30.0)",
                (presupuesto_id,),
            )

    def test_cantidad_debe_ser_positiva(self, conn):
        presupuesto_id = _seed_presupuesto(conn)
        pieza_id = _seed_pieza(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO presupuesto_piezas (presupuesto_id, pieza_id, cantidad, precio_unitario_aplicado) "
                "VALUES (?, ?, 0, 30.0)",
                (presupuesto_id, pieza_id),
            )

    def test_es_compatible_default_cero(self, conn):
        presupuesto_id = _seed_presupuesto(conn)
        pieza_id = _seed_pieza(conn)
        conn.execute(
            "INSERT INTO presupuesto_piezas (presupuesto_id, pieza_id, cantidad, precio_unitario_aplicado) "
            "VALUES (?, ?, 1, 30.0)",
            (presupuesto_id, pieza_id),
        )
        conn.commit()
        row = conn.execute("SELECT es_compatible FROM presupuesto_piezas").fetchone()
        assert row["es_compatible"] == 0


class TestQuejas:
    def test_columns(self, conn):
        cols = _columns(conn, "quejas")
        assert cols["cliente_id"]["notnull"] == 1
        assert cols["descripcion"]["notnull"] == 1
        assert cols["vehiculo_id"]["notnull"] == 0

    def test_requiere_cliente_existente(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO quejas (cliente_id, descripcion) VALUES (999, 'no llamaron')")

    def test_resuelta_default_cero(self, conn):
        cliente_id = _seed_cliente(conn)
        conn.execute(
            "INSERT INTO quejas (cliente_id, descripcion) VALUES (?, 'no llamaron')", (cliente_id,)
        )
        conn.commit()
        row = conn.execute("SELECT resuelta FROM quejas").fetchone()
        assert row["resuelta"] == 0

    def test_vehiculo_id_opcional(self, conn):
        cliente_id = _seed_cliente(conn)
        conn.execute(
            "INSERT INTO quejas (cliente_id, descripcion) VALUES (?, 'queja general')",
            (cliente_id,),
        )
        conn.commit()
        row = conn.execute("SELECT vehiculo_id FROM quejas").fetchone()
        assert row["vehiculo_id"] is None

    def test_resuelta_solo_acepta_0_o_1(self, conn):
        cliente_id = _seed_cliente(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO quejas (cliente_id, descripcion, resuelta) VALUES (?, 'x', 2)",
                (cliente_id,),
            )


class TestPresupuestos:
    def test_presupuesto_requires_existing_cita(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO presupuestos (cita_id, total) VALUES (999, 100.0)")

    def test_estado_default_borrador(self, conn):
        cita_id = _seed_cita(conn)
        conn.execute("INSERT INTO presupuestos (cita_id, total) VALUES (?, 100.0)", (cita_id,))
        conn.commit()
        row = conn.execute("SELECT estado FROM presupuestos").fetchone()
        assert row["estado"] == "borrador"

    def test_estado_invalido_rechazado(self, conn):
        cita_id = _seed_cita(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO presupuestos (cita_id, total, estado) VALUES (?, 100.0, 'inventado')",
                (cita_id,),
            )

    def test_total_no_negativo(self, conn):
        cita_id = _seed_cita(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO presupuestos (cita_id, total) VALUES (?, -1.0)", (cita_id,))


class TestDecisionLog:
    def test_columns_match_exact_ddl(self, conn):
        cols = _columns(conn, "decision_log")
        for required in [
            "timestamp",
            "input_text",
            "agent",
            "reasoning",
            "output",
            "reviewed_by",
            "verdict",
            "verdict_reason",
            "parent_decision_id",
            "langfuse_trace_id",
            "langfuse_observation_id",
        ]:
            assert required in cols

        for required_not_null in ["timestamp", "input_text", "agent", "reasoning", "output"]:
            assert cols[required_not_null]["notnull"] == 1

        for optional in [
            "reviewed_by",
            "verdict",
            "verdict_reason",
            "parent_decision_id",
            "langfuse_trace_id",
            "langfuse_observation_id",
        ]:
            assert cols[optional]["notnull"] == 0

    def test_langfuse_columns_admiten_valores_y_null(self, conn):
        """langfuse_trace_id/observation_id son opcionales -- una fila sin
        Langfuse configurado debe poder insertarse igual (NULL), y una con
        Langfuse activo debe poder guardar los IDs reales."""
        conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
            "VALUES ('2026-08-27 10:00:00', 'x', 'router', 'r', 'o')"
        )
        conn.execute(
            "INSERT INTO decision_log "
            "(timestamp, input_text, agent, reasoning, output, langfuse_trace_id, langfuse_observation_id) "
            "VALUES ('2026-08-27 10:01:00', 'x', 'router', 'r', 'o', 'trace-abc', 'obs-abc')"
        )
        conn.commit()
        rows = conn.execute(
            "SELECT langfuse_trace_id, langfuse_observation_id FROM decision_log ORDER BY id"
        ).fetchall()
        assert rows[0]["langfuse_trace_id"] is None
        assert rows[0]["langfuse_observation_id"] is None
        assert rows[1]["langfuse_trace_id"] == "trace-abc"
        assert rows[1]["langfuse_observation_id"] == "obs-abc"

    def test_migracion_idempotente_sobre_bd_ya_creada_con_esquema_anterior(
        self, tmp_path, monkeypatch
    ):
        """Simula una BD ya creada ANTES de que estas dos columnas
        existieran (DDL manual sin ellas) -- init_db() debe añadirlas vía
        ALTER TABLE sin lanzar, y sin perder las filas ya existentes."""
        db_path = tmp_path / "legacy.db"
        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE decision_log ("
            "id INTEGER PRIMARY KEY, timestamp DATETIME NOT NULL, input_text TEXT NOT NULL, "
            "agent TEXT NOT NULL, reasoning TEXT NOT NULL, output TEXT NOT NULL, "
            "reviewed_by TEXT, verdict TEXT, verdict_reason TEXT, "
            "parent_decision_id INTEGER REFERENCES decision_log(id))"
        )
        legacy_conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
            "VALUES ('2026-08-27 10:00:00', 'fila preexistente', 'router', 'r', 'o')"
        )
        legacy_conn.commit()
        legacy_conn.close()

        monkeypatch.setattr(tm_db, "DB_PATH", db_path)
        migrated_conn = tm_db.get_conn()
        try:
            cols = _columns(migrated_conn, "decision_log")
            assert "langfuse_trace_id" in cols
            assert "langfuse_observation_id" in cols
            row = migrated_conn.execute("SELECT * FROM decision_log").fetchone()
            assert row["input_text"] == "fila preexistente"
            assert row["langfuse_trace_id"] is None
        finally:
            migrated_conn.close()

    def test_insert_minimal_decision(self, conn):
        conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
            "VALUES ('2026-08-27 10:00:00', 'ruido al frenar', 'router', "
            "'clasificado como consulta tecnica', '{\"derivado_a\": \"diagnostico\"}')"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row["agent"] == "router"
        assert row["verdict"] is None

    def test_parent_decision_id_chains_to_existing_row(self, conn):
        cur = conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
            "VALUES ('2026-08-27 10:00:00', 'x', 'diagnostico', 'r', 'o')"
        )
        conn.commit()
        parent_id = cur.lastrowid
        conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output, parent_decision_id) "
            "VALUES ('2026-08-27 10:05:00', 'x retry', 'diagnostico', 'r2', 'o2', ?)",
            (parent_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT parent_decision_id FROM decision_log WHERE input_text = 'x retry'"
        ).fetchone()
        assert row["parent_decision_id"] == parent_id

    def test_parent_decision_id_requires_existing_row(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO decision_log "
                "(timestamp, input_text, agent, reasoning, output, parent_decision_id) "
                "VALUES ('2026-08-27 10:00:00', 'x', 'router', 'r', 'o', 999)"
            )
