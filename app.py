import streamlit as st
from pathlib import Path
import os
import datetime
import pandas as pd
from PIL import Image
import json
import base64
import re
import smtplib
from itsdangerous import URLSafeTimedSerializer
from email.mime.text import MIMEText
import bcrypt

st.set_page_config(page_title="Centro de Recursos Colaborativo", layout="wide")
st.markdown("<div id='inicio'></div>", unsafe_allow_html=True)

# --- LOGO Y TÍTULO --
logo_path = Path("assets/logo.png")
if logo_path.exists():
    logo_base64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    st.markdown(
        f"""
        <div style='text-align: center;'>
            <img src='data:image/png;base64,{logo_base64}' style='height: 200px;' />
            <h1>Centro de Recursos Colaborativo</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

# ---------- AUTENTICACIÓN ----------
# --- Configuración de tokens y correo ---
SECRET_KEY = "TU_SECRETO_MUY_LARGO"
SALT = "salt-recovery"
serializer = URLSafeTimedSerializer(SECRET_KEY)

SMTP_SERVER = "smtp.tu-servidor.com"
SMTP_PORT = 587
SMTP_USER = "tu@correo.com"
SMTP_PASS = "tu-contraseña"

def send_recovery_email(destino_email, token):
    recover_url = st.get_url() + f"?token={token}"
    html = f"""
    <p>Hola,</p>
    <p>Haz clic <a href="{recover_url}">aquí</a> para restablecer tu contraseña. El enlace expirará en 30 min.</p>
    """
    msg = MIMEText(html, "html")
    msg["Subject"] = "Recuperación de contraseña"
    msg["From"] = SMTP_USER
    msg["To"] = destino_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

params = st.query_params
token_param = params.get("token", [None])[0]
if token_param:
    try:
        email = serializer.loads(token_param, salt=SALT, max_age=1800)  # 30 min
    except Exception:
        st.error("Enlace inválido o caducado.")
        st.stop()
    # Formulario de cambio de contraseña
    st.subheader("🔑 Restablecer contraseña")
    nueva = st.text_input("Nueva contraseña", type="password")
    confirmar = st.text_input("Confirmar contraseña", type="password")
    if st.button("Cambiar contraseña"):
        if nueva and nueva == confirmar:
            hashed = bcrypt.hashpw(nueva.encode(), bcrypt.gensalt()).decode()
            usuarios_df = pd.read_excel("usuarios.xlsx")
            usuarios_df.loc[usuarios_df["mail"] == email, "contraseña"] = hashed
            usuarios_df.to_excel("usuarios.xlsx", index=False)
            st.success("Contraseña actualizada. Vuelve al login.")
        else:
            st.error("Las contraseñas no coinciden.")
    st.stop()

usuarios_df = pd.read_excel("usuarios.xlsx")

if "usuario" not in st.session_state:

    # CENTRAR Y ENCERRAR TODO EN COLUMNAS
    cols = st.columns([1, 2, 1])
    with cols[1]:

        # DIV decorativo para el recuadro
        st.markdown("""
            <div style='padding: 2rem; background-color: #fafafa;
                        border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.1);'>
        """, unsafe_allow_html=True)

        # FORMULARIO DE LOGIN
        st.subheader("🔐 Iniciar sesión")
        usuario_input = st.text_input("Correo electrónico")
        contrasena_input = st.text_input("Contraseña", type="password")
        if st.button("Acceder"):
            user_row = usuarios_df[usuarios_df["mail"] == usuario_input]
            if (not user_row.empty and
                bcrypt.checkpw(contrasena_input.encode(),
                               user_row.iloc[0]["contraseña"].encode())):
                st.session_state.usuario = user_row.iloc[0]["usuario"]
                st.session_state.area = user_row.iloc[0]["area"]
                st.session_state.permisos = user_row.iloc[0]["permisos"].split(",")
                st.session_state.rol = user_row.iloc[0]["rol"]
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

        # RECUPERACIÓN DE CONTRASEÑA
        st.markdown("---")
        st.markdown("¿Olvidaste tu contraseña?")
        mail_recup = st.text_input("Introduce tu correo para recuperación", key="recup")
        if st.button("Enviar enlace de recuperación"):
            if mail_recup in usuarios_df["mail"].values:
                token = serializer.dumps(mail_recup, salt=SALT)
                send_recovery_email(mail_recup, token)
                st.success("Correo de recuperación enviado. Revisa tu bandeja.")
            else:
                st.error("Correo no registrado.")

        # CIERRE DEL DIV
        st.markdown("</div>", unsafe_allow_html=True)

    # Evitamos que continúe si aún no hay login
    st.stop()

usuario_actual = st.session_state.usuario

# ---------- VARIABLES DE SESIÓN ----------
usuario_actual = st.session_state.usuario
area_original = st.session_state.area
permisos = st.session_state.permisos
rol = st.session_state.rol

# ---------- MAPA DE ÁREAS DISPONIBLES ----------
area_map = {
    "Dirección Deportiva": "direccion_deportiva",
    "Cuerpo Técnico": "cuerpo_tecnico",
    "Servicios Médicos": "servicios_medicos"
}

# ---------- LOGO Y TEMPORADA EN LA PARTE SUPERIOR DEL SIDEBAR ----------
logo_path = Path("assets/logo.png")
if logo_path.exists():
    logo_base64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    st.sidebar.markdown(
        f"""
        <div style='display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;'>
            <span style='font-weight: bold; font-size: 3em;'>25/26</span>
            <img src='data:image/png;base64,{logo_base64}' style='height: 120px;' />
        </div>
        """,
        unsafe_allow_html=True
    )

# ---------- MENSAJE DE SESIÓN ----------
st.sidebar.markdown("### 🧑‍💼 Sesión iniciada")
st.sidebar.success(f"{usuario_actual} ({rol})")

# ---------- BOTÓN DE CIERRE DE SESIÓN ----------
if st.sidebar.button("Cerrar sesión"):
    st.session_state.clear()
    st.rerun()

# ---------- SELECCIÓN DE ÁREA (si tiene acceso total) ----------
if area_original == "todas":
    st.sidebar.markdown("---")
    area_opciones = list(area_map.keys())
    area = st.sidebar.selectbox("Selecciona área", area_opciones)
else:
    area = area_original

# ---------- DEFINICIÓN DE CARPETA PARA ARCHIVOS ----------
base_folder = Path("archivos")
area_folder = base_folder / area_map[area]
area_folder.mkdir(parents=True, exist_ok=True)


# ---------- ENLACES EN SIDEBAR ----------
enlace_file = area_folder / "enlaces.txt"
sidebar_enlaces = []
if enlace_file.exists():
    with open(enlace_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                nombre, enlace = line.strip().split("::")
                sidebar_enlaces.append((nombre, enlace))
            except:
                continue


# ---------- RESUMEN EN SIDEBAR ----------
def generar_id_archivo(nombre_archivo):
    base = Path(nombre_archivo).stem
    base = base.lower().replace(" ", "_")
    base = re.sub(r'\W+', '', base)  # eliminar todo lo que no sea letra, número o _
    return f"id_{base}"

def icono_archivo(nombre_archivo):
    ext = Path(nombre_archivo).suffix.lower()
    if ext == ".pdf":
        return "📄"
    elif ext in [".xlsx", ".xls", ".csv"]:
        return "📊"
    elif ext in [".mp4", ".mov"]:
        return "🎥"
    elif ext in [".jpg", ".jpeg", ".png", ".gif"]:
        return "🖼️"
    else:
        return "📁"

archivos_sidebar = []
for f in area_folder.glob("*"):
    if f.is_file() and not f.name.endswith(".meta.json") and f.name != "enlaces.txt":
        archivos_sidebar.append(f)

# Ordenar por fecha de modificación (más reciente primero)
archivos_sidebar = sorted(archivos_sidebar, key=os.path.getmtime, reverse=True)

with st.sidebar.expander(f"📂 Archivos disponibles: {len(archivos_sidebar)}"):
    for f in archivos_sidebar:
        # nombre visible
        meta_path = f.with_suffix(f.suffix + ".meta.json")
        nombre = f.name
        if meta_path.exists():
            try:
                meta = json.load(open(meta_path, "r", encoding="utf-8"))
                nombre = meta.get("nombre_original", nombre)
            except:
                pass

        ancla = generar_id_archivo(nombre)
        icono = icono_archivo(f.name)
        st.markdown(f"- {icono} [{nombre}](#{ancla})")

with st.sidebar.expander(f"🔗 Enlaces compartidos: {len(sidebar_enlaces)}"):
    for nombre, enlace in sidebar_enlaces:
        st.markdown(f"- [{nombre}]({enlace})")


# ---------- INTERFAZ PRINCIPAL ----------
st.markdown(f"## {area}")
st.markdown("### 🔎 Buscar archivos")
search_query = st.text_input("Buscar por nombre o descripción").lower()

# ---------- SUBIDA DE ARCHIVOS ----------
if "subir" in permisos:
    st.markdown("### 📤 Subida de archivos")
    comentario_input = st.text_area("Comentario o descripción (opcional)")
    uploaded_file = st.file_uploader("Selecciona un archivo", type=["pdf", "xlsx", "xls", "csv", "mp4", "mov", "jpg", "jpeg", "png", "gif"])

    if uploaded_file:
        for f in area_folder.glob("*"):
            if f.is_file() and not f.name.endswith(".meta.json") and f.name != "enlaces.txt":
                meta_path = f.with_suffix(f.suffix + ".meta.json")
                if meta_path.exists():
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                    if meta.get("nombre_original") == uploaded_file.name:
                        f.unlink()
                        meta_path.unlink()

        # Timestamp y usuario actual
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        usuario_meta = st.session_state.usuario

        # Guarda el archivo como hasta ahora
        timestamp_fn = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_filename = f"{timestamp_fn}_{uploaded_file.name}"
        filepath = area_folder / safe_filename
        with open(filepath, "wb") as f:
            f.write(uploaded_file.read())

        # Nuevo JSON de metadatos, incluyendo usuario y fecha
        meta = {
            "nombre_original": uploaded_file.name,
            "comentario": comentario_input.strip(),
            "usuario": usuario_meta,
            "timestamp": timestamp_str
        }
        meta_path = filepath.with_suffix(filepath.suffix + ".meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        st.success(f"✅ Archivo guardado: {uploaded_file.name}")
 
# ---------- VISUALIZACIÓN Y GESTIÓN DE ARCHIVOS ----------
st.markdown("---")
st.markdown("### 📁 Archivos disponibles")

# ---------- CONTROLES DE VISTA ----------
col1, col2 = st.columns(2)
with col1:
    orden = st.selectbox("Ordenar por", ["Más recientes", "Más antiguos", "Nombre A-Z", "Nombre Z-A"])
with col2:
    vista = st.selectbox("Vista", ["1 columna", "2 columnas", "3 columnas"])
    num_cols = int(vista.split()[0])

files = [f for f in area_folder.glob("*") if not f.name.endswith(".meta.json") and f.name != "enlaces.txt"]

if orden == "Más recientes":
    files = sorted(files, key=os.path.getmtime, reverse=True)
elif orden == "Más antiguos":
    files = sorted(files, key=os.path.getmtime)
elif orden == "Nombre A-Z":
    files = sorted(files, key=lambda x: x.name.lower())
elif orden == "Nombre Z-A":
    files = sorted(files, key=lambda x: x.name.lower(), reverse=True)

if search_query:
    filtered_files = []
    for file in files:
        meta_path = file.with_suffix(file.suffix + ".meta.json")
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            nombre = meta.get("nombre_original", file.name).lower()
            comentario = meta.get("comentario", "").lower()
            if search_query in nombre or search_query in comentario:
                filtered_files.append((file, meta))
        else:
            if search_query in file.name.lower():
                filtered_files.append((file, {}))
else:
    filtered_files = [(file, json.load(open(file.with_suffix(file.suffix + ".meta.json"), "r", encoding="utf-8"))) if file.with_suffix(file.suffix + ".meta.json").exists() else (file, {}) for file in files]

chunks = [filtered_files[i:i + num_cols] for i in range(0, len(filtered_files), num_cols)]
for chunk in chunks:
    cols = st.columns(num_cols)
    for (file, meta), col in zip(chunk, cols):
        with col:
            ancla = generar_id_archivo(file.name)
            st.markdown(f"<div id='{ancla}'></div>", unsafe_allow_html=True)
            nombre = meta.get("nombre_original", file.name)
            usuario_meta = meta.get("usuario", "desconocido")
            timestamp_meta = meta.get("timestamp", "")
            comentario = meta.get("comentario", "")
            st.markdown(f"<h4 style='margin-bottom:0.2rem;'>{nombre}</h4>", unsafe_allow_html=True)
            st.markdown(
                f"<p style='font-size:0.8rem; color:gray; margin-top:0;margin-bottom:0.5rem;'>"
                f"Subido por {usuario_meta} el {timestamp_meta}</p>",
                unsafe_allow_html=True
            )

            if comentario:
                st.markdown(f"📝 *{comentario}*")

            if file.suffix == ".pdf":
                st.download_button("⬇️ Descargar PDF", file.read_bytes(), file_name=nombre)
                st.markdown("ℹ️ Vista previa no disponible en la nube.")
            elif file.suffix in [".mp4", ".mov"]:
                st.video(str(file))
                st.download_button("⬇️ Descargar video", file.read_bytes(), file_name=nombre)
            elif file.suffix in [".xlsx", ".xls", ".csv"]:
                df = pd.read_excel(file) if file.suffix != ".csv" else pd.read_csv(file)
                st.dataframe(df.head())
                st.download_button("⬇️ Descargar tabla", file.read_bytes(), file_name=nombre)
            elif file.suffix in [".jpg", ".jpeg", ".png", ".gif"]:
                img = Image.open(file)
                st.image(img, caption=nombre, use_container_width=True)
                st.download_button("⬇️ Descargar imagen", file.read_bytes(), file_name=nombre)
            else:
                st.download_button("⬇️ Descargar archivo", file.read_bytes(), file_name=nombre)

            if "editar" in permisos:
                with st.expander("✏️ Editar comentario"):
                    nuevo_comentario = st.text_area("Editar comentario", value=comentario, key=file.name)
                    if st.button("💾 Guardar", key=f"guardar_{file.name}"):
                        meta["comentario"] = nuevo_comentario.strip()
                        with open(file.with_suffix(file.suffix + ".meta.json"), "w", encoding="utf-8") as f:
                            json.dump(meta, f)
                        st.success("Comentario actualizado.")

            if "subir" in permisos:
                with st.expander("🔄 Actualizar este archivo"):
                    archivo_nuevo = st.file_uploader("Selecciona un archivo nuevo", key=f"update_{file.name}")
                    if archivo_nuevo:
                        file.unlink()
                        meta_path = file.with_suffix(file.suffix + ".meta.json")
                        if meta_path.exists():
                            meta_path.unlink()

                        # elimina el anterior...
                        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        usuario_meta = st.session_state.usuario

                        timestamp_fn = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                        nuevo_nombre = f"{timestamp_fn}_{archivo_nuevo.name}"
                        nueva_ruta = area_folder / nuevo_nombre
                        with open(nueva_ruta, "wb") as f:
                            f.write(archivo_nuevo.read())

                        nuevo_meta = {
                            "nombre_original": archivo_nuevo.name,
                            "comentario": comentario,
                            "usuario": usuario_meta,
                            "timestamp": timestamp_str
                        }
                        new_meta_path = nueva_ruta.with_suffix(nueva_ruta.suffix + ".meta.json")
                        with open(new_meta_path, "w", encoding="utf-8") as f:
                            json.dump(nuevo_meta, f)

                        st.success("Archivo actualizado correctamente.")

            if "eliminar" in permisos:
                if st.button("🗑️ Eliminar", key=f"delete_{file.name}"):
                    file.unlink()
                    meta_path = file.with_suffix(file.suffix + ".meta.json")
                    if meta_path.exists():
                        meta_path.unlink()
                    st.warning(f"Archivo eliminado. Recarga la página para ver los cambios.")

            st.markdown("---")

# ---------- ENLACES COMPARTIDOS ----------
st.markdown("### 🔗 Enlaces compartidos")
nombre_url = st.text_input("Título o descripción")
url = st.text_input("Introduce un enlace (https://...)")

if "subir" in permisos and st.button("Guardar enlace"):
    if url and nombre_url:
        with open(enlace_file, "a", encoding="utf-8") as f:
            f.write(f"{nombre_url}::{url}\n")
        st.success("✅ Enlace guardado correctamente.")

if enlace_file.exists():
    with open(enlace_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                nombre, enlace = line.strip().split("::")
                st.markdown(f"- 🔗 [{nombre}]({enlace})")
            except:
                continue
else:
    st.info("No hay enlaces aún.")
