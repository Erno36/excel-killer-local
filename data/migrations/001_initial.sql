-- Migracion 001: esquema inicial
-- Aplica cuando PRAGMA user_version = 0 (base recien creada).

-- Tabla de usuarios del sistema.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,       -- prefijo $2b$ (bcrypt)
    is_active     INTEGER NOT NULL DEFAULT 1,  -- 1=activo, 0=desactivado
    is_test       INTEGER NOT NULL DEFAULT 0,  -- 1=usuario de prueba (no en produccion)
    created_at    TEXT    NOT NULL,            -- ISO 8601
    updated_at    TEXT    NOT NULL
);

-- Tabla de intentos de login (para bloqueo temporal por intentos fallidos).
CREATE TABLE IF NOT EXISTS login_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT    NOT NULL,
    attempted_at TEXT    NOT NULL,   -- ISO 8601
    success      INTEGER NOT NULL    -- 0=fallido, 1=exitoso
);

-- Indice para acelerar la consulta de intentos recientes por usuario.
CREATE INDEX IF NOT EXISTS idx_login_attempts_user_time
    ON login_attempts(username, attempted_at);

-- Actualizar version de esquema.
PRAGMA user_version = 1;
