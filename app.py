import streamlit as st
from pathlib import Path
import os
from datetime import datetime
import pandas as pd
from PIL import Image
import json
import base64
import re
import smtplib
from itsdangerous import URLSafeTimedSerializer
from email.mime.text import MIMEText
import bcrypt
from azure.storage.blob import BlobServiceClient
from io import BytesIO

# RESUMEN de Herramientas y Servicios de la APP
# Visual Studio Code para programar en python el código de la app (C:\Users\david\Documents\Streamlit\Albacete)
# Streamlit Cloud para hospedar la app (https://share.streamlit.io/)
# GitHub para el despliegue de la app (https://github.com/dmmanchon/centro-recursos)
# Dominio creado en Microsoft @autoanalyzerpro.com para poder enviar enlaces de recuperación desde Mailjet y cuenta de Almacenamiento (https://admin.microsoft.com/?login_hint=autoanalyzerpro%40autoanalyzerpro.com&source=applauncher#/Domains/Details/autoanalyzerpro.com)
# Azure Blob Storage de Microsoft para el almacenamiento de archivos (https://portal.azure.com/#@autoanalyzerpro.com/resource/subscriptions/31d6b443-05de-4364-8ae6-c879d9350f7b/resourcegroups/app-recursos/providers/Microsoft.Storage/storageAccounts/recursoscentro1/containersList)
# Mailjet para enviar enlaces de recuperación automáticos (https://app.mailjet.com/onboarding)

# Configuración de Azure Blob Storage desde secrets
AZURE_CONNECTION_STRING = st.secrets["AZURE_CONNECTION_STRING"]
AZURE_CONTAINER_NAME = "archivos-app"

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

# Configuración del servidor SMTP (correo)
SMTP_SERVER = st.secrets["SMTP_SERVER"]
SMTP_PORT = st.secrets["SMTP_PORT"]
SMTP_USER = st.secrets["SMTP_USER"]
SMTP_PASS = st.secrets["SMTP_PASS"]

# URL base para enlaces de recuperación
APP_URL = st.secrets["APP_URL"]

# --- Configuración general de la app ---
st.set_page_config(page_title="Centro de Recursos Colaborativo", layout="wide")
st.markdown("<div id='inicio'></div>", unsafe_allow_html=True)

# --- LOGO Y TÍTULO --
if "usuario" not in st.session_state:
    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        try:
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
        except Exception as e:
            st.warning(f"No se pudo cargar el logo: {e}")
    else:
        st.title("Centro de Recursos Colaborativo")


# ---------- AUTENTICACIÓN ----------
# --- Configuración de tokens y correo ---
# --- Autenticación ---

SECRET_KEY = st.secrets["SECRET_KEY"]
SALT = "salt-recovery"
serializer = URLSafeTimedSerializer(SECRET_KEY)

def cargar_usuarios_desde_blob():
    blob_client = container_client.get_blob_client("usuarios.xlsx")
    stream = BytesIO()
    blob_client.download_blob().readinto(stream)
    stream.seek(0)
    return pd.read_excel(stream)

def guardar_usuarios_en_blob(df):
    blob_client = container_client.get_blob_client("usuarios.xlsx")
    stream = BytesIO()
    df.to_excel(stream, index=False)
    stream.seek(0)
    blob_client.upload_blob(stream, overwrite=True)

def send_recovery_email(mail_destino, token):
    recover_url = f"{APP_URL}/?token={token}"
    mensaje = MIMEText(
        f"Haz clic en el siguiente enlace para restablecer tu contraseña:\n\n{recover_url}"
    )
    mensaje["Subject"] = "🔐 Recuperación de contraseña"
    mensaje["From"] = f"Centro de Recursos <{st.secrets['EMAIL_FROM']}>"
    mensaje["To"] = mail_destino

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(mensaje)
        st.success("✅ Enlace de recuperación enviado al correo electrónico.")
    except Exception as e:
        st.error(f"❌ Error al enviar el correo: {e}")

# --- Procesar token desde URL ---
params = st.query_params
token_param = params.get("token", [None])[0]
if token_param:
    try:
        email = serializer.loads(token_param, salt=SALT, max_age=1800)
    except Exception:
        st.error("Enlace inválido o caducado.")
        st.stop()

    st.subheader("🔑 Restablecer contraseña")
    nueva = st.text_input("Nueva contraseña", type="password")
    confirmar = st.text_input("Confirmar contraseña", type="password")
    if st.button("Cambiar contraseña"):
        if nueva and nueva == confirmar:
            hashed = bcrypt.hashpw(nueva.encode(), bcrypt.gensalt()).decode()
            usuarios_df = cargar_usuarios_desde_blob()
            usuarios_df.loc[usuarios_df["mail"] == email, "contraseña"] = hashed
            guardar_usuarios_en_blob(usuarios_df)
            st.success("Contraseña actualizada. Vuelve al login.")
        else:
            st.error("Las contraseñas no coinciden.")
    st.stop()

