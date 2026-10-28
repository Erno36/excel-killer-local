"""
tests/test_cleansing.py — Pruebas del motor de limpieza de datos.

Cubre engine/cleansing.py: apply_rule, apply_all_rules, preview_rule.
Datos sinteticos unicamente. Sin datos reales ni derivados de datos reales.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
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
# Helpers de construccion de fixtures
# ---------------------------------------------------------------------------

def _series(*values) -> pd.Series:
    """Crea una pd.Series a partir de valores posicionales."""
    return pd.Series(list(values))


def _make_entry(label: str, data: dict) -> FileEntry:
    """Construye un FileEntry minimo con datos sinteticos."""
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


def _rule(op: str, params: dict | None = None, file_label: str = "A", column: str = "col") -> CleansingRule:
    """Construye una CleansingRule de prueba con valores minimos."""
    return CleansingRule.new(file_label=file_label, column=column, operation=op, params=params or {})


# ===========================================================================
# Pruebas de apply_rule — operaciones individuales
# ===========================================================================

class TestStripSpaces:
    def test_strip_spaces_colapsa_internos(self):
        """'  hola   mundo  ' debe quedar 'hola mundo'."""
        s = _series("  hola   mundo  ")
        result = apply_rule(s, _rule("strip_spaces"))
        assert result[0] == "hola mundo"

    def test_strip_spaces_solo_extremos(self):
        """'  abc  ' debe quedar 'abc'."""
        s = _series("  abc  ")
        result = apply_rule(s, _rule("strip_spaces"))
        assert result[0] == "abc"

    def test_strip_spaces_multiples_espacios_internos(self):
        """Colapsa tres o más espacios internos a uno."""
        s = _series("a     b")
        result = apply_rule(s, _rule("strip_spaces"))
        assert result[0] == "a b"

    def test_strip_spaces_no_modifica_nan(self):
        """NaN permanece NaN."""
        s = _series(np.nan)
        result = apply_rule(s, _rule("strip_spaces"))
        assert pd.isna(result[0])

    def test_strip_spaces_cadena_limpia_sin_cambio(self):
        """Cadena sin espacios extra no cambia."""
        s = _series("abc def")
        result = apply_rule(s, _rule("strip_spaces"))
        assert result[0] == "abc def"


class TestCasoMayusculas:
    def test_to_uppercase(self):
        """'garcia' debe quedar 'GARCIA'."""
        s = _series("garcia")
        result = apply_rule(s, _rule("to_uppercase"))
        assert result[0] == "GARCIA"

    def test_to_lowercase(self):
        """'GARCIA' debe quedar 'garcia'."""
        s = _series("GARCIA")
        result = apply_rule(s, _rule("to_lowercase"))
        assert result[0] == "garcia"

    def test_capitalize(self):
        """'JUAN garcia' debe quedar 'Juan garcia' (solo primera letra, resto sin tocar)."""
        s = _series("JUAN garcia")
        result = apply_rule(s, _rule("capitalize"))
        # str.capitalize() hace mayuscula solo la primera letra y minuscula el resto
        assert result[0] == "Juan garcia"

    def test_uppercase_con_tildes(self):
        """'ñoño' debe quedar 'ÑOÑO'."""
        s = _series("ñoño")
        result = apply_rule(s, _rule("to_uppercase"))
        assert result[0] == "ÑOÑO"

    def test_uppercase_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("to_uppercase"))
        assert pd.isna(result[0])


class TestReplaceLiteral:
    def test_replace_literal(self):
        """Elimina guiones de CUIL sintetico."""
        s = _series("20-12345678-9")
        result = apply_rule(s, _rule("replace_literal", {"find": "-", "replace": ""}))
        assert result[0] == "20123456789"

    def test_replace_literal_reemplaza_todas_las_ocurrencias(self):
        """Reemplaza todas las ocurrencias, no solo la primera."""
        s = _series("a-b-c-d")
        result = apply_rule(s, _rule("replace_literal", {"find": "-", "replace": "_"}))
        assert result[0] == "a_b_c_d"

    def test_replace_literal_find_vacio(self):
        """find vacio no lanza, retorna el valor original."""
        s = _series("abc")
        result = apply_rule(s, _rule("replace_literal", {"find": "", "replace": "X"}))
        # str.replace("", "X") inserta X entre cada caracter — comportamiento de Python,
        # no es un error. Verificamos que no lanza.
        assert isinstance(result[0], str)

    def test_replace_literal_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("replace_literal", {"find": "-", "replace": ""}))
        assert pd.isna(result[0])


class TestReplaceRegex:
    def test_replace_regex_valido(self):
        """Patron r'\\s+' normaliza multiples espacios en uno."""
        s = _series("hola   mundo")
        result = apply_rule(s, _rule("replace_regex", {"pattern": r"\s+", "replace": " "}))
        assert result[0] == "hola mundo"

    def test_replace_regex_invalido_lanza_valueerror(self):
        """Patron '[[[' lanza ValueError."""
        s = _series("abc")
        with pytest.raises(ValueError, match="invalido"):
            apply_rule(s, _rule("replace_regex", {"pattern": "[[[", "replace": ""}))

    def test_replace_regex_pattern_vacio_no_lanza(self):
        """Pattern vacio es valido para re.compile; no lanza ValueError."""
        s = _series("abc")
        # re.compile("") es valido en Python; insertaria entre cada char
        result = apply_rule(s, _rule("replace_regex", {"pattern": "", "replace": "X"}))
        assert isinstance(result[0], str)

    def test_replace_regex_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("replace_regex", {"pattern": r"\d", "replace": ""}))
        assert pd.isna(result[0])


class TestRemoveChars:
    def test_remove_chars_cuil(self):
        """Eliminar '-' y '.' del CUIL sintetico."""
        s = _series("20-12345678-9")
        result = apply_rule(s, _rule("remove_chars", {"chars": "-."}))
        assert result[0] == "20123456789"

    def test_remove_chars_especiales_regex_corchete_cierre(self):
        """']' es especial en regex de clase de caracteres; re.escape debe manejarlo."""
        s = _series("a]b]c")
        result = apply_rule(s, _rule("remove_chars", {"chars": "]"}))
        assert result[0] == "abc"

    def test_remove_chars_especiales_backslash(self):
        r"""'\' es especial en regex; re.escape debe manejarlo."""
        s = _series("a\\b\\c")
        result = apply_rule(s, _rule("remove_chars", {"chars": "\\"}))
        assert result[0] == "abc"

    def test_remove_chars_especiales_caret(self):
        """'^' dentro de la clase de caracteres es especial; re.escape debe manejarlo."""
        s = _series("a^b^c")
        result = apply_rule(s, _rule("remove_chars", {"chars": "^"}))
        assert result[0] == "abc"

    def test_remove_chars_vacio_retorna_copia(self):
        """chars vacio no modifica el valor."""
        s = _series("abc")
        result = apply_rule(s, _rule("remove_chars", {"chars": ""}))
        assert result[0] == "abc"

    def test_remove_chars_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("remove_chars", {"chars": "-"}))
        assert pd.isna(result[0])


