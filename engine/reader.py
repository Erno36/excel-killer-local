"""
engine/reader.py — Lectura de archivos Excel.

Implementa FileReaderPort (Protocol).
Soporta .xlsx (openpyxl) y .xls (xlrd).
Soporta sheet_index=-1 para leer y concatenar TODAS las hojas.
Devuelve DataFrame + FileMetadata sin modificar el contenido de las celdas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from data.models import FileMetadata
from engine.header_detector import MAX_HEADER_SCAN_ROWS, detect_header_rows


# ---------------------------------------------------------------------------
# Excepciones del dominio
# ---------------------------------------------------------------------------

class FileReadError(Exception):
    """El archivo no pudo leerse (corrupto, formato no soportado, vacio)."""
    pass


class EmptyFileError(FileReadError):
    """El archivo no tiene filas de datos (solo encabezado o completamente vacio)."""
    pass


# ---------------------------------------------------------------------------
# Puerto (interface)
# ---------------------------------------------------------------------------

@runtime_checkable
class FileReaderPort(Protocol):
    def read(
        self,
        path: Path,
        sheet_index: int = 0,
        header_row: int | None = None,
    ) -> tuple[pd.DataFrame, FileMetadata]:
        """
        Lee la hoja indicada del archivo.
        sheet_index=-1: lee y concatena todas las hojas.
        header_row: indice 0-based opcional para corregir la deteccion automatica.
        Retorna (DataFrame, FileMetadata).
        Lanza FileReadError si el archivo esta corrupto.
        Lanza EmptyFileError si la hoja no tiene datos.
        """
        ...


# ---------------------------------------------------------------------------
# Implementacion
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".xlsx", ".xls"}


class ExcelFileReader:
    """
    Implementacion concreta de FileReaderPort.
    Usa openpyxl para .xlsx y xlrd para .xls.
    sheet_index=-1: lee todas las hojas y concatena los DataFrames.
    """

    def read(
        self,
        path: Path,
        sheet_index: int = 0,
        header_row: int | None = None,
    ) -> tuple[pd.DataFrame, FileMetadata]:
        path = Path(path)
        ext = path.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            raise FileReadError(
                f"Formato no soportado: '{path.name}'. "
                "Solo se aceptan archivos .xlsx y .xls."
            )

        if not path.exists():
            raise FileReadError(f"El archivo '{path.name}' no existe.")

        if sheet_index == -1:
            return self._read_all_sheets(path, ext, header_row)

        return self._read_single_sheet(path, ext, sheet_index, header_row)

    def inspect_header_rows(
        self,
        path: Path,
        sheet_index: int = 0,
    ) -> tuple[list[int], int]:
        """Inspecciona solo las primeras filas y devuelve candidatos y filas leidas."""
        path = Path(path)
        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise FileReadError(
                f"Formato no soportado: '{path.name}'. "
                "Solo se aceptan archivos .xlsx y .xls."
            )
        if not path.exists():
            raise FileReadError(f"El archivo '{path.name}' no existe.")
        if sheet_index < 0:
            return [], 0

        sheet_names = self._get_sheet_names(path, extension)
        if sheet_index >= len(sheet_names):
            raise FileReadError(
                f"La hoja seleccionada no existe en el archivo '{path.name}'."
            )
        engine = "openpyxl" if extension == ".xlsx" else "xlrd"
        try:
            raw = pd.read_excel(
                path,
                sheet_name=sheet_names[sheet_index],
                engine=engine,
                header=None,
                dtype=object,
                nrows=MAX_HEADER_SCAN_ROWS,
            )
        except Exception as exc:
            raise FileReadError(
                f"No se pudieron inspeccionar los encabezados de '{path.name}'."
            ) from exc
        return detect_header_rows(raw), len(raw)

    # ------------------------------------------------------------------
    # Lectura de hoja unica
    # ------------------------------------------------------------------

    def _read_single_sheet(
        self,
        path: Path,
        ext: str,
        sheet_index: int,
        header_row: int | None = None,
    ) -> tuple[pd.DataFrame, FileMetadata]:
        sheet_names = self._get_sheet_names(path, ext)

        if sheet_index >= len(sheet_names):
            sheet_index = 0

        sheet_name = sheet_names[sheet_index]
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"

        try:
            raw = pd.read_excel(
                path,
                sheet_name=sheet_name,
                engine=engine,
                header=None,
                dtype=object,
            )
        except Exception as exc:
            raise FileReadError(
                f"El archivo '{path.name}' no pudo leerse. "
                "Verifica que sea un Excel valido (.xlsx o .xls)."
            ) from exc

        if len(raw) < 2:
            raise EmptyFileError(
                f"El archivo '{path.name}' no tiene datos en la hoja '{sheet_name}'."
            )

        warnings: list[str] = []
        detected_rows = detect_header_rows(raw)
        selected_header = self._select_header_row(
            raw, header_row, detected_rows, path.name, warnings
        )
        if selected_header >= len(raw) - 1:
            raise EmptyFileError(
                f"El archivo '{path.name}' no tiene filas de datos debajo del encabezado "
                f"seleccionado en la hoja '{sheet_name}'."
            )
        raw_columns = raw.iloc[selected_header].tolist()
        normalized_names = self._normalize_columns(raw_columns, path.name, warnings)

        df = raw.iloc[selected_header + 1 :].copy()
        df.columns = normalized_names
        df = df.reset_index(drop=True)
        df = df.astype(str).replace("nan", "")

        metadata = FileMetadata(
            path=path,
            sheet_names=sheet_names,
            sheet_used=sheet_name,
            row_count=len(df),
            column_names=list(df.columns),
            warnings=warnings,
            header_row_index=selected_header,
            header_candidates=detected_rows[:5],
            header_scan_rows=min(MAX_HEADER_SCAN_ROWS, len(raw)),
        )

        return df, metadata

    # ------------------------------------------------------------------
    # Lectura de todas las hojas (concatenacion)
    # ------------------------------------------------------------------

    def _read_all_sheets(
        self,
        path: Path,
        ext: str,
        header_row: int | None = None,
    ) -> tuple[pd.DataFrame, FileMetadata]:
        sheet_names = self._get_sheet_names(path, ext)
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"

        dfs: list[pd.DataFrame] = []
        all_warnings: list[str] = []
        first_header_row = 0
        first_header_candidates: list[int] = []
        first_header_scan_rows = 0

        for sheet_index, sheet_name in enumerate(sheet_names):
            try:
                raw = pd.read_excel(
                    path,
                    sheet_name=sheet_name,
                    engine=engine,
                    header=None,
                    dtype=object,
                )
            except Exception:
                all_warnings.append(
                    f"La hoja '{sheet_name}' no pudo leerse y fue omitida."
                )
                continue

            if len(raw) < 2:
                all_warnings.append(
                    f"La hoja '{sheet_name}' no tiene datos y fue omitida."
                )
                continue

            detected_rows = detect_header_rows(raw)
            selected_header = self._select_header_row(
                raw, header_row, detected_rows, f"{path.name} ({sheet_name})",
                all_warnings,
            )
            if selected_header >= len(raw) - 1:
                all_warnings.append(
                    f"La hoja '{sheet_name}' no tiene datos debajo del encabezado seleccionado "
                    "y fue omitida."
                )
                continue
            if first_header_scan_rows == 0:
                first_header_row = selected_header
                first_header_candidates = detected_rows[:5]
                first_header_scan_rows = min(MAX_HEADER_SCAN_ROWS, len(raw))
            raw_columns = raw.iloc[selected_header].tolist()
            normalized = self._normalize_columns(
                raw_columns, f"{path.name} ({sheet_name})", all_warnings
            )
            df_sheet = raw.iloc[selected_header + 1 :].copy()
            df_sheet.columns = normalized
            df_sheet = df_sheet.reset_index(drop=True)
            df_sheet = df_sheet.astype(str).replace("nan", "")
            dfs.append(df_sheet)

        if not dfs:
            raise EmptyFileError(
                f"El archivo '{path.name}' no tiene datos en ninguna hoja."
            )

        # Concatenar; columnas faltantes en alguna hoja quedan como cadena vacia.
        combined = pd.concat(dfs, ignore_index=True, join="outer").fillna("")

        if len(sheet_names) > 1:
            all_warnings.insert(
                0,
                f"Se combinaron {len(dfs)} hoja(s) de {len(sheet_names)} disponibles. "
                "Filas de hojas con columnas distintas tendran celdas vacias en las columnas faltantes.",
            )

        metadata = FileMetadata(
            path=path,
            sheet_names=sheet_names,
            sheet_used="Todas las hojas",
            row_count=len(combined),
            column_names=list(combined.columns),
            warnings=all_warnings,
            header_row_index=first_header_row,
            header_candidates=first_header_candidates,
            header_scan_rows=first_header_scan_rows,
        )

        return combined, metadata

    def _select_header_row(
        self,
        raw: pd.DataFrame,
        requested_row: int | None,
        candidates: list[int],
        filename: str,
        warnings: list[str],
    ) -> int:
        """Elige el encabezado detectado o valida la fila corregida por el usuario."""
        limit = min(MAX_HEADER_SCAN_ROWS, len(raw))
        if requested_row is not None:
            if not isinstance(requested_row, int) or not 0 <= requested_row < limit:
                raise FileReadError(
                    f"La fila de encabezado indicada para '{filename}' debe estar "
                    f"entre 1 y {limit}."
                )
            selected = requested_row
        elif candidates:
            selected = candidates[0]
        else:
            selected = 0

        if selected > 0:
            source = "elegida" if requested_row is not None else "detectada"
            warnings.append(
                f"Fila de encabezado {source}: {selected + 1} en '{filename}'. "
                "Verifica que las columnas reconocidas sean correctas."
            )
        return selected

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _get_sheet_names(self, path: Path, ext: str) -> list[str]:
        """Devuelve la lista de hojas sin leer el contenido."""
        try:
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            xl = pd.ExcelFile(path, engine=engine)
            return xl.sheet_names
        except Exception as exc:
            raise FileReadError(
                f"El archivo '{path.name}' no pudo leerse. "
                "Verifica que sea un Excel valido."
            ) from exc

    def _normalize_columns(
        self,
        raw_columns: list,
        filename: str,
        warnings: list[str],
    ) -> list[str]:
        """
        - Reemplaza celdas vacias (NaN, None, '') con 'Columna_<letra>'.
        - Desambigua nombres duplicados agregando sufijo numerico (_1, _2...).
        Preserva acentos y caracteres especiales del espanol (CA-03-02).
        """
        import string

        def col_letter(i: int) -> str:
            result = ""
            i += 1
            while i > 0:
                i, rem = divmod(i - 1, 26)
                result = string.ascii_uppercase[rem] + result
            return result

        normalized: list[str] = []
        for i, col in enumerate(raw_columns):
            col_str = str(col).strip() if col is not None else ""
            if col_str == "" or col_str.lower() in ("nan", "none"):
                col_str = f"Columna_{col_letter(i)}"
                warnings.append(
                    f"Columna sin encabezado en posicion {i + 1} del archivo '{filename}'. "
                    f"Se asigno el nombre '{col_str}'."
                )
            normalized.append(col_str)

        seen: dict[str, int] = {}
        result: list[str] = []
        has_duplicates = False
        for col in normalized:
            if col in seen:
                has_duplicates = True
                seen[col] += 1
                result.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 1
                result.append(col)

        if has_duplicates:
            warnings.append(
                f"El archivo '{filename}' tiene columnas con nombres duplicados. "
                "Se agregaron sufijos numericos para diferenciarlas."
            )

        return result
