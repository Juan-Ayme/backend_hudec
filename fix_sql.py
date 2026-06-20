import os
import re

sql_dir = "app/kawii_matrix/sql"
for file in os.listdir(sql_dir):
    if file.endswith(".sql"):
        filepath = os.path.join(sql_dir, file)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace :param::int[] with CAST(:param AS int[])
        new_content = re.sub(r':([a-zA-Z0-9_]+)::int\[\]', r'CAST(:\1 AS int[])', content)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Fixed {filepath}")
