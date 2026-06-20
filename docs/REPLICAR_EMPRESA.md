# Replicar el sistema para una nueva empresa

> Modelo: **un despliegue por empresa** en el mismo servidor — cada empresa es una
> copia con su propio `.env` y su propia base de datos PostgreSQL. Aislamiento total,
> sin tocar código. Toda la configuración por empresa vive en su `.env`.

---

## Por qué este modelo

El sistema es mono-empresa: asume **una** cuenta BSale, **una** base de datos y **una**
taxonomía. Para varias empresas, lo más simple y seguro (para pocas empresas) es
replicar: cada una con su `.env` + DB. La marca es white-label (`BRAND_NAME`,
`CLASSIFICATION_LABEL`), así que cada copia se ve como su propia empresa.

---

## Pasos para dar de alta una empresa nueva

### 1. Crear su base de datos
```sql
CREATE DATABASE db_empresa_x;
```
(Aplicar el esquema / correr migraciones igual que en la empresa original. Ver
`schema.sql` y `alembic/`.)

### 2. Crear su `.env`
Copiar la plantilla y completar lo marcado con (*):
```bash
cp .env.example .env   # (o un .env por empresa si corren varias instancias)
```
Valores **por empresa**:
- `BRAND_NAME`, `CLASSIFICATION_LABEL` — su marca.
- `DB_NAME`, `DB_PASSWORD` — su base.
- `BSALE_TOKEN` — token de **su** cuenta BSale.
- `OFFICES_TIENDA`, `OFFICE_ALMACEN`, `TIPOS_VENTA`, `TIPOS_DEVOLUCION`, `TIPOS_TRASLADO`
  — IDs de **su** BSale (estables; se sacan una vez de su cuenta).
- `EXCLUDED_DEPARTMENTS`, `SEASONAL_DEPARTMENTS` — **por NOMBRE**, separados por `|`.

> ⚠️ **IDs de BSale vs IDs de taxonomía local.** Los IDs de sucursales y tipos de
> documento vienen de BSale y son estables por empresa → van por ID. Los departamentos/
> categorías son taxonomía LOCAL que el sync re-siembra (los IDs cambian) → por eso las
> exclusiones y lo estacional van por **NOMBRE**, no por ID.

### 3. Primer sync (ETL desde BSale)
```bash
python run_daily_sync.py --days 30   # carga inicial (ajustar días)
```
Esto puebla productos, stock, ventas, recepciones y **siembra la taxonomía** de la empresa.

### 4. Arrancar la API
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001   # un puerto por empresa
```
Al arrancar:
- Crea la tabla `app_config` y **siembra las exclusiones desde el `.env`** (por nombre).
- A partir de ahí, las exclusiones se ajustan en vivo desde la pantalla **Configuración**
  del frontend (la DB manda; el `.env` solo fue la semilla inicial).

### 5. Frontend
Apuntar el frontend de esa empresa a su API:
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001
```
(Un build/instancia de frontend por empresa, o un proxy por subdominio.)

### 6. Programar el sync diario
Task Scheduler (Windows) → `python run_daily_sync.py` para esa carpeta/empresa, ~3 AM.

---

## Convivencia en un solo servidor

- Cada empresa: su **DB** (mismo Postgres, distinto `DB_NAME`), su **puerto** de uvicorn
  (8000, 8001, 8002…), su **instancia** de frontend (o proxy por subdominio).
- Las restricciones (exclusiones/estacional) viven en el `.env` y la `app_config` de
  **cada** base → no se mezclan entre empresas.

## Checklist rápido

- [ ] `CREATE DATABASE` de la empresa + esquema/migraciones.
- [ ] `.env` con BSALE_TOKEN, DB_NAME, OFFICES/TIPOS, BRAND, EXCLUDED/SEASONAL (por nombre).
- [ ] `python run_daily_sync.py --days 30`.
- [ ] `uvicorn ... --port 800X`.
- [ ] Frontend con `NEXT_PUBLIC_API_BASE_URL` a ese puerto.
- [ ] Tarea programada del sync diario.
- [ ] Verificar en la pantalla Configuración que las exclusiones quedaron bien.

---

## Cuándo dejar este modelo

Si pasas de "pocas empresas que operas tú" a "muchos clientes que se registran solos"
(SaaS), conviene migrar a multi-tenant real (login + `tenant_id` o DB-por-tenant +
onboarding automático). Es un refactor grande; no vale la pena hasta tener volumen.
