-- ============================================================
-- Migracion: Crear tabla users y conectar FK
-- Fecha: 2026-06-05
-- Descripcion: Crea catalogo de usuarios de BSale y establece
--              FK desde documents y receptions.
-- ============================================================

-- PASO 1: Crear la tabla de usuarios
CREATE TABLE IF NOT EXISTS users (
    bsale_user_id INTEGER PRIMARY KEY,
    first_name VARCHAR(200),
    last_name VARCHAR(200),
    email VARCHAR(300),
    bsale_office_id INTEGER REFERENCES offices(bsale_office_id),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_office ON users(bsale_office_id);

-- PASO 2: Ejecutar sync_users() ANTES de continuar con el paso 3.
-- Esto pobla la tabla users desde la API de BSale.
-- Comando: python -c "from harvester import db; from harvester.sync_masters import sync_users; db.init_pool(); print(sync_users()); db.close_pool()"

-- PASO 3: Limpiar IDs huerfanos (usuarios que ya no existen en BSale)
-- Poner NULL en documents donde el user_id no tiene match en users
UPDATE documents SET bsale_user_id = NULL
WHERE bsale_user_id IS NOT NULL
  AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users);

-- Poner NULL en receptions donde el user_id no tiene match en users
UPDATE receptions SET bsale_user_id = NULL
WHERE bsale_user_id IS NOT NULL
  AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users);

-- PASO 4: Agregar FK constraints
ALTER TABLE documents
    ADD CONSTRAINT documents_bsale_user_id_fkey
    FOREIGN KEY (bsale_user_id) REFERENCES users(bsale_user_id);

ALTER TABLE receptions
    ADD CONSTRAINT receptions_bsale_user_id_fkey
    FOREIGN KEY (bsale_user_id) REFERENCES users(bsale_user_id);
