import sqlite3

import pytest

from backend.agents.taller_mecanico import agenda
from backend.agents.taller_mecanico import db as tm_db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "taller_mecanico.db"
    monkeypatch.setattr(tm_db, "DB_PATH", db_path)
    connection = tm_db.get_conn()
    yield connection
    connection.close()


@pytest.fixture
def vehiculo_id(conn) -> int:
    # agenda.py no usa crypto_utils (no toca columnas de clientes), así que
    # estos valores son placeholders opacos, no ciphertext real — ver la
    # misma convención en test_schema.py._seed_cliente. Nombrados para que
    # no se confundan con un token Fernet real si alguien los copia.
    cur = conn.execute(
        "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) "
        "VALUES ('placeholder-nombre', 'placeholder-telefono', 'placeholder-hash-600111222')"
    )
    conn.commit()
    cliente_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) VALUES (?, '1234ABC', 'Seat', 'Ibiza')",
        (cliente_id,),
    )
    conn.commit()
    return cur.lastrowid


class TestCrearCita:
    def test_crea_cita_con_duracion_por_defecto(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Ruido al frenar")
        row = conn.execute("SELECT * FROM citas WHERE id = ?", (cita_id,)).fetchone()
        assert row["duracion_minutos"] == 60
        assert row["motivo"] == "Ruido al frenar"
        assert row["estado"] == "pendiente"

    def test_crea_cita_con_duracion_explicita(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 10:00", "Revisión completa", duracion_minutos=120
        )
        row = conn.execute("SELECT duracion_minutos FROM citas WHERE id = ?", (cita_id,)).fetchone()
        assert row["duracion_minutos"] == 120

    def test_rechaza_vehiculo_inexistente(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            agenda.crear_cita(conn, 999, "2026-09-01 10:00", "x")

    def test_dos_citas_que_se_solapan_la_segunda_falla(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        with pytest.raises(agenda.SolapamientoError):
            agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:30", "Segunda", duracion_minutos=60)

    def test_dos_citas_que_no_se_solapan_ambas_se_crean(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        # 11:00 empieza justo cuando termina la primera (10:00 + 60min) -> no solapa
        segunda_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 11:00", "Segunda", duracion_minutos=60
        )
        assert segunda_id is not None

    def test_solapamiento_parcial_al_inicio_falla(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        with pytest.raises(agenda.SolapamientoError):
            agenda.crear_cita(conn, vehiculo_id, "2026-09-01 09:30", "Segunda", duracion_minutos=60)

    def test_cita_totalmente_contenida_falla(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 09:00", "Primera", duracion_minutos=180)
        with pytest.raises(agenda.SolapamientoError):
            agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Segunda", duracion_minutos=30)

    def test_solapamiento_no_bloquea_otro_vehiculo(self, conn, vehiculo_id):
        cur = conn.execute(
            "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo) "
            "SELECT cliente_id, '9999XYZ', 'Renault', 'Clio' FROM vehiculos WHERE id = ?",
            (vehiculo_id,),
        )
        conn.commit()
        otro_vehiculo_id = cur.lastrowid

        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        # Mismo hueco, vehículo distinto -> no debe solapar.
        otra_cita_id = agenda.crear_cita(
            conn, otro_vehiculo_id, "2026-09-01 10:00", "Segunda", duracion_minutos=60
        )
        assert otra_cita_id is not None

    def test_cita_cancelada_no_bloquea_el_hueco(self, conn, vehiculo_id):
        primera_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60
        )
        agenda.cancelar_cita(conn, primera_id)
        # El hueco quedó libre porque la primera se canceló.
        segunda_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 10:00", "Segunda", duracion_minutos=60
        )
        assert segunda_id is not None


class TestConsultarDisponibilidad:
    def test_hueco_libre_es_disponible(self, conn, vehiculo_id):
        assert agenda.esta_disponible(conn, vehiculo_id, "2026-09-01 10:00", 60) is True

    def test_hueco_ocupado_no_es_disponible(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        assert agenda.esta_disponible(conn, vehiculo_id, "2026-09-01 10:00", 60) is False


class TestReprogramarCita:
    def test_reprogramar_a_hueco_libre(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera")
        agenda.reprogramar_cita(conn, cita_id, "2026-09-02 09:00")
        row = conn.execute("SELECT fecha_hora FROM citas WHERE id = ?", (cita_id,)).fetchone()
        assert row["fecha_hora"] == "2026-09-02 09:00"

    def test_reprogramar_no_choca_consigo_misma(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera")
        # Reprogramar "al mismo sitio" no debe fallar por solapar consigo misma.
        agenda.reprogramar_cita(conn, cita_id, "2026-09-01 10:00")

    def test_reprogramar_a_hueco_ocupado_falla(self, conn, vehiculo_id):
        agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=60)
        segunda_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 12:00", "Segunda", duracion_minutos=60
        )
        with pytest.raises(agenda.SolapamientoError):
            agenda.reprogramar_cita(conn, segunda_id, "2026-09-01 10:30")

    def test_reprogramar_cita_inexistente_falla(self, conn):
        with pytest.raises(agenda.CitaNoEncontradaError):
            agenda.reprogramar_cita(conn, 999, "2026-09-02 09:00")

    def test_reprogramar_cita_cancelada_falla(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera")
        agenda.cancelar_cita(conn, cita_id)
        with pytest.raises(agenda.EstadoCitaInvalidoError):
            agenda.reprogramar_cita(conn, cita_id, "2026-09-02 09:00")

    def test_reprogramar_cambia_duracion(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(
            conn, vehiculo_id, "2026-09-01 10:00", "Primera", duracion_minutos=30
        )
        agenda.reprogramar_cita(conn, cita_id, "2026-09-01 10:00", nueva_duracion_minutos=90)
        row = conn.execute("SELECT duracion_minutos FROM citas WHERE id = ?", (cita_id,)).fetchone()
        assert row["duracion_minutos"] == 90


class TestFechaHoraFormatos:
    def test_acepta_formato_con_segundos(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00:00", "Primera")
        assert cita_id is not None

    def test_formato_invalido_da_error_de_dominio(self, conn, vehiculo_id):
        with pytest.raises(agenda.FechaHoraInvalidaError):
            agenda.crear_cita(conn, vehiculo_id, "01/09/2026 10:00", "Primera")


class TestCancelarCita:
    def test_cancelar_marca_estado(self, conn, vehiculo_id):
        cita_id = agenda.crear_cita(conn, vehiculo_id, "2026-09-01 10:00", "Primera")
        agenda.cancelar_cita(conn, cita_id)
        row = conn.execute("SELECT estado FROM citas WHERE id = ?", (cita_id,)).fetchone()
        assert row["estado"] == "cancelada"

    def test_cancelar_cita_inexistente_falla(self, conn):
        with pytest.raises(agenda.CitaNoEncontradaError):
            agenda.cancelar_cita(conn, 999)
