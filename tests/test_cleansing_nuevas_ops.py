"""
tests/test_cleansing_nuevas_ops.py — Pruebas de las nuevas operaciones de
engine/cleansing.py: drop_column y filter_date_*.

Datos sinteticos exclusivamente. Sin datos reales ni derivados de datos reales.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.models import FileEntry, FileMetadata
from engine.cleansing import (
    CleansingRule,
    apply_all_rules,
    apply_rule,
    preview_rule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(label: str, data: dict) -> FileEntry:
    df = pd.DataFrame(data)
    return FileEntry(
        path=None,
        label=label,
        sheet_index=0,
        df=df,
        metadata=FileMetadata(
            path=None,
            sheet_names=["Hoja1"],
            sheet_used="Hoja1",
            row_count=len(df),
            column_names=list(df.columns),
        ),
        is_virtual=True,
    )


def _rule(op: str, params: dict | None = None,
          file_label: str = "A", column: str = "fecha") -> CleansingRule:
    return CleansingRule.new(
        file_label=file_label, column=column, operation=op, params=params or {}
    )


# ===========================================================================
# drop_column
# ===========================================================================

class TestDropColumn:

    def test_drop_column_elimina_columna(self):
        """drop_column elimina la columna del DataFrame."""
        entry = _make_entry("A", {"col1": [1, 2], "col2": ["a", "b"]})
        rules = [CleansingRule.new("A", "col1", "drop_column")]
        result = apply_all_rules([entry], rules)
        assert "col1" not in result[0].df.columns
        assert "col2" in result[0].df.columns
        assert result[0].metadata.column_names == ["col2"]

    def test_drop_column_no_modifica_original(self):
        """El FileEntry original no muta."""
        entry = _make_entry("A", {"col1": [1, 2], "col2": ["a", "b"]})
        rules = [CleansingRule.new("A", "col1", "drop_column")]
        apply_all_rules([entry], rules)
        assert "col1" in entry.df.columns

    def test_drop_column_columna_inexistente_no_crashea(self):
        """Si la columna no existe, no lanza excepcion."""
        entry = _make_entry("A", {"col1": [1, 2]})
        rules = [CleansingRule.new("A", "COLUMNA_INEXISTENTE", "drop_column")]
        result = apply_all_rules([entry], rules)
        assert list(result[0].df.columns) == ["col1"]

    def test_drop_column_multiples_columnas(self):
        """Dos reglas drop_column eliminan dos columnas distintas."""
        entry = _make_entry("A", {"a": [1], "b": [2], "c": [3]})
        rules = [
            CleansingRule.new("A", "a", "drop_column"),
            CleansingRule.new("A", "b", "drop_column"),
        ]
        result = apply_all_rules([entry], rules)
        assert list(result[0].df.columns) == ["c"]

    def test_drop_column_no_afecta_otro_archivo(self):
        """drop_column en A no afecta el archivo B."""
        entry_a = _make_entry("A", {"col": [1], "extra": [2]})
        entry_b = _make_entry("B", {"col": [3], "extra": [4]})
        rules = [CleansingRule.new("A", "extra", "drop_column")]
        result = apply_all_rules([entry_a, entry_b], rules)
        assert "extra" not in result[0].df.columns  # A sin extra
        assert "extra" in result[1].df.columns      # B intacto

    def test_apply_rule_drop_column_lanza_not_implemented(self):
        """apply_rule con drop_column lanza NotImplementedError."""
        import pandas as pd
        s = pd.Series(["a", "b"])
        rule = _rule("drop_column", column="col")
        with pytest.raises(NotImplementedError, match="DataFrame"):
            apply_rule(s, rule)

    def test_preview_rule_drop_column_retorna_descripcion(self):
        """preview_rule para drop_column retorna descripcion sintetica."""
        rule = _rule("drop_column")
        pairs = preview_rule(None, rule)
        assert len(pairs) == 1
        before, after = pairs[0]
        assert "eliminada" in before.lower()


# ===========================================================================
# filter_date_before
# ===========================================================================

class TestFilterDateBefore:

    def _entry_con_fechas(self) -> FileEntry:
        return _make_entry("A", {
            "fecha": [
                "01/01/2024",
                "15/06/2024",
                "31/12/2024",
                "01/01/2025",
                "texto-invalido",
            ],
            "codigo": ["A", "B", "C", "D", "E"],
        })

    def test_retiene_filas_menores_o_iguales(self):
        """filter_date_before retiene filas con fecha <= limite."""
        entry = self._entry_con_fechas()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_before", {"date": "15/06/2024"}
        )]
        result = apply_all_rules([entry], rules)
        codigos = list(result[0].df["codigo"])
        assert set(codigos) == {"A", "B"}

    def test_fecha_invalida_en_params_no_filtra(self):
        """Si la fecha en params no parsea, no se filtra ninguna fila."""
        entry = self._entry_con_fechas()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_before", {"date": "no-parseable"}
        )]
        result = apply_all_rules([entry], rules)
        # Sin fecha valida: todas las filas se conservan
        assert len(result[0].df) == 5

    def test_celdas_invalidas_se_excluyen(self):
        """Filas con valores no parseables como fecha se excluyen del resultado."""
        entry = self._entry_con_fechas()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_before", {"date": "31/12/2025"}
        )]
        result = apply_all_rules([entry], rules)
        assert "texto-invalido" not in result[0].df["fecha"].values

    def test_no_modifica_original(self):
        """El DataFrame original no muta."""
        entry = self._entry_con_fechas()
        original_len = len(entry.df)
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_before", {"date": "15/06/2024"}
        )]
        apply_all_rules([entry], rules)
        assert len(entry.df) == original_len

    def test_apply_rule_lanza_not_implemented(self):
        """apply_rule con filter_date_before lanza NotImplementedError."""
        s = pd.Series(["01/01/2024"])
        rule = _rule("filter_date_before", {"date": "01/01/2025"})
        with pytest.raises(NotImplementedError):
            apply_rule(s, rule)

    def test_preview_rule_retorna_descripcion(self):
        """preview_rule para filter_date_before retorna descripcion sintetica."""
        rule = _rule("filter_date_before", {"date": "01/01/2025"})
        pairs = preview_rule(None, rule)
        assert len(pairs) == 1
        before, _ = pairs[0]
        assert "fecha" in before.lower()


# ===========================================================================
# filter_date_after
# ===========================================================================

class TestFilterDateAfter:

    def _entry(self) -> FileEntry:
        return _make_entry("A", {
            "fecha": ["01/01/2024", "15/06/2024", "31/12/2024", "01/01/2025"],
            "id": [1, 2, 3, 4],
        })

    def test_retiene_filas_mayores_o_iguales(self):
        """filter_date_after retiene filas con fecha >= limite."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_after", {"date": "15/06/2024"}
        )]
        result = apply_all_rules([entry], rules)
        ids = list(result[0].df["id"])
        # 15/06/2024, 31/12/2024, 01/01/2025
        assert set(ids) == {2, 3, 4}

    def test_fecha_invalida_no_filtra(self):
        """Fecha invalida en params: no filtra."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_after", {"date": "INVALIDO"}
        )]
        result = apply_all_rules([entry], rules)
        assert len(result[0].df) == 4


# ===========================================================================
# filter_date_range
# ===========================================================================

class TestFilterDateRange:

    def _entry(self) -> FileEntry:
        return _make_entry("A", {
            "fecha": [
                "01/01/2024",
                "15/06/2024",
                "31/12/2024",
                "01/01/2025",
                "15/06/2025",
            ],
            "id": [1, 2, 3, 4, 5],
        })

    def test_retiene_rango_inclusivo(self):
        """filter_date_range retiene filas con desde <= fecha <= hasta."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_range",
            {"date_from": "15/06/2024", "date_to": "01/01/2025"},
        )]
        result = apply_all_rules([entry], rules)
        ids = list(result[0].df["id"])
        assert set(ids) == {2, 3, 4}

    def test_rango_de_un_dia(self):
        """Rango de un dia retiene solo esa fecha."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_range",
            {"date_from": "15/06/2024", "date_to": "15/06/2024"},
        )]
        result = apply_all_rules([entry], rules)
        assert len(result[0].df) == 1
        assert result[0].df.iloc[0]["id"] == 2

    def test_date_from_invalido_no_filtra(self):
        """date_from invalido: no filtra."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_range",
            {"date_from": "NO-FECHA", "date_to": "31/12/2024"},
        )]
        result = apply_all_rules([entry], rules)
        assert len(result[0].df) == 5

    def test_date_to_invalido_no_filtra(self):
        """date_to invalido: no filtra."""
        entry = self._entry()
        rules = [CleansingRule.new(
            "A", "fecha", "filter_date_range",
            {"date_from": "01/01/2024", "date_to": "NO-FECHA"},
        )]
        result = apply_all_rules([entry], rules)
        assert len(result[0].df) == 5

    def test_preview_rule_retorna_descripcion(self):
        """preview_rule para filter_date_range retorna descripcion sintetica."""
        rule = CleansingRule.new(
            "A", "fecha", "filter_date_range",
            {"date_from": "01/01/2024", "date_to": "31/12/2024"},
        )
        pairs = preview_rule(None, rule)
        assert len(pairs) == 1
        before, _ = pairs[0]
        assert "fecha" in before.lower()