# --- LOGIN ---
usuarios_df = cargar_usuarios_desde_blob()
if "usuario" not in st.session_state:
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.markdown("""<div style='padding: 2rem; background-color: #fafafa;
                        border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.1);'>""",
                    unsafe_allow_html=True)

        st.subheader("🔐 Iniciar sesión")
        usuario_input = st.text_input("Correo electrónico")
        contrasena_input = st.text_input("Contraseña", type="password")

        if st.button("Acceder"):
            user_row = usuarios_df[usuarios_df["mail"] == usuario_input]
            if (not user_row.empty and
                bcrypt.checkpw(contrasena_input.encode(), user_row.iloc[0]["contraseña"].encode())):
                st.session_state.usuario = user_row.iloc[0]["usuario"]
                st.session_state.area = user_row.iloc[0]["area"]
                st.session_state.permisos = user_row.iloc[0]["permisos"].split(",")
                st.session_state.rol = user_row.iloc[0]["rol"]
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

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
        st.markdown("</div>", unsafe_allow_html=True)

    st.stop()


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

# ---------- DEFINICIÓN DE PREFIJO PARA BLOB STORAGE ----------
azure_prefix = area_map[area] + "/"  # Ejemplo: 'direccion_deportiva/'


# ---------- ENLACES EN SIDEBAR ----------
sidebar_enlaces = []
enlace_blob_path = f"{azure_prefix}enlaces.txt"
try:
    enlaces_bytes = container_client.get_blob_client(enlace_blob_path).download_blob().readall()
    for line in enlaces_bytes.decode("utf-8").splitlines():
        try:
            nombre, enlace = line.strip().split("::")
            sidebar_enlaces.append((nombre, enlace))
        except:
            continue
except Exception:
    pass  # Si no existe el blob de enlaces, no se muestra nada

# ---------- FUNCIONES AUXILIARES ----------
def generar_id_archivo(nombre_archivo):
    base = Path(nombre_archivo).stem
    base = base.lower().replace(" ", "_")
    base = re.sub(r'\W+', '', base)
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

# ---------- LISTADO DE ARCHIVOS EN SIDEBAR ----------
archivos_sidebar = []
for blob in container_client.list_blobs(name_starts_with=azure_prefix):
    if not blob.name.endswith(".meta.json") and not blob.name.endswith("enlaces.txt"):
        archivos_sidebar.append((blob.name, blob.last_modified))

# Ordenar por fecha de modificación
archivos_sidebar.sort(key=lambda x: x[1], reverse=True)

with st.sidebar.expander(f"📂 Archivos disponibles: {len(archivos_sidebar)}"):
    for blob_name, last_mod in archivos_sidebar:
        file_name = blob_name.split("/")[-1]
        meta_name = f"{blob_name}.meta.json"
        try:
            meta_bytes = container_client.get_blob_client(meta_name).download_blob().readall()
            meta = json.loads(meta_bytes)
            visible_name = meta.get("nombre_original", file_name)
        except:
            visible_name = file_name

        ancla = generar_id_archivo(visible_name)
        icono = icono_archivo(file_name)
        st.markdown(f"- {icono} [{visible_name}](#{ancla})")

with st.sidebar.expander(f"🔗 Enlaces compartidos: {len(sidebar_enlaces)}"):
    for nombre, enlace in sidebar_enlaces:
        st.markdown(f"- [{nombre}]({enlace})")


# ---------- INTERFAZ PRINCIPAL ----------
st.markdown(f"## {area}")
st.markdown("### 🔎 Buscar archivos")
search_query = st.text_input("Buscar por nombre o descripción").lower()

# ---------- FUNCIONES AZURE BLOB ----------

def subir_a_blob(nombre_archivo, contenido_bytes):
    blob_client = container_client.get_blob_client(nombre_archivo)
    blob_client.upload_blob(contenido_bytes, overwrite=True)

def listar_blobs():
    return container_client.list_blobs()

def descargar_blob(nombre_archivo):
    blob_client = container_client.get_blob_client(nombre_archivo)
    stream = blob_client.download_blob()
    return stream.readall()

def eliminar_blob(nombre_archivo):
    blob_client = container_client.get_blob_client(nombre_archivo)
    blob_client.delete_blob()

