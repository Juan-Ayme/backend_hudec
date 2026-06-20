import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

print("Conectando a la base de datos...")
conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'db_kawii_pluss'),
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'root')
)

print("Leyendo docs/schema.sql...")
with open('docs/schema.sql', 'r', encoding='utf-8-sig') as f:
    sql = f.read()

print("Ejecutando SQL...")
with conn.cursor() as cur:
    cur.execute(sql)
conn.commit()
conn.close()
print("¡Base de datos inicializada correctamente!")