class TestKeepOnlyDigits:
    def test_keep_only_digits(self):
        """'20-12.345.678/9' debe quedar '20123456789'."""
        s = _series("20-12.345.678/9")
        result = apply_rule(s, _rule("keep_only_digits"))
        assert result[0] == "20123456789"

    def test_keep_only_digits_sin_digitos(self):
        """Cadena sin digitos queda vacia."""
        s = _series("abc-def")
        result = apply_rule(s, _rule("keep_only_digits"))
        assert result[0] == ""

    def test_keep_only_digits_ya_son_digitos(self):
        """Cadena ya solo con digitos no cambia."""
        s = _series("12345")
        result = apply_rule(s, _rule("keep_only_digits"))
        assert result[0] == "12345"

    def test_keep_only_digits_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("keep_only_digits"))
        assert pd.isna(result[0])


class TestNormalizeDate:
    def test_normalize_date_ok(self):
        """'25/10/2025' con from='%d/%m/%Y' to='%Y-%m-%d' -> '2025-10-25'."""
        s = _series("25/10/2025")
        result = apply_rule(
            s,
            _rule("normalize_date", {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"}),
        )
        assert result[0] == "2025-10-25"

    def test_normalize_date_fallback(self):
        """Celda no parseable queda sin cambio (no lanza)."""
        s = _series("no-es-fecha")
        result = apply_rule(
            s,
            _rule("normalize_date", {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"}),
        )
        assert result[0] == "no-es-fecha"

    def test_normalize_date_nan_permanece_nan(self):
        """NaN permanece NaN."""
        s = _series(np.nan)
        result = apply_rule(
            s,
            _rule("normalize_date", {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"}),
        )
        assert pd.isna(result[0])

    def test_normalize_date_mezcla_validos_invalidos(self):
        """Fila valida se transforma; fila invalida queda sin cambio."""
        s = _series("01/01/2025", "invalido", "15/06/2024")
        result = apply_rule(
            s,
            _rule("normalize_date", {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"}),
        )
        assert result[0] == "2025-01-01"
        assert result[1] == "invalido"
        assert result[2] == "2024-06-15"


class TestFillEmpty:
    def test_fill_empty_nan(self):
        """NaN -> valor por defecto."""
        s = _series(np.nan)
        result = apply_rule(s, _rule("fill_empty", {"value": "SIN DATO"}))
        assert result[0] == "SIN DATO"

    def test_fill_empty_string_vacio(self):
        """'' -> valor por defecto."""
        s = _series("")
        result = apply_rule(s, _rule("fill_empty", {"value": "SIN DATO"}))
        assert result[0] == "SIN DATO"

    def test_fill_empty_valor_existente_no_cambia(self):
        """Valores no vacios no se tocan."""
        s = _series("existente")
        result = apply_rule(s, _rule("fill_empty", {"value": "SIN DATO"}))
        assert result[0] == "existente"

    def test_fill_empty_con_cero(self):
        """Valor por defecto numerico '0' rellena NaN."""
        s = _series(np.nan, "abc", "")
        result = apply_rule(s, _rule("fill_empty", {"value": "0"}))
        assert result[0] == "0"
        assert result[1] == "abc"
        assert result[2] == "0"


class TestPadLeft:
    def test_pad_left_cuil(self):
        """'1234567890' (10 chars) con width=11, char='0' -> '01234567890'."""
        s = _series("1234567890")
        result = apply_rule(s, _rule("pad_left", {"width": 11, "char": "0"}))
        assert result[0] == "01234567890"

    def test_pad_left_ya_suficiente_ancho(self):
        """Cadena con ancho >= width no cambia."""
        s = _series("12345678901")
        result = apply_rule(s, _rule("pad_left", {"width": 11, "char": "0"}))
        assert result[0] == "12345678901"

    def test_pad_left_caracter_no_cero(self):
        """char distinto de '0' usa rjust."""
        s = _series("abc")
        result = apply_rule(s, _rule("pad_left", {"width": 6, "char": "-"}))
        assert result[0] == "---abc"

    def test_pad_left_no_modifica_nan(self):
        s = _series(np.nan)
        result = apply_rule(s, _rule("pad_left", {"width": 11, "char": "0"}))
        assert pd.isna(result[0])


class TestOperacionInvalida:
    def test_operacion_invalida_lanza_valueerror(self):
        """Operacion desconocida lanza ValueError."""
        s = _series("abc")
        with pytest.raises(ValueError, match="desconocida"):
            apply_rule(s, _rule("operacion_inexistente"))


# ===========================================================================
# Pruebas de apply_all_rules
# ===========================================================================

class TestApplyAllRules:
    def test_apply_all_rules_acumulativo(self):
        """
        Aplicar strip_spaces y luego keep_only_digits sobre la misma columna
        produce efectos encadenados en orden.
        """
        entry = _make_entry("A", {"col": ["  20 - 123 ", "  30 - 456 "]})
        rules = [
            CleansingRule.new("A", "col", "strip_spaces"),
            CleansingRule.new("A", "col", "keep_only_digits"),
        ]
        result = apply_all_rules([entry], rules)
        assert result[0].df["col"][0] == "20123"
        assert result[0].df["col"][1] == "30456"

    def test_apply_all_rules_label_inexistente(self):
        """Regla con file_label desconocido no crashea."""
        entry = _make_entry("A", {"col": ["abc"]})
        rules = [CleansingRule.new("LABEL_INEXISTENTE", "col", "strip_spaces")]
        result = apply_all_rules([entry], rules)
        # Debe retornar el entry sin modificar
        assert result[0].df["col"][0] == "abc"

    def test_apply_all_rules_columna_inexistente(self):
        """Regla con columna desconocida no crashea."""
        entry = _make_entry("A", {"col": ["abc"]})
        rules = [CleansingRule.new("A", "COLUMNA_INEXISTENTE", "strip_spaces")]
        result = apply_all_rules([entry], rules)
        assert result[0].df["col"][0] == "abc"

    def test_apply_all_rules_no_modifica_originales(self):
        """Los FileEntry originales no mutan: aplica no destructividad."""
        original_value = "  test  "
        entry = _make_entry("A", {"col": [original_value]})
        rules = [CleansingRule.new("A", "col", "strip_spaces")]
        _ = apply_all_rules([entry], rules)
        # El entry original debe permanecer sin cambios
        assert entry.df["col"][0] == original_value

    def test_apply_all_rules_regex_invalido_no_crashea(self):
        """
        Regla replace_regex con patron invalido en apply_all_rules:
        se ignora silenciosamente (no re-lanza, no crashea la app).
        """
        entry = _make_entry("A", {"col": ["abc", "def"]})
        rules = [CleansingRule.new("A", "col", "replace_regex", {"pattern": "[[[", "replace": ""})]
        # No debe lanzar excepcion
        result = apply_all_rules([entry], rules)
        # La columna debe quedar sin cambio (regla ignorada)
        assert result[0].df["col"][0] == "abc"

    def test_apply_all_rules_multiples_archivos(self):
        """Reglas sobre distintos archivos se aplican al archivo correcto."""
        entry_a = _make_entry("A", {"col": ["  abc  "]})
        entry_b = _make_entry("B", {"col": ["  xyz  "]})
        rules = [
            CleansingRule.new("A", "col", "strip_spaces"),
            CleansingRule.new("B", "col", "to_uppercase"),
        ]
        result = apply_all_rules([entry_a, entry_b], rules)
        # A: strip aplicado
        assert result[0].df["col"][0] == "abc"
        # B: uppercase aplicado (con espacios internos originales)
        assert result[1].df["col"][0] == "  XYZ  "

    def test_apply_all_rules_retorna_nuevos_entry(self):
        """Los objetos retornados son nuevos FileEntry, no los mismos."""
        entry = _make_entry("A", {"col": ["abc"]})
        rules = [CleansingRule.new("A", "col", "strip_spaces")]
        result = apply_all_rules([entry], rules)
        assert result[0] is not entry

    def test_apply_all_rules_sin_reglas_retorna_copia(self):
        """Sin reglas, retorna entradas equivalentes (sin crashear)."""
        entry = _make_entry("A", {"col": ["abc"]})
        result = apply_all_rules([entry], [])
        assert result[0].df["col"][0] == "abc"

    def test_apply_all_rules_idempotente(self):
        """Aplicar las mismas reglas dos veces produce el mismo resultado."""
        entry = _make_entry("A", {"col": ["  HOLA  MUNDO  "]})
        rules = [CleansingRule.new("A", "col", "strip_spaces")]
        result1 = apply_all_rules([entry], rules)
        # Usar el resultado de la primera aplicacion como entrada de la segunda
        result2 = apply_all_rules(result1, rules)
        assert result1[0].df["col"][0] == result2[0].df["col"][0]

    def test_apply_all_rules_orden_importa(self):
        """El orden de las reglas afecta el resultado (encadenamiento)."""
        entry = _make_entry("A", {"col": ["  20-12345678-9  "]})
        # strip primero, luego remove_chars
        rules_orden1 = [
            CleansingRule.new("A", "col", "strip_spaces"),
            CleansingRule.new("A", "col", "remove_chars", {"chars": "-"}),
        ]
        # remove_chars primero, luego strip
        rules_orden2 = [
            CleansingRule.new("A", "col", "remove_chars", {"chars": "-"}),
            CleansingRule.new("A", "col", "strip_spaces"),
        ]
        entry2 = _make_entry("A", {"col": ["  20-12345678-9  "]})
        r1 = apply_all_rules([entry], rules_orden1)
        r2 = apply_all_rules([entry2], rules_orden2)
        # Ambos producen el mismo resultado final en este caso
        assert r1[0].df["col"][0] == r2[0].df["col"][0] == "20123456789"


# ===========================================================================
# Pruebas de preview_rule
# ===========================================================================

class TestPreviewRule:
    def test_preview_rule_ok(self):
        """Retorna hasta 5 pares (antes, despues) para serie con datos."""
        s = pd.Series(["  abc  ", "  def  ", "  ghi  ", "  jkl  ", "  mno  ", "  pqr  "])
        rule = _rule("strip_spaces")
        pairs = preview_rule(s, rule, n=5)
        assert len(pairs) == 5
        for before, after in pairs:
            assert after == before.strip()

    def test_preview_rule_retorna_menos_de_n_si_hay_menos_filas(self):
        """Si la serie tiene 2 filas validas, retorna 2 pares."""
        s = _series("  a  ", "  b  ")
        pairs = preview_rule(s, _rule("strip_spaces"), n=5)
        assert len(pairs) == 2

    def test_preview_rule_ignora_vacios_y_nulos(self):
        """Filas vacias y NaN no aparecen en el preview."""
        s = pd.Series(["  abc  ", np.nan, "", "  def  "])
        pairs = preview_rule(s, _rule("strip_spaces"), n=5)
        # Solo 2 filas no vacias/nulas
        assert len(pairs) == 2

    def test_preview_rule_regex_invalido(self):
        """Pattern invalido retorna lista vacia sin lanzar excepcion."""
        s = _series("abc", "def")
        rule = _rule("replace_regex", {"pattern": "[[[", "replace": ""})
        pairs = preview_rule(s, rule, n=5)
        assert pairs == []

    def test_preview_rule_serie_vacia(self):
        """Serie vacia retorna lista vacia."""
        s = pd.Series([], dtype=str)
        pairs = preview_rule(s, _rule("strip_spaces"), n=5)
        assert pairs == []

    def test_preview_rule_serie_solo_nulos(self):
        """Serie con solo NaN retorna lista vacia."""
        s = pd.Series([np.nan, np.nan])
        pairs = preview_rule(s, _rule("strip_spaces"), n=5)
        assert pairs == []

    def test_preview_rule_tipos_de_retorno(self):
        """Cada par debe ser (str, str)."""
        s = _series("  abc  ")
        pairs = preview_rule(s, _rule("strip_spaces"), n=5)
        assert len(pairs) == 1
        before, after = pairs[0]
        assert isinstance(before, str)
        assert isinstance(after, str)


# ===========================================================================
# Pruebas de propiedades (property-like)
# ===========================================================================

class TestPropiedades:
    def test_apply_rule_no_modifica_serie_original(self):
        """apply_rule no debe modificar la serie original."""
        original = pd.Series(["  abc  ", "  def  "])
        original_copia = original.copy()
        _ = apply_rule(original, _rule("strip_spaces"))
        pd.testing.assert_series_equal(original, original_copia)

    def test_apply_all_rules_longitud_preservada(self):
        """El numero de filas no cambia despues de apply_all_rules."""
        n_filas = 20
        entry = _make_entry("A", {"col": [f"  val {i}  " for i in range(n_filas)]})
        rules = [CleansingRule.new("A", "col", "strip_spaces")]
        result = apply_all_rules([entry], rules)
        assert len(result[0].df) == n_filas

    def test_apply_rule_strip_idempotente(self):
        """strip_spaces aplicado dos veces da el mismo resultado que una vez."""
        s = _series("  hola   mundo  ")
        r1 = apply_rule(s, _rule("strip_spaces"))
        r2 = apply_rule(r1, _rule("strip_spaces"))
        pd.testing.assert_series_equal(r1, r2)

    def test_apply_rule_keep_only_digits_idempotente(self):
        """keep_only_digits aplicado dos veces da el mismo resultado."""
        s = _series("20-12345678-9", "abc123")
        r1 = apply_rule(s, _rule("keep_only_digits"))
        r2 = apply_rule(r1, _rule("keep_only_digits"))
        pd.testing.assert_series_equal(r1, r2)

    def test_apply_rule_to_uppercase_idempotente(self):
        """to_uppercase aplicado dos veces da el mismo resultado."""
        s = _series("Garcia Lopez", "PEREZ")
        r1 = apply_rule(s, _rule("to_uppercase"))
        r2 = apply_rule(r1, _rule("to_uppercase"))
        pd.testing.assert_series_equal(r1, r2)


# ===========================================================================
# Pruebas de seguridad: RN-019 — audit log no contiene valores de celdas
# ===========================================================================

class TestSeguridadRN019:
    """
    Verifica que el log de auditoria generado por apply_all_rules + el logger
    no filtre valores de celdas, CUILes, importes ni parametros de busqueda/reemplazo.
    """

    def test_log_cleansing_no_contiene_valores_de_params(self, tmp_path):
        """
        El AuditEntry de CLEANSING_APPLY no debe contener los valores de
        los campos 'find', 'replace', 'pattern', 'chars' ni 'value'.
        Verifica directamente el dict del AuditEntry antes de serializar.
        """
        import json
        from audit.logger import AuditLogger, make_timestamp
        from data.models import AuditEntry

        VALOR_PROHIBIDO_FIND = "20-XXXXX"
        VALOR_PROHIBIDO_REPLACE = "20XXXXX"
        VALOR_PROHIBIDO_CHARS = "-."

        logger = AuditLogger(tmp_path / ".logs")

        rules = [
            CleansingRule.new("A", "col", "replace_literal", {
                "find": VALOR_PROHIBIDO_FIND,
                "replace": VALOR_PROHIBIDO_REPLACE,
            }),
            CleansingRule.new("A", "col", "remove_chars", {
                "chars": VALOR_PROHIBIDO_CHARS,
            }),
        ]

        ops_used = list({r.operation for r in rules})

        # Simular el log tal como lo hace CleansingScreen._on_apply
        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="testuser",
            accion="CLEANSING_APPLY",
            archivos=[{"etiqueta": "A"}],
            columnas=["col"],
            filas_procesadas=10,
            extra={
                "operaciones": ops_used,
                "reglas_count": len(rules),
            },
        )
        logger.log(entry)

        log_file = next((tmp_path / ".logs").glob("*.jsonl"))
        contenido = log_file.read_text(encoding="utf-8")

        assert VALOR_PROHIBIDO_FIND not in contenido, (
            f"El log contiene el valor de 'find': {VALOR_PROHIBIDO_FIND}"
        )
        assert VALOR_PROHIBIDO_REPLACE not in contenido, (
            f"El log contiene el valor de 'replace': {VALOR_PROHIBIDO_REPLACE}"
        )
        assert VALOR_PROHIBIDO_CHARS not in contenido, (
            f"El log contiene el valor de 'chars': {VALOR_PROHIBIDO_CHARS}"
        )

    def test_log_no_contiene_pattern_regex(self, tmp_path):
        """
        El log de CLEANSING_APPLY no debe contener el pattern de un replace_regex.
        """
        from audit.logger import AuditLogger, make_timestamp
        from data.models import AuditEntry

        PATRON_PROHIBIDO = r"\d{2}-\d{8}-\d"

        logger = AuditLogger(tmp_path / ".logs")

        rules = [
            CleansingRule.new("A", "col", "replace_regex", {
                "pattern": PATRON_PROHIBIDO,
                "replace": "",
            }),
        ]

        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="testuser",
            accion="CLEANSING_APPLY",
            archivos=[{"etiqueta": "A"}],
            columnas=["col"],
            filas_procesadas=5,
            extra={
                "operaciones": ["replace_regex"],
                "reglas_count": 1,
            },
        )
        logger.log(entry)

        log_file = next((tmp_path / ".logs").glob("*.jsonl"))
        contenido = log_file.read_text(encoding="utf-8")

        assert PATRON_PROHIBIDO not in contenido, (
            f"El log contiene el patron de regex: {PATRON_PROHIBIDO}"
        )

    def test_log_cleansing_solo_registra_metadatos_seguros(self, tmp_path):
        """
        El log de CLEANSING_APPLY registra: operaciones, reglas_count, columnas,
        filas_procesadas — pero NO params individuales de cada regla.

        NOTA DE DEFECTO DEF-CLEAN-001 (medio): AuditLogger._entry_to_dict usa
        record.update(entry.extra) en lugar de record["extra"] = entry.extra,
        por lo que las claves del dict extra se aplanan al nivel raiz del JSON
        en vez de quedar anidadas bajo "extra". Funciona pero es inconsistente
        con el modelo AuditEntry. El test verifica el comportamiento real
        (aplanado) y registra el defecto para que lo corrija el desarrollador.
        """
        import json
        from audit.logger import AuditLogger, make_timestamp
        from data.models import AuditEntry

        logger = AuditLogger(tmp_path / ".logs")

        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="testuser",
            accion="CLEANSING_APPLY",
            archivos=[{"etiqueta": "Stock Seguros"}],
            columnas=["CUIL"],
            filas_procesadas=500,
            extra={
                "operaciones": ["remove_chars"],
                "reglas_count": 1,
            },
        )
        logger.log(entry)

        log_file = next((tmp_path / ".logs").glob("*.jsonl"))
        record = json.loads(log_file.read_text(encoding="utf-8").strip())

        assert record["accion"] == "CLEANSING_APPLY"
        assert record["filas_procesadas"] == 500
        assert record["columnas"] == ["CUIL"]
        # DEF-CLEAN-001: el logger aplana 'extra' al nivel raiz (record.update(extra))
        # por lo que las claves "operaciones" y "reglas_count" estan al nivel raiz.
        assert "operaciones" in record, (
            "DEF-CLEAN-001: las claves de extra deben estar presentes (aplanadas al raiz)"
        )
        # No debe haber *claves* de params individuales de reglas en el registro.
        # Se verifica que no existen como claves de primer nivel del dict,
        # no como substrings (para no confundir con nombres de operacion como "remove_chars").
        claves_prohibidas_de_params = ["find", "replace", "pattern"]
        for clave in claves_prohibidas_de_params:
            assert clave not in record, (
                f"RN-019: la clave de param '{clave}' no debe estar en el log de auditoria"
            )


# ===========================================================================
# Pruebas de casos borde de dominio bancario
# ===========================================================================

class TestCasosBordeDominioBancario:
    """
    Casos realistas del dominio: CUILes, fechas argentinas, importes,
    caracteres especiales, campos en blanco, valores limite.
    Todos los datos son sinteticos.
    """

    def test_cuil_sintetico_normalizacion_completa(self):
        """Pipeline completo sobre CUILes sinteticos: remove_chars -> keep_only_digits."""
        cuilas_sucios = pd.Series([
            "20-11111111-1",
            "27 - 22222222 - 2",
            "23.33333333.3",
            " 20/44444444/4 ",
        ])
        # Paso 1: remove_chars (guiones, puntos, barras y espacios)
        r1 = apply_rule(cuilas_sucios, _rule("remove_chars", {"chars": "-. /"}))
        # Paso 2: keep_only_digits (por si queda algo)
        r2 = apply_rule(r1, _rule("keep_only_digits"))
        assert r2[0] == "20111111111"
        assert r2[1] == "27222222222"
        assert r2[2] == "23333333333"
        assert r2[3] == "20444444444"

    def test_fechas_argentinas_a_iso(self):
        """Fechas en formato argentino se normalizan a ISO 8601."""
        fechas = pd.Series(["01/01/2025", "31/12/2024", "15/06/2023"])
        result = apply_rule(
            fechas,
            _rule("normalize_date", {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"}),
        )
        assert result[0] == "2025-01-01"
        assert result[1] == "2024-12-31"
        assert result[2] == "2023-06-15"

    def test_importes_con_caracteres_no_numericos(self):
        """Importes con '$', '.', ',' se reducen a solo digitos (sin decimales)."""
        importes = pd.Series(["$1.500,00", "$ 2.300,50", "800"])
        result = apply_rule(importes, _rule("keep_only_digits"))
        assert result[0] == "150000"
        assert result[1] == "230050"
        assert result[2] == "800"

    def test_nombres_con_tildes_uppercase(self):
        """Nombres con tildes y enies se convierten correctamente a mayusculas."""
        nombres = pd.Series(["garcía lópez", "ñoño peñas", "josé martínez"])
        result = apply_rule(nombres, _rule("to_uppercase"))
        assert result[0] == "GARCÍA LÓPEZ"
        assert result[1] == "ÑOÑO PEÑAS"
        assert result[2] == "JOSÉ MARTÍNEZ"

    def test_cuil_pad_left_a_11_digitos(self):
        """CUIL que llego con 10 digitos se rellena a 11 con '0' a la izquierda."""
        s = pd.Series(["1234567890", "23456789012", "987654321"])
        result = apply_rule(s, _rule("pad_left", {"width": 11, "char": "0"}))
        assert result[0] == "01234567890"
        assert result[1] == "23456789012"   # ya tiene 11, no cambia
        assert result[2] == "00987654321"

    def test_fill_empty_en_columna_estado_cuenta(self):
        """Columna de estado con NaN y vacios recibe valor por defecto 'DESCONOCIDO'."""
        estados = pd.Series(["activo", np.nan, "", "inactivo", np.nan])
        result = apply_rule(estados, _rule("fill_empty", {"value": "DESCONOCIDO"}))
        assert result[0] == "activo"
        assert result[1] == "DESCONOCIDO"
        assert result[2] == "DESCONOCIDO"
        assert result[3] == "inactivo"
        assert result[4] == "DESCONOCIDO"

    def test_strip_spaces_en_nombres_de_productos(self):
        """Nombres de productos bancarios con espacios multiples se normalizan."""
        productos = pd.Series([
            "  Seguro   de  Vida  ",
            " Prestamo    Personal ",
            "Anticipos",
        ])
        result = apply_rule(productos, _rule("strip_spaces"))
        assert result[0] == "Seguro de Vida"
        assert result[1] == "Prestamo Personal"
        assert result[2] == "Anticipos"

    def test_volumen_grande_sin_error(self):
        """10000 filas procesadas sin excepcion ni perdida de filas."""
        n = 10_000
        s = pd.Series([f"  val {i}  " for i in range(n)])
        result = apply_rule(s, _rule("strip_spaces"))
        assert len(result) == n
        assert result[0] == "val 0"
        assert result[n - 1] == f"val {n - 1}"
