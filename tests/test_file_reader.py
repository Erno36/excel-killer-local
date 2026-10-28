"""
tests/test_file_reader.py — Pruebas del lector de archivos Excel.

Cubre CA-02-01 a CA-02-06, CA-03-01 a CA-03-04.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from engine.reader import EmptyFileError, ExcelFileReader, FileReadError


@pytest.fixture
def reader():
    return ExcelFileReader()


class TestLecturaBasica:
    def test_lee_excel_valido(self, reader, excel_seguros):
        """CA-02-01 / CA-03-01: lee archivo valido y detecta columnas."""
        df, meta = reader.read(excel_seguros)
        assert not df.empty
        assert "CUIL" in df.columns
        assert "nombre_producto" in df.columns
        assert meta.row_count == 4

    def test_columnas_detectadas_correctamente(self, reader, excel_seguros):
        """CA-03-01: columnas detectadas son exactamente las del archivo."""
        df, meta = reader.read(excel_seguros)
        expected = ["CUIL", "nombre_producto", "estado", "broker", "importe_prima"]
        assert meta.column_names == expected

    def test_sheet_names_detectadas(self, reader, excel_seguros):
        """El metadata incluye la lista de hojas."""
        _, meta = reader.read(excel_seguros)
        assert len(meta.sheet_names) >= 1
        assert meta.sheet_used in meta.sheet_names

    def test_multiple_sheets(self, reader, tmp_path):
        """Seleccion de hoja por indice."""
        path = tmp_path / "multi.xlsx"
        with pd.ExcelWriter(path) as w:
            pd.DataFrame({"A": [1]}).to_excel(w, sheet_name="Hoja1", index=False)
            pd.DataFrame({"B": [2]}).to_excel(w, sheet_name="Hoja2", index=False)

        _, meta0 = reader.read(path, sheet_index=0)
        _, meta1 = reader.read(path, sheet_index=1)

        assert meta0.sheet_used == "Hoja1"
        assert meta1.sheet_used == "Hoja2"

    def test_inspecciona_solo_primeras_filas_para_encabezado(self, reader, tmp_path):
        path = tmp_path / "encabezado_inspeccion.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame([
                ["Reporte", None],
                ["Codigo", "Estado"],
                ["001", "Activo"],
            ]).to_excel(writer, header=False, index=False)

        candidates, scanned_rows = reader.inspect_header_rows(path)

        assert candidates[0] == 1
        assert scanned_rows == 3

    def test_detecta_encabezado_por_separado_en_cada_hoja(self, reader, tmp_path):
        path = tmp_path / "encabezados_por_hoja.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame([["ID", "Estado"], ["1", "OK"]]).to_excel(
                writer, sheet_name="Hoja1", header=False, index=False
            )
            pd.DataFrame([
                ["Reporte", None],
                ["ID", "Estado"],
                ["2", "OK"],
            ]).to_excel(writer, sheet_name="Hoja2", header=False, index=False)

        dataframe, metadata = reader.read(path, sheet_index=-1)

        assert len(dataframe) == 2
        assert metadata.sheet_used == "Todas las hojas"
        assert any("fila 2" in warning for warning in metadata.warnings)

    def test_detecta_encabezado_debajo_de_filas_informativas(self, reader, tmp_path):
        path = tmp_path / "encabezado_demorado.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame([
                ["Reporte mensual", None, None],
                ["Generado por Operaciones", None, None],
                ["CUIL", "Estado", "Importe"],
                ["20123456789", "Activo", "1.250,00"],
                ["20234567890", "Baja", "950,00"],
            ]).to_excel(writer, sheet_name="Datos", header=False, index=False)

        df, metadata = reader.read(path)

        assert metadata.header_row_index == 2
        assert metadata.column_names == ["CUIL", "Estado", "Importe"]
        assert len(df) == 2
        assert any("fila 3" in warning for warning in metadata.warnings)

    def test_permite_corregir_fila_de_encabezado(self, reader, tmp_path):
        path = tmp_path / "correccion_encabezado.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame([
                ["Informe", None],
                ["Identificador", "Resultado"],
                ["00123", "OK"],
            ]).to_excel(writer, header=False, index=False)

        df, metadata = reader.read(path, header_row=1)

        assert metadata.header_row_index == 1
        assert metadata.column_names == ["Identificador", "Resultado"]
        assert len(df) == 1

    def test_rechaza_fila_de_encabezado_fuera_de_rango(self, reader, excel_seguros):
        with pytest.raises(FileReadError, match="fila de encabezado"):
            reader.read(excel_seguros, header_row=20)


class TestFormatosYErrores:
    def test_formato_no_soportado(self, reader, tmp_path):
        """CA-02-03: formato no Excel lanza FileReadError."""
        bad_file = tmp_path / "reporte.pdf"
        bad_file.write_text("contenido")
        with pytest.raises(FileReadError) as exc_info:
            reader.read(bad_file)
        assert "no soportado" in str(exc_info.value).lower()

    def test_archivo_vacio_lanza_empty_error(self, reader, excel_empty):
        """CA-02-04: archivo sin datos lanza EmptyFileError."""
        with pytest.raises(EmptyFileError) as exc_info:
            reader.read(excel_empty)
        assert "no tiene datos" in str(exc_info.value).lower() or "vacio" in str(exc_info.value).lower()

    def test_archivo_corrupto(self, reader, tmp_path):
        """CA-07-01: archivo con extension xlsx pero contenido corrupto."""
        bad = tmp_path / "corrupto.xlsx"
        bad.write_bytes(b"esto no es un excel")
        with pytest.raises(FileReadError) as exc_info:
            reader.read(bad)
        assert "no pudo leerse" in str(exc_info.value).lower()

    def test_archivo_inexistente(self, reader, tmp_path):
        """Archivo que no existe lanza FileReadError."""
        missing = tmp_path / "no_existe.xlsx"
        with pytest.raises(FileReadError):
            reader.read(missing)


class TestNormalizacionEncabezados:
    def test_columna_sin_encabezado(self, reader, tmp_path):
        """CA-03-03: columna sin nombre recibe nombre generado."""
        import openpyxl
        path = tmp_path / "sin_encabezado.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["CUIL", None, "Nombre"])
        ws.append(["20-11111111-1", "valor", "Juan"])
        wb.save(path)

        df, meta = reader.read(path)
        # La segunda columna no tiene nombre; debe recibir uno generado.
        assert "Columna_B" in meta.column_names
        assert len(meta.warnings) > 0

    def test_columnas_duplicadas(self, reader, excel_with_duplicates):
        """CA-03-04: columnas duplicadas se desambiguan con sufijo."""
        df, meta = reader.read(excel_with_duplicates)
        # Debe haber dos columnas "Importe" con sufijos.
        importe_cols = [c for c in meta.column_names if "Importe" in c]
        assert len(importe_cols) == 2
        assert len(set(importe_cols)) == 2  # son distintas
        assert len(meta.warnings) > 0

    def test_columnas_con_acentos(self, reader, tmp_path):
        """CA-03-02: acentos y caracteres especiales se preservan."""
        import openpyxl
        path = tmp_path / "acentos.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Numero de poliza", "Razon social", "Codigo_1"])
        ws.append(["P001", "Garcia & Cia", "C1"])
        wb.save(path)

        df, meta = reader.read(path)
        assert "Numero de poliza" in meta.column_names
        assert "Razon social" in meta.column_names
        assert "Codigo_1" in meta.column_names
