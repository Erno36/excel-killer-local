"""
engine/exporter.py — Exportacion del resultado a .xlsx.

Implementa ExporterPort (Protocol).
Neutraliza inyeccion de formulas en Excel en valores de texto con prefijos peligrosos.
Los valores numericos (int, float) se exportan sin modificacion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from data.models import CrossResult, ExportOutcome


# ---------------------------------------------------------------------------
# Puerto (interface)
# ---------------------------------------------------------------------------

@runtime_checkable
class ExporterPort(Protocol):
    def export(
        self,
        result: CrossResult,
        destination: Path,
        overwrite: bool = False,
    ) -> ExportOutcome:
        """
        Escribe el resultado en destination (.xlsx).
        Si destination existe y overwrite=False, lanza FileExistsError.
        Si result.df es None (dry_run), lanza ValueError.
        """
        ...


# ---------------------------------------------------------------------------
# Implementacion
# ---------------------------------------------------------------------------

# Prefijos de texto que activan formulas en Excel — se neutralizan con apostrofe.
# Solo aplica a valores de tipo str. Los numericos (int, float) nunca se tocan.
FORMULA_PREFIX_CHARS = ("=", "+", "-", "@", "\t", "\r", "|", "%")


class XlsxExporter:
    """Exporta CrossResult a .xlsx usando openpyxl."""

    def export(
        self,
        result: CrossResult,
        destination: Path,
        overwrite: bool = False,
    ) -> ExportOutcome:
        destination = Path(destination)

        if result.df is None:
            raise ValueError(
                "El resultado del cruce no esta disponible (modo dry-run). "
                "Ejecuta el cruce completo antes de exportar."
            )

        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"El archivo '{destination.name}' ya existe. "
                "Confirma si deseas sobreescribirlo."
            )

        destination.parent.mkdir(parents=True, exist_ok=True)

        df_clean = self._sanitize_dataframe(result.df)

        df_clean.to_excel(destination, index=False, engine="openpyxl")

        return ExportOutcome(
            path=destination,
            rows_written=len(df_clean),
        )

    def _sanitize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Neutraliza inyeccion de formulas en celdas de texto.
        Los valores que comienzan con caracteres de formula se prefijaenn con apostrofe.
        """
        sanitized = df.copy()
        for col in sanitized.columns:
            if sanitized[col].dtype == object:
                sanitized[col] = sanitized[col].apply(self._sanitize_value)
        return sanitized

    @staticmethod
    def _sanitize_value(value: object) -> object:
        # Los numericos se devuelven tal cual — nunca corromper importes negativos.
        if isinstance(value, (int, float)):
            return value
        # Solo sanitizar strings con prefijos de formula.
        if isinstance(value, str) and value.startswith(FORMULA_PREFIX_CHARS):
            return "'" + value
        return value