# ===========================================================================
# Encadenamiento con otras operaciones
# ===========================================================================

class TestEncadenamiento:
    def test_drop_column_y_strip_spaces(self):
        """drop_column y strip_spaces en distintas columnas del mismo archivo."""
        entry = _make_entry("A", {
            "nombre": ["  juan  ", "  ana  "],
            "extra":  ["x", "y"],
        })
        rules = [
            CleansingRule.new("A", "extra", "drop_column"),
            CleansingRule.new("A", "nombre", "strip_spaces"),
        ]
        result = apply_all_rules([entry], rules)
        assert "extra" not in result[0].df.columns
        assert result[0].df["nombre"][0] == "juan"

    def test_filter_date_y_strip_spaces(self):
        """filter_date_before aplicado y luego strip_spaces sobre otra columna."""
        entry = _make_entry("A", {
            "fecha":  ["01/01/2024", "31/12/2024", "01/01/2025"],
            "nombre": ["  juan  ", "  ana  ", "  pedro  "],
        })
        rules = [
            CleansingRule.new("A", "fecha", "filter_date_before", {"date": "31/12/2024"}),
            CleansingRule.new("A", "nombre", "strip_spaces"),
        ]
        result = apply_all_rules([entry], rules)
        # Solo 2 filas quedan (01/01/2024 y 31/12/2024)
        assert len(result[0].df) == 2
        assert result[0].df["nombre"].iloc[0] == "juan"

    def test_drop_column_antes_de_filtro_en_columna_eliminada(self):
        """
        Si drop_column elimina una columna y luego otra regla la usa,
        la segunda regla se ignora silenciosamente.
        """
        entry = _make_entry("A", {
            "fecha":  ["01/01/2024", "31/12/2024"],
            "codigo": ["A", "B"],
        })
        rules = [
            CleansingRule.new("A", "fecha", "drop_column"),
            # Esta regla sobre "fecha" (ya eliminada) debe ignorarse sin crashear.
            CleansingRule.new("A", "fecha", "strip_spaces"),
        ]
        result = apply_all_rules([entry], rules)
        assert "fecha" not in result[0].df.columns
        assert "codigo" in result[0].df.columns


class TestStrictCleansing:

    def test_strict_rechaza_columna_inexistente(self):
        entry = _make_entry("A", {"codigo": ["001"]})
        rule = CleansingRule.new("A", "no_existe", "drop_column")

        with pytest.raises(ValueError, match="no_existe"):
            apply_all_rules([entry], [rule], strict=True)

    def test_strict_rechaza_fecha_de_filtro_invalida(self):
        entry = _make_entry("A", {"fecha": ["2025-01-01"]})
        rule = CleansingRule.new(
            "A", "fecha", "filter_date_before", {"date": "no-es-fecha"}
        )

        with pytest.raises(ValueError, match="fecha invalida"):
            apply_all_rules([entry], [rule], strict=True)
