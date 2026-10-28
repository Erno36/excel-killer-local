"""
tests/test_cross.py — Pruebas del motor de cruce.

Cubre CA-04-01 a CA-04-06, RN-012 a RN-016.
NO importa nada de PySide6 (RT-06).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.models import CrossConfig, FileEntry, FileMetadata
from engine.cross import CrossConfigError, execute_cross


def make_entry(data: dict, label: str, path: str = "test.xlsx") -> FileEntry:
    """Helper: construye un FileEntry desde un dict."""
    df = pd.DataFrame(data)
    # Convertir todo a string para simular lectura desde Excel.
    df = df.astype(str)
    meta = FileMetadata(
        path=Path(path),
        sheet_names=["Sheet1"],
        sheet_used="Sheet1",
        row_count=len(df),
        column_names=list(df.columns),
    )
    return FileEntry(path=Path(path), label=label, sheet_index=0, df=df, metadata=meta)


class TestCruceBasico:
    def test_outer_join_produce_todas_las_filas(self):
        """CA-04-01: outer join incluye filas sin coincidencia."""
        entry_a = make_entry(
            {"CUIL": ["20-11111111-1", "20-22222222-2", "20-33333333-3"]},
            "ArchivoA",
        )
        entry_b = make_entry(
            {"CUIL": ["20-11111111-1", "20-22222222-2", "20-44444444-4"]},
            "ArchivoB",
        )
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("CUIL", "CUIL")],
            join_type="outer",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 4  # 2 coincidencias + 1 solo A + 1 solo B
        assert result.join_type == "outer"

    def test_inner_join_solo_coincidencias(self):
        """CA-04-01 variante inner: solo las filas con coincidencia."""
        entry_a = make_entry(
            {"CUIL": ["20-11111111-1", "20-22222222-2", "20-33333333-3"]},
            "A",
        )
        entry_b = make_entry(
            {"CUIL": ["20-11111111-1", "20-22222222-2", "20-44444444-4"]},
            "B",
        )
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("CUIL", "CUIL")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 2

    def test_left_join(self):
        """Left join conserva todas las filas del primer archivo."""
        entry_a = make_entry({"CUIL": ["A", "B", "C"]}, "Izquierda")
        entry_b = make_entry({"CUIL": ["A", "B"]}, "Derecha")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("CUIL", "CUIL")],
            join_type="left",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 3


class TestSinCoincidencias:
    def test_inner_sin_coincidencias(self):
        """CA-04-02: inner join sin coincidencias produce 0 filas y advertencia."""
        entry_a = make_entry({"CUIL": ["A", "B"]}, "A")
        entry_b = make_entry({"CUIL": ["C", "D"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("CUIL", "CUIL")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 0
        assert any("coincidencias" in w.lower() for w in result.warnings)


class TestNormalizacion:
    def test_normalizacion_activa_unifica_claves(self):
        """CA-04-03: normalización strip+lowercase une 'GARCIA ' con 'garcia'."""
        entry_a = make_entry({"nombre": ["  GARCIA  ", "PEREZ"]}, "A")
        entry_b = make_entry({"nombre": ["garcia", "lopez"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("nombre", "nombre")],
            join_type="inner",
            normalize_keys=True,
        )
        result = execute_cross(config)
        assert result.row_count == 1  # "GARCIA" == "garcia" tras normalizar

    def test_normalizacion_inactiva_es_case_sensitive(self):
        """Sin normalización, comparacion exacta."""
        entry_a = make_entry({"CUIL": ["  GARCIA  "]}, "A")
        entry_b = make_entry({"CUIL": ["garcia"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("CUIL", "CUIL")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 0


class TestErrores:
    def test_columna_inexistente_lanza_error(self):
        """CA-07-02: columna que no existe lanza CrossConfigError."""
        entry_a = make_entry({"CUIL": ["A"]}, "A")
        entry_b = make_entry({"CUIL": ["A"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("NoExiste", "CUIL")],
            join_type="inner",
            normalize_keys=False,
        )
        with pytest.raises(CrossConfigError) as exc_info:
            execute_cross(config)
        assert "noe" in str(exc_info.value).lower() or "noexiste" in str(exc_info.value).lower()

    def test_menos_de_dos_archivos(self):
        """Debe fallar con un solo archivo."""
        entry_a = make_entry({"CUIL": ["A"]}, "A")
        config = CrossConfig(
            file_entries=[entry_a],
            key_pairs=[],
            join_type="inner",
            normalize_keys=False,
        )
        with pytest.raises(CrossConfigError):
            execute_cross(config)

    def test_key_pairs_insuficientes(self):
        """N archivos pero N-2 pares de claves."""
        a = make_entry({"K": ["A"]}, "A")
        b = make_entry({"K": ["A"]}, "B")
        c = make_entry({"K": ["A"]}, "C")
        config = CrossConfig(
            file_entries=[a, b, c],
            key_pairs=[("K", "K")],  # necesita 2 pares, solo hay 1
            join_type="inner",
            normalize_keys=False,
        )
        with pytest.raises(CrossConfigError):
            execute_cross(config)


class TestIdempotencia:
    def test_mismo_resultado_en_dos_ejecuciones(self):
        """CA-04-05: idempotencia — el mismo cruce produce el mismo resultado."""
        entry_a = make_entry({"K": ["A", "B", "C"], "val_a": ["1", "2", "3"]}, "A")
        entry_b = make_entry({"K": ["A", "B", "D"], "val_b": ["x", "y", "z"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("K", "K")],
            join_type="outer",
            normalize_keys=False,
        )
        r1 = execute_cross(config)
        r2 = execute_cross(config)
        assert r1.row_count == r2.row_count
        assert list(r1.df.columns) == list(r2.df.columns)


class TestDryRun:
    def test_dry_run_no_produce_dataframe(self):
        """RNF-08: dry_run retorna CrossResult con df=None."""
        entry_a = make_entry({"K": ["A"]}, "A")
        entry_b = make_entry({"K": ["A"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("K", "K")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config, dry_run=True)
        assert result.df is None
        assert result.row_count >= 0


class TestTresArchivos:
    def test_cruce_tres_archivos(self):
        """Cruce de 3 archivos (cadena de joins)."""
        a = make_entry({"K": ["A", "B"], "v_a": ["1", "2"]}, "A")
        b = make_entry({"K": ["A", "B"], "v_b": ["x", "y"]}, "B")
        c = make_entry({"K": ["A", "C"], "v_c": ["p", "q"]}, "C")
        config = CrossConfig(
            file_entries=[a, b, c],
            key_pairs=[("K", "K"), ("K", "K")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        # A inner B = {A, B}; resultado inner C = {A}
        assert result.row_count == 1


class TestCasosEspeciales:
    def test_valores_cero_y_negativos_no_se_descartan(self):
        """CA-04-06: valores 0.00 y negativos se procesan."""
        entry_a = make_entry({"K": ["X"], "importe": ["0.00"]}, "A")
        entry_b = make_entry({"K": ["X"], "importe2": ["-150.50"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("K", "K")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 1
        assert "0.00" in result.df["importe"].values

    def test_clave_solo_espacios_sin_normalizacion(self):
        """Clave con solo espacios se trata como clave valida si no hay normalizacion."""
        entry_a = make_entry({"K": ["   ", "A"]}, "A")
        entry_b = make_entry({"K": ["   ", "B"]}, "B")
        config = CrossConfig(
            file_entries=[entry_a, entry_b],
            key_pairs=[("K", "K")],
            join_type="inner",
            normalize_keys=False,
        )
        result = execute_cross(config)
        assert result.row_count == 1  # "   " == "   "
