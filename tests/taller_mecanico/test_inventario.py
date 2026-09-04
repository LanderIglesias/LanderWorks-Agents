import sqlite3

import pytest

from backend.agents.taller_mecanico import db as tm_db
from backend.agents.taller_mecanico import inventario


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "taller_mecanico.db"
    monkeypatch.setattr(tm_db, "DB_PATH", db_path)
    connection = tm_db.get_conn()
    yield connection
    connection.close()


class TestAltaPieza:
    def test_alta_pieza_basica(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas de freno", precio_unitario=30.0)
        row = conn.execute("SELECT * FROM piezas WHERE id = ?", (pieza_id,)).fetchone()
        assert row["nombre"] == "Pastillas de freno"
        assert row["stock"] == 0
        assert row["stock_minimo"] == 0
        assert row["precio_unitario"] == 30.0

    def test_alta_pieza_con_stock_inicial_y_minimo(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Discos de freno", precio_unitario=60.0, stock_inicial=10, stock_minimo=3
        )
        row = conn.execute("SELECT * FROM piezas WHERE id = ?", (pieza_id,)).fetchone()
        assert row["stock"] == 10
        assert row["stock_minimo"] == 3

    def test_alta_pieza_referencia_duplicada_falla(self, conn):
        inventario.alta_pieza(conn, "Pastillas", precio_unitario=30.0, referencia="REF-1")
        with pytest.raises(sqlite3.IntegrityError):
            inventario.alta_pieza(conn, "Discos", precio_unitario=60.0, referencia="REF-1")

    def test_alta_pieza_precio_negativo_falla(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            inventario.alta_pieza(conn, "Pastillas", precio_unitario=-5.0)


class TestConsultarStock:
    def test_consultar_stock_pieza_existente(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=30.0, stock_inicial=5)
        assert inventario.consultar_stock(conn, pieza_id) == 5

    def test_consultar_stock_pieza_inexistente_falla(self, conn):
        with pytest.raises(inventario.PiezaNoEncontradaError):
            inventario.consultar_stock(conn, 999)


class TestDescontarStock:
    def test_descontar_stock_disponible(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=30.0, stock_inicial=10)
        inventario.descontar_stock(conn, pieza_id, cantidad=4)
        assert inventario.consultar_stock(conn, pieza_id) == 6

    def test_descontar_mas_stock_del_disponible_falla(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=30.0, stock_inicial=3)
        with pytest.raises(inventario.StockInsuficienteError):
            inventario.descontar_stock(conn, pieza_id, cantidad=4)
        # El stock no debe quedar tocado ni en negativo tras el rechazo.
        assert inventario.consultar_stock(conn, pieza_id) == 3

    def test_descontar_cantidad_no_positiva_falla(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=30.0, stock_inicial=3)
        with pytest.raises(ValueError):
            inventario.descontar_stock(conn, pieza_id, cantidad=0)

    def test_descontar_pieza_inexistente_falla(self, conn):
        with pytest.raises(inventario.PiezaNoEncontradaError):
            inventario.descontar_stock(conn, 999, cantidad=1)


class TestAlertaStockBajoMinimo:
    def test_stock_por_encima_del_minimo_no_alerta(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=10, stock_minimo=3
        )
        assert inventario.necesita_reposicion(conn, pieza_id) is False

    def test_stock_igual_al_minimo_alerta(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=3, stock_minimo=3
        )
        assert inventario.necesita_reposicion(conn, pieza_id) is True

    def test_stock_por_debajo_del_minimo_alerta(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=1, stock_minimo=3
        )
        assert inventario.necesita_reposicion(conn, pieza_id) is True

    def test_descontar_hasta_bajo_minimo_dispara_alerta(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=5, stock_minimo=3
        )
        assert inventario.necesita_reposicion(conn, pieza_id) is False
        inventario.descontar_stock(conn, pieza_id, cantidad=3)
        assert inventario.necesita_reposicion(conn, pieza_id) is True

    def test_listar_piezas_bajo_minimo(self, conn):
        bien_surtida = inventario.alta_pieza(
            conn, "Filtro aceite", precio_unitario=10.0, stock_inicial=20, stock_minimo=5
        )
        baja_de_stock = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=2, stock_minimo=5
        )
        alertas = inventario.listar_piezas_bajo_minimo(conn)
        ids_en_alerta = {p["id"] for p in alertas}
        assert baja_de_stock in ids_en_alerta
        assert bien_surtida not in ids_en_alerta


class TestAltaPiezaEsCompatible:
    def test_alta_pieza_original_por_defecto(self, conn):
        pieza_id = inventario.alta_pieza(conn, "Pastillas Bosch", precio_unitario=30.0)
        pieza = inventario.obtener_pieza(conn, pieza_id)
        assert pieza["es_compatible"] == 0

    def test_alta_pieza_compatible_explicita(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas Ferodo", precio_unitario=20.0, es_compatible=1
        )
        pieza = inventario.obtener_pieza(conn, pieza_id)
        assert pieza["es_compatible"] == 1


class TestObtenerPieza:
    def test_obtener_pieza_existente(self, conn):
        pieza_id = inventario.alta_pieza(
            conn, "Pastillas", precio_unitario=30.0, stock_inicial=5, referencia="REF-1"
        )
        pieza = inventario.obtener_pieza(conn, pieza_id)
        assert pieza["id"] == pieza_id
        assert pieza["nombre"] == "Pastillas"
        assert pieza["precio_unitario"] == 30.0
        assert pieza["referencia"] == "REF-1"

    def test_obtener_pieza_inexistente_falla(self, conn):
        with pytest.raises(inventario.PiezaNoEncontradaError):
            inventario.obtener_pieza(conn, 999)
