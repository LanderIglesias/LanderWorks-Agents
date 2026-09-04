import sqlite3

import pytest

from backend.agents.taller_mecanico import crm, crypto_utils

# `conn` y `crypto_env` (autouse) viven en conftest.py -- compartidos con
# el resto de tests de taller_mecanico.


class TestAltaCliente:
    def test_alta_cliente_basico(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        assert crypto_utils.decrypt(row["nombre_encrypted"]) == "Ana García"
        assert crypto_utils.decrypt(row["telefono_encrypted"]) == "600111222"
        assert row["telefono_hash"] == crypto_utils.hash_for_lookup("600111222")

    def test_alta_cliente_con_email_y_direccion(self, conn):
        cliente_id = crm.alta_cliente(
            conn,
            nombre="Ana García",
            telefono="600111222",
            email="ana@example.com",
            direccion="Calle Falsa 123",
        )
        row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        assert crypto_utils.decrypt(row["email_encrypted"]) == "ana@example.com"
        assert crypto_utils.decrypt(row["direccion_encrypted"]) == "Calle Falsa 123"

    def test_alta_cliente_sin_email_ni_direccion(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        assert row["email_encrypted"] is None
        assert row["direccion_encrypted"] is None

    def test_alta_cliente_telefono_duplicado_rechazada_via_hash(self, conn):
        crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        with pytest.raises(crm.ClienteDuplicadoError):
            crm.alta_cliente(conn, nombre="Otra Ana", telefono="600111222")
        # Debe seguir habiendo solo un cliente -- no hay bypass del cifrado
        # (dos ciphertexts distintos para el mismo teléfono real no cuelan).
        count = conn.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()["n"]
        assert count == 1

    def test_alta_cliente_telefono_con_espacios_es_consistente(self, conn):
        # encrypt() no normaliza espacios pero hash_for_lookup() sí -- si
        # alta_cliente no normalizara telefono antes de ambas llamadas, el
        # valor descifrado y el valor usado para buscar podrían divergir.
        crm.alta_cliente(conn, nombre="Ana García", telefono="  600111222  ")
        encontrado = crm.buscar_cliente_por_telefono(conn, "600111222")
        assert encontrado is not None
        assert encontrado["telefono"] == "600111222"

    def test_alta_cliente_no_deja_filas_a_medias_tras_duplicado(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        with pytest.raises(crm.ClienteDuplicadoError):
            crm.alta_cliente(conn, nombre="Otra Ana", telefono="600111222")
        row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        assert crypto_utils.decrypt(row["nombre_encrypted"]) == "Ana García"


class TestObtenerCliente:
    def test_obtener_cliente_descifra_los_campos(self, conn):
        cliente_id = crm.alta_cliente(
            conn, nombre="Ana García", telefono="600111222", email="ana@example.com"
        )
        cliente = crm.obtener_cliente(conn, cliente_id)
        assert cliente["nombre"] == "Ana García"
        assert cliente["telefono"] == "600111222"
        assert cliente["email"] == "ana@example.com"
        assert cliente["direccion"] is None

    def test_obtener_cliente_inexistente_falla(self, conn):
        with pytest.raises(crm.ClienteNoEncontradoError):
            crm.obtener_cliente(conn, 999)


class TestBuscarClientePorTelefono:
    def test_encuentra_cliente_existente(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        encontrado = crm.buscar_cliente_por_telefono(conn, "600111222")
        assert encontrado is not None
        assert encontrado["id"] == cliente_id
        assert encontrado["nombre"] == "Ana García"

    def test_no_encuentra_telefono_inexistente(self, conn):
        assert crm.buscar_cliente_por_telefono(conn, "600999999") is None


class TestAltaVehiculo:
    def test_alta_vehiculo_vinculado_a_cliente(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        vehiculo_id = crm.alta_vehiculo(
            conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza"
        )
        row = conn.execute("SELECT * FROM vehiculos WHERE id = ?", (vehiculo_id,)).fetchone()
        assert row["cliente_id"] == cliente_id
        assert row["matricula"] == "1234ABC"

    def test_alta_vehiculo_cliente_inexistente_falla(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            crm.alta_vehiculo(conn, 999, matricula="1234ABC", marca="Seat", modelo="Ibiza")

    def test_alta_vehiculo_matricula_duplicada_falla(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        crm.alta_vehiculo(conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza")
        with pytest.raises(sqlite3.IntegrityError):
            crm.alta_vehiculo(conn, cliente_id, matricula="1234ABC", marca="Renault", modelo="Clio")


class TestObtenerVehiculo:
    def test_obtener_vehiculo_existente(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        vehiculo_id = crm.alta_vehiculo(
            conn,
            cliente_id,
            matricula="1234ABC",
            marca="Seat",
            modelo="Ibiza",
            anio=2018,
            kilometraje=85000,
        )
        vehiculo = crm.obtener_vehiculo(conn, vehiculo_id)
        assert vehiculo["id"] == vehiculo_id
        assert vehiculo["cliente_id"] == cliente_id
        assert vehiculo["matricula"] == "1234ABC"
        assert vehiculo["marca"] == "Seat"
        assert vehiculo["modelo"] == "Ibiza"
        assert vehiculo["anio"] == 2018
        assert vehiculo["kilometraje"] == 85000

    def test_obtener_vehiculo_inexistente_falla(self, conn):
        with pytest.raises(crm.VehiculoNoEncontradoError):
            crm.obtener_vehiculo(conn, 999)


class TestHistorialVehiculo:
    def test_historial_sin_citas_previas_devuelve_lista_vacia(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        vehiculo_id = crm.alta_vehiculo(
            conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza"
        )
        assert crm.historial_vehiculo(conn, vehiculo_id) == []

    def test_historial_devuelve_citas_pasadas_ordenadas(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        vehiculo_id = crm.alta_vehiculo(
            conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza"
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-01-10 09:00', 'ITV')",
            (vehiculo_id,),
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-03-05 09:00', 'Ruido al frenar')",
            (vehiculo_id,),
        )
        conn.commit()

        historial = crm.historial_vehiculo(conn, vehiculo_id)
        assert [c["motivo"] for c in historial] == ["Ruido al frenar", "ITV"]

    def test_historial_vehiculo_inexistente_falla(self, conn):
        with pytest.raises(crm.VehiculoNoEncontradoError):
            crm.historial_vehiculo(conn, 999)


class TestContarVisitasCompletadasCliente:
    def test_cliente_sin_citas_devuelve_cero(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        assert crm.contar_visitas_completadas_cliente(conn, cliente_id) == 0

    def test_cuenta_solo_citas_completadas(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        vehiculo_id = crm.alta_vehiculo(
            conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza"
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            "VALUES (?, '2026-01-01 09:00', 'ITV', 'completada')",
            (vehiculo_id,),
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            "VALUES (?, '2026-02-01 09:00', 'Revisión', 'completada')",
            (vehiculo_id,),
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            "VALUES (?, '2026-03-01 09:00', 'Pendiente', 'pendiente')",
            (vehiculo_id,),
        )
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            "VALUES (?, '2026-04-01 09:00', 'Cancelada', 'cancelada')",
            (vehiculo_id,),
        )
        conn.commit()
        assert crm.contar_visitas_completadas_cliente(conn, cliente_id) == 2

    def test_suma_visitas_de_todos_los_vehiculos_del_cliente(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        v1 = crm.alta_vehiculo(conn, cliente_id, matricula="1111AAA", marca="Seat", modelo="Ibiza")
        v2 = crm.alta_vehiculo(conn, cliente_id, matricula="2222BBB", marca="Seat", modelo="Leon")
        for v in (v1, v2):
            conn.execute(
                "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
                "VALUES (?, '2026-01-01 09:00', 'ITV', 'completada')",
                (v,),
            )
        conn.commit()
        assert crm.contar_visitas_completadas_cliente(conn, cliente_id) == 2

    def test_cliente_inexistente_falla(self, conn):
        with pytest.raises(crm.ClienteNoEncontradoError):
            crm.contar_visitas_completadas_cliente(conn, 999)


class TestQuejas:
    def test_registrar_queja(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        queja_id = crm.registrar_queja(conn, cliente_id, "No me llamaron para confirmar la cita")
        row = conn.execute("SELECT * FROM quejas WHERE id = ?", (queja_id,)).fetchone()
        assert row["cliente_id"] == cliente_id
        assert row["resuelta"] == 0

    def test_registrar_queja_cliente_inexistente_falla(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            crm.registrar_queja(conn, 999, "x")

    def test_tiene_queja_no_resuelta_false_sin_quejas(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        assert crm.tiene_queja_no_resuelta(conn, cliente_id) is False

    def test_tiene_queja_no_resuelta_true_tras_registrar(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        crm.registrar_queja(conn, cliente_id, "x")
        assert crm.tiene_queja_no_resuelta(conn, cliente_id) is True

    def test_tiene_queja_no_resuelta_false_si_ya_resuelta(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        queja_id = crm.registrar_queja(conn, cliente_id, "x")
        conn.execute("UPDATE quejas SET resuelta = 1 WHERE id = ?", (queja_id,))
        conn.commit()
        assert crm.tiene_queja_no_resuelta(conn, cliente_id) is False

    def test_tiene_queja_no_resuelta_cliente_inexistente_falla(self, conn):
        with pytest.raises(crm.ClienteNoEncontradoError):
            crm.tiene_queja_no_resuelta(conn, 999)

    def test_resolver_queja_la_marca_resuelta(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        queja_id = crm.registrar_queja(conn, cliente_id, "x")
        crm.resolver_queja(conn, queja_id)
        row = conn.execute("SELECT resuelta FROM quejas WHERE id = ?", (queja_id,)).fetchone()
        assert row["resuelta"] == 1
        assert crm.tiene_queja_no_resuelta(conn, cliente_id) is False

    def test_resolver_queja_inexistente_falla(self, conn):
        with pytest.raises(crm.QuejaNoEncontradaError):
            crm.resolver_queja(conn, 999)

    def test_resolver_una_queja_no_afecta_a_otra_sin_resolver(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
        queja_1_id = crm.registrar_queja(conn, cliente_id, "primera")
        crm.registrar_queja(conn, cliente_id, "segunda")
        crm.resolver_queja(conn, queja_1_id)
        # Sigue habiendo una queja sin resolver (la segunda).
        assert crm.tiene_queja_no_resuelta(conn, cliente_id) is True
