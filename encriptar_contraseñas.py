import pandas as pd
import bcrypt

# Carga el archivo de usuarios
archivo = "usuarios.xlsx"
usuarios_df = pd.read_excel(archivo)

# Recorremos todas las filas
for i in usuarios_df.index:
    clave = str(usuarios_df.loc[i, "contraseña"])
    # Solo si aún no está encriptada (los hash bcrypt comienzan por $2b$)
    if not clave.startswith("$2b$"):
        hashed = bcrypt.hashpw(clave.encode(), bcrypt.gensalt()).decode()
        usuarios_df.loc[i, "contraseña"] = hashed

# Guardamos el Excel actualizado
usuarios_df.to_excel(archivo, index=False)
print("✅ Contraseñas actualizadas con bcrypt.")
