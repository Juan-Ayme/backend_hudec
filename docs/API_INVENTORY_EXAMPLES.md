# Ejemplos de Consumo de API (Analíticas de Inventario y Ventas)

A continuación te detallo la documentación y ejemplos para interactuar con la API (usando `curl` como ejemplo, pero son endpoints HTTP GET / POST estándar consumibles desde JS/React/Vue o Postman).

## 1. Endpoints Básicos de Productos de Alta Rotación y "Huesos" (NUEVO)

Hemos creado dos endpoints dedicados específicamente para solventar tu requerimiento de saber qué comprar rápido (alta rotación) y qué productos son "huesos" (capital inmovilizado).

### A. Productos de Alta Rotación (`/analytics/inventory/fast-moving`)

Este endpoint te entrega los productos que se están vendiendo **rápido** y que se agotarán pronto basándose en el análisis de las últimas recepciones, el cálculo algorítmico de la WMA (Promedio Móvil Ponderado) de la demanda y los **Días de Cobertura** (`dias_cobertura`). 

Están ordenados desde el producto que **más rápido se va a quedar sin stock** hasta los que tienen un poco más de aire.

**Request:**
```bash
curl -X 'GET' \
  'http://localhost:8000/analytics/inventory/fast-moving?top=20' \
  -H 'accept: application/json'
```

**Respuesta de ejemplo:**
```json
{
  "data": [
    {
      "bsale_product_id": 4125,
      "product_name": "Serum Facial Hidratante 30ml",
      "department": "Skincare",
      "category": "Serums",
      "abc": "A",
      "xyz": "X",
      "stock_total": 12.0,
      "demand_diaria_efectiva": 4.5,
      "dias_cobertura": 2.6,
      "estado_stock": "2. BAJO ROP",
      "rop": 40.0
    }
  ],
  "resumen": {
    "total_productos_alta_rotacion_mostrados": 20
  }
}
```

---

### B. Productos "Huesos" o Muertos (`/analytics/inventory/dead-stock`)

Este endpoint detecta todo el inventario estancado (muerto o huesos). Se define como "hueso" a un producto que tiene stock disponible mayor a 0, pero su **demanda diaria efectiva es 0** (no se ha vendido nada en las últimas semanas) o tiene más de 180 días de cobertura (vas a tardar medio año en venderlo).

Se ordena descendentemente por el costo o **Capital Inmovilizado** (para que sepas cuánta plata estás perdiendo al tenerlo ahí parado).

**Request:**
```bash
curl -X 'GET' \
  'http://localhost:8000/analytics/inventory/dead-stock?top=20' \
  -H 'accept: application/json'
```

**Respuesta de ejemplo:**
```json
{
  "data": [
    {
      "bsale_product_id": 894,
      "product_name": "Esmalte Color Lila Antiguo",
      "department": "Maquillaje",
      "category": "Uñas",
      "stock_total": 150.0,
      "costo_unitario": 2000.0,
      "inv_valor_costo": 300000.0,
      "demand_diaria_efectiva": 0.0,
      "dias_cobertura": 9999.0,
      "dias_desde_recepcion": 45
    }
  ],
  "resumen": {
    "total_capital_inmovilizado": 4500000.0,
    "total_productos_huesos": 250
  }
}
```

---

## 2. Puntos de Reorden, Alertas y ABC/XYZ

Si necesitas ir más a fondo que una simple lista y buscas parámetros predictivos:

### A. Alertas de Reposición Urgente (ROP)

Enfocado estrictamente en mostrar lo que se encuentra "Bajo ROP" (Punto de reorden). 

**Request:**
```bash
curl -X 'GET' \
  'http://localhost:8000/analytics/inventory/alerts' \
  -H 'accept: application/json'
```

**Respuesta:**
```json
{
  "total_bajo_rop": 45,
  "alertas": [
    {
      "bsale_product_id": 140,
      "product_name": "Shampoo Reparador 1L",
      "abc": "A",
      "stock_total": 5.0,
      "rop": 15.0
    }
  ],
  "parametros": {
    "z": 1.65,
    "lead_time_d": 7,
    "nivel_servicio": "95%"
  }
}
```

### B. Rendimiento del Capital (GMROI)

¿Qué productos te dejan más dinero por cada peso invertido en tenerlos en stock?

**Request:**
```bash
curl -X 'GET' \
  'http://localhost:8000/analytics/inventory/gmroi?top=10' \
  -H 'accept: application/json'
```

**Respuesta:**
```json
{
  "data": [
    {
      "product_name": "Labial Matte Rojo Pasión",
      "abc": "A",
      "inv_valor_costo": 50000.0,
      "gmroi": 4.5,
      "inventory_turnover": 6.2,
      "rev_anual_est": 500000.0
    }
  ],
  "resumen": {
    "inventario_total_costo": 12500000.0,
    "revenue_anual_estimado": 45000000.0,
    "gmroi_global": 1.8
  }
}
```
*(Nota: Un GMROI de 4.5 significa que por cada $1 gastado en inventario para ese labial, recuperaste $4.5 en margen bruto a lo largo del año).*

---

## 3. Resumen Estructural de los Filtros en estos Endpoints

Todos los cálculos y APIs expuestas **solamente evalúan las ventas provenientes de las sucursales con ID 1 y 3**.
El almacén (ID 4) es utilizado **exclusivamente** para reportar el `stock_total` o el `inv_valor_costo` sumando los inventarios (es decir, en el ejemplo del labial anterior, el valor del costo o `stock_total` agrupa lo disponible en Almacén + Tiendas), **pero no impacta en nada a las proyecciones o rotaciones de venta**, que provienen netamente del flujo comercial en las sucursales reales.