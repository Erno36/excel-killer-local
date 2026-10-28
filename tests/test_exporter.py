"""
tests/test_exporter.py — Pruebas del exportador a Excel.

Cubre CA-05-01 a CA-05-03, RN-017, RN-018.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.models import CrossResult
from engine.exporter import XlsxExporter


@pytest.fixture
def exporter():
    return XlsxExporter()


def make_result(rows: int = 5) -> CrossResult:
    df = pd.DataFrame({
        "CUIL": [f"20-{i:08d}-{i%9}" for i in range(rows)],
        "Nombre": [f"Nombre {i}" for i in range(rows)],
        "Importe": [str(i * 100.0) for i in range(rows)],
    })
    return CrossResult(
        df=df,
        row_count=rows,
        join_type="inner",
        columns_used=["CUIL"],
        warnings=[],
        duration_ms=10.0,
    )


class TestExportacion:
    def test_exportacion_exitosa(self, exporter, tmp_path):
        """CA-05-01: exportacion crea el archivo con la cantidad correcta de filas."""
        dest = tmp_path / "resultado.xlsx"
        result = make_result(100)
        outcome = exporter.export(result, dest, overwrite=False)

        assert dest.exists()
        assert outcome.rows_written == 100

        # Verificar leyendo el archivo exportado.
        df_check = pd.read_excel(dest)
        assert len(df_check) == 100

    def test_sobreescritura_con_overwrite_true(self, exporter, tmp_path):
        """CA-05-02: sobreescritura permitida con overwrite=True."""
        dest = tmp_path / "resultado.xlsx"
        make_result(5).df.to_excel(dest, index=False)  # crear archivo previo

        result = make_result(10)
        outcome = exporter.export(result, dest, overwrite=True)
        assert outcome.rows_written == 10

        df_check = pd.read_excel(dest)
        assert len(df_check) == 10

    def test_sin_overwrite_lanza_file_exists(self, exporter, tmp_path):
        """CA-05-02: sin overwrite, lanza FileExistsError si el archivo existe."""
        dest = tmp_path / "resultado.xlsx"
        dest.touch()

        with pytest.raises(FileExistsError):
            exporter.export(make_result(), dest, overwrite=False)

    def test_resultado_vacio_exporta_solo_encabezados(self, exporter, tmp_path):
        """CA-05-03: resultado con 0 filas genera archivo con solo encabezados."""
        dest = tmp_path / "vacio.xlsx"
        empty_result = CrossResult(
            df=pd.DataFrame(columns=["CUIL", "Nombre"]),
            row_count=0,
            join_type="inner",
            columns_used=["CUIL"],
            warnings=[],
            duration_ms=0.0,
        )
        outcome = exporter.export(empty_result, dest, overwrite=False)
        assert dest.exists()
        assert outcome.rows_written == 0
        df_check = pd.read_excel(dest)
        assert len(df_check) == 0
        assert "CUIL" in df_check.columns

    def test_dry_run_lanza_error(self, exporter, tmp_path):
        """Intentar exportar un resultado dry-run lanza ValueError."""
        dest = tmp_path / "nada.xlsx"
        dry_result = CrossResult(
            df=None,
            row_count=0,
            join_type="inner",
            columns_used=[],
            warnings=[],
            duration_ms=0.0,
        )
        with pytest.raises(ValueError):
            exporter.export(dry_result, dest)


class TestSanitizacion:
    def test_neutraliza_formula_excel(self, exporter, tmp_path):
        """La exportacion neutraliza strings que comienzan con = (inyeccion de formulas)."""
        df = pd.DataFrame({"col": ["=1+1", "+malicious", "@sum", "valor_normal"]})
        result = CrossResult(
            df=df,
            row_count=4,
            join_type="inner",
            columns_used=["col"],
            warnings=[],
            duration_ms=0.0,
        )
        dest = tmp_path / "sanitizado.xlsx"
        exporter.export(result, dest)

        df_check = pd.read_excel(dest, dtype=str)
        assert df_check["col"].iloc[0].startswith("'") or not df_check["col"].iloc[0].startswith("=")
        assert "valor_normal" in df_check["col"].values

    def test_float_negativo_no_se_corrompe(self, exporter):
        """DEF-001: un float negativo debe devolverse sin modificacion."""
        result = XlsxExporter._sanitize_value(-150.50)
        assert result == -150.50
        assert isinstance(result, float)

    def test_int_negativo_no_se_corrompe(self, exporter):
        """DEF-001: un int negativo debe devolverse sin modificacion."""
        result = XlsxExporter._sanitize_value(-42)
        assert result == -42
        assert isinstance(result, int)

    def test_float_positivo_no_se_modifica(self, exporter):
        """Los floats positivos tambien se devuelven sin modificacion."""
        result = XlsxExporter._sanitize_value(99.99)
        assert result == 99.99

    def test_string_formula_se_sanitiza(self, exporter):
        """DEF-001: un string que empieza con = debe sanitizarse con apostrofe."""
        result = XlsxExporter._sanitize_value("=SUMA(A1:A10)")
        assert result == "'=SUMA(A1:A10)"

    @pytest.mark.parametrize("value", ["-formula", "\t=1+1", "\r@SUMA(A1)"])
    def test_prefijos_adicionales_de_formula_se_sanitizan(self, value):
        assert XlsxExporter._sanitize_value(value) == "'" + value

    def test_exportacion_con_importes_negativos(self, exporter, tmp_path):
        """DEF-001: exportar un DataFrame con importes float negativos no los corrompe."""
        df = pd.DataFrame({
            "Cuenta": ["101", "202"],
            "Importe": [-150.50, -3000.00],
        })
        result = CrossResult(
            df=df,
            row_count=2,
            join_type="inner",
            columns_used=["Cuenta"],
            warnings=[],
            duration_ms=0.0,
        )
        dest = tmp_path / "negativos.xlsx"
        exporter.export(result, dest)

        df_check = pd.read_excel(dest)
        assert df_check["Importe"].iloc[0] == -150.50
        assert df_check["Importe"].iloc[1] == -3000.00