def mostrar_pdf(contenido_pdf):
    import base64
    base64_pdf = base64.b64encode(contenido_pdf).decode('utf-8')
    pdf_display = f"""
        <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)

def mostrar_excel(contenido_excel, extension):
    import pandas as pd
    from io import BytesIO

    try:
        if extension == ".csv":
            df = pd.read_csv(BytesIO(contenido_excel))
        else:
            df = pd.read_excel(BytesIO(contenido_excel), engine="openpyxl")
        st.dataframe(df)
    except Exception as e:
        st.error("No se pudo mostrar el contenido del archivo.")
        st.exception(e)

# ---------- SUBIDA DE ARCHIVOS ----------
if "subir" in permisos:
    st.markdown("### 📤 Subida de archivos")
    comentario_input = st.text_area("Comentario o descripción (opcional)")
    uploaded_file = st.file_uploader(
        "Selecciona un archivo",
        type=["pdf", "xlsx", "xls", "csv", "mp4", "mov", "jpg", "jpeg", "png", "gif"]
    )

    if uploaded_file:
        original_name = uploaded_file.name
        timestamp_fn = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_filename = f"{timestamp_fn}_{original_name}"
        blob_name = f"{azure_prefix}{safe_filename}"

        # Subir archivo
        subir_a_blob(blob_name, uploaded_file.getvalue())

        # Crear metadatos
        meta = {
            "usuario": st.session_state.usuario,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "comentario": comentario_input.strip(),
            "nombre_original": original_name
        }
        meta_str = json.dumps(meta, ensure_ascii=False)
        subir_a_blob(f"{blob_name}.meta.json", meta_str.encode("utf-8"))

        st.success(f"✅ Archivo **{original_name}** y sus metadatos subidos correctamente.")


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

# Aplicar orden
if orden == "Más recientes":
    archivos_sidebar.sort(key=lambda x: x[1], reverse=True)
elif orden == "Más antiguos":
    archivos_sidebar.sort(key=lambda x: x[1])
elif orden == "Nombre A-Z":
    archivos_sidebar.sort(key=lambda x: x[0].lower())
elif orden == "Nombre Z-A":
    archivos_sidebar.sort(key=lambda x: x[0].lower(), reverse=True)

# Aplicar filtro
filtered_files = []
for blob_name, mod in archivos_sidebar:
    try:
        meta_bytes = container_client.get_blob_client(blob_name + ".meta.json").download_blob().readall()
        meta = json.loads(meta_bytes)
    except:
        meta = {}

    nombre = meta.get("nombre_original", Path(blob_name).name).lower()
    comentario = meta.get("comentario", "").lower()

    if search_query in nombre or search_query in comentario:
        filtered_files.append((blob_name, meta))

# Mostrar archivos en cuadrícula
chunks = [filtered_files[i:i + num_cols] for i in range(0, len(filtered_files), num_cols)]
for chunk in chunks:
    cols = st.columns(num_cols)
    for (blob_name, meta), col in zip(chunk, cols):
        with col:
            blob_path = Path(blob_name)
            original = meta.get("nombre_original", blob_path.name)
            suffix = blob_path.suffix.lower()
            ancla = generar_id_archivo(original)

            st.markdown(f"<div id='{ancla}'></div>", unsafe_allow_html=True)
            st.markdown(f"### {original}", unsafe_allow_html=True)
            usuario = meta.get("usuario", "desconocido")
            fecha = meta.get("fecha", "")
            st.markdown(f"*Subido por {usuario} el {fecha}*", unsafe_allow_html=True)

            contenido = descargar_blob(blob_name)
            if suffix == ".pdf":
                st.download_button("📥 Descargar PDF", data=contenido, file_name=blob_path.name)
                mostrar_pdf(contenido)
            elif suffix in [".xlsx", ".xls", ".csv"]:
                st.download_button("📥 Descargar Excel/CSV", data=contenido, file_name=blob_path.name)
                mostrar_excel(contenido, suffix)
            elif suffix in [".mp4", ".mov"]:
                st.download_button("📥 Descargar Vídeo", data=contenido, file_name=blob_path.name)
                st.video(contenido)
            elif suffix in [".jpg", ".jpeg", ".png", ".gif"]:
                st.download_button("📥 Descargar Imagen", data=contenido, file_name=blob_path.name)
                st.image(contenido, use_column_width=True)
            else:
                st.download_button("📥 Descargar Archivo", data=contenido, file_name=blob_path.name)

            comentario = st.text_area("💬 Comentario", value=meta.get("comentario", ""), key=f"comentario_{blob_name}")
            if st.button("💾 Guardar comentario", key=f"guardar_comentario_{blob_name}"):
                meta["comentario"] = comentario
                meta_str = json.dumps(meta, ensure_ascii=False)
                subir_a_blob(blob_name + ".meta.json", meta_str.encode("utf-8"))
                st.success("Comentario actualizado.")

            if st.button("🗑️ Eliminar archivo", key=f"eliminar_{blob_name}"):
                eliminar_blob(blob_name)
                eliminar_blob(blob_name + ".meta.json")
                st.warning("Archivo eliminado. Recarga para ver los cambios.")

            st.markdown("---")

# ---------- ENLACES COMPARTIDOS ----------
st.markdown("### 🔗 Enlaces compartidos")
nombre_url = st.text_input("Título o descripción")
url = st.text_input("Introduce un enlace (https://...)")

if "subir" in permisos and st.button("Guardar enlace"):
    if url and nombre_url:
        # Descargar enlaces actuales
        enlaces_blob = f"{azure_prefix}enlaces.txt"
        try:
            enlaces_bytes = container_client.get_blob_client(enlaces_blob).download_blob().readall()
            contenido_actual = enlaces_bytes.decode("utf-8")
        except:
            contenido_actual = ""

        nuevo_contenido = contenido_actual + f"{nombre_url}::{url}\n"
        subir_a_blob(enlaces_blob, nuevo_contenido.encode("utf-8"))
        st.success("✅ Enlace guardado correctamente.")
