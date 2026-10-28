"""
tests/test_date_utils.py — Pruebas de engine/_date_utils.py.

Cubre parse_date_flexible: formatos soportados, casos invalidos y
comportamiento conservador (None en lugar de excepcion).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from engine._date_utils import DATE_FORMATS, parse_date_flexible


class TestParseDateFlexible:
    """Pruebas unitarias de parse_date_flexible."""

    # --- Formatos validos ---

    def test_formato_argentino_slash(self):
        """dd/mm/aaaa -> datetime correcto."""
        result = parse_date_flexible("25/10/2025")
        assert result == datetime(2025, 10, 25)

    def test_formato_iso8601(self):
        """aaaa-mm-dd -> datetime correcto."""
        result = parse_date_flexible("2025-10-25")
        assert result == datetime(2025, 10, 25)

    def test_formato_guion_europeo(self):
        """dd-mm-aaaa -> datetime correcto."""
        result = parse_date_flexible("25-10-2025")
        assert result == datetime(2025, 10, 25)

    def test_formato_estadounidense(self):
        """mm/dd/aaaa -> datetime correcto."""
        result = parse_date_flexible("10/25/2025")
        assert result == datetime(2025, 10, 25)

    def test_formato_iso_con_slash(self):
        """aaaa/mm/dd -> datetime correcto."""
        result = parse_date_flexible("2025/10/25")
        assert result == datetime(2025, 10, 25)

    def test_primero_de_enero(self):
        """Fecha borde: 01/01/2024."""
        result = parse_date_flexible("01/01/2024")
        assert result == datetime(2024, 1, 1)

    def test_ultimo_del_anio(self):
        """Fecha borde: 31/12/2024."""
        result = parse_date_flexible("31/12/2024")
        assert result == datetime(2024, 12, 31)

    def test_strip_de_espacios(self):
        """Espacios al inicio/fin se recortan antes de parsear."""
        result = parse_date_flexible("  25/10/2025  ")
        assert result == datetime(2025, 10, 25)

    # --- Casos invalidos -> None ---

    def test_cadena_vacia_retorna_none(self):
        """Cadena vacia retorna None."""
        assert parse_date_flexible("") is None

    def test_solo_espacios_retorna_none(self):
        """Cadena de solo espacios retorna None."""
        assert parse_date_flexible("   ") is None

    def test_texto_libre_retorna_none(self):
        """Texto sin formato de fecha retorna None."""
        assert parse_date_flexible("no-es-una-fecha") is None

    def test_numero_retorna_none(self):
        """Numero sin separadores de fecha retorna None."""
        assert parse_date_flexible("20251025") is None

    def test_ninguno_retorna_none(self):
        """None como input retorna None (no lanza)."""
        assert parse_date_flexible(None) is None  # type: ignore[arg-type]

    def test_entero_retorna_none(self):
        """Entero como input retorna None (no lanza)."""
        assert parse_date_flexible(12345) is None  # type: ignore[arg-type]

    def test_fecha_invalida_dia_fuera_de_rango(self):
        """32/01/2025 retorna None (dia invalido)."""
        assert parse_date_flexible("32/01/2025") is None

    def test_fecha_invalida_mes_fuera_de_rango(self):
        """13/13/2025 retorna None: no parsea en ningun formato (mes 13 invalido en todos)."""
        # Nota: "01/13/2025" parsea como mm/dd/yyyy (enero 13) — es valido.
        # Para garantizar None, necesitamos un mes > 12 en todos los formatos.
        assert parse_date_flexible("13/13/2025") is None

    # --- Propiedades ---

    def test_retorna_datetime_no_string(self):
        """El resultado es un objeto datetime, no una cadena."""
        result = parse_date_flexible("25/10/2025")
        assert isinstance(result, datetime)

    def test_formatos_cubren_cinco_entradas(self):
        """DATE_FORMATS debe tener exactamente 5 entradas."""
        assert len(DATE_FORMATS) == 5

    def test_no_lanza_nunca(self):
        """parse_date_flexible nunca lanza excepcion, sin importar la entrada."""
        entradas_raras = [
            None, 0, [], {}, "", "abc", "99/99/9999",
            "2025-13-01", "DROP TABLE", "=1+1", "A" * 1000,
        ]
        for entrada in entradas_raras:
            try:
                parse_date_flexible(entrada)  # type: ignore[arg-type]
            except Exception as exc:
                pytest.fail(f"parse_date_flexible({entrada!r}) lanzo: {exc}")
