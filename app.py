import streamlit as st
from pathlib import Path
import os
from datetime import datetime
import pytz
import pandas as pd
from PIL import Image
import json
import base64
import re
import smtplib
from itsdangerous import URLSafeTimedSerializer
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import bcrypt
from azure.storage.blob import BlobServiceClient
from io import BytesIO
from streamlit_cookies_manager import EncryptedCookieManager
from itsdangerous.exc import SignatureExpired, BadSignature
import urllib.parse

# RESUMEN de Herramientas y Servicios de la APP
# Visual Studio Code para programar en python el código de la app (C:\Users\david\Documents\Streamlit\Albacete)
# Streamlit Cloud para hospedar la app (https://share.streamlit.io/)
# GitHub para el despliegue de la app (https://github.com/dmmanchon/centro-recursos)
# Dominio en Microsoft @autoanalyzerpro.com para enviar enlaces de recuperación desde Mailjet y cuenta de Almacenamiento:
# (https://admin.microsoft.com/?login_hint=autoanalyzerpro%40autoanalyzerpro.com&source=applauncher#/Domains/Details/autoanalyzerpro.com)
# Azure Blob Storage de Microsoft para el almacenamiento de archivos:
# (https://portal.azure.com/#@autoanalyzerpro.com/resource/subscriptions/31d6b443-05de-4364-8ae6-c879d9350f7b/resourcegroups/app-recursos/providers/Microsoft.Storage/storageAccounts/recursoscentro1/containersList)
# Mailjet para enviar enlaces de recuperación automáticos (https://app.mailjet.com/onboarding)


# Configuración general de la app ---
st.set_page_config(
    page_title="Centro de Recursos Colaborativo",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown("<div id='inicio'></div>", unsafe_allow_html=True)

TIPOS_ARCHIVO = [
    "pdf", "doc", "docx", "ppt", "pptx",
    "xlsx", "xls", "csv", "mp4", "mov",
    "jpg", "jpeg", "png", "gif"
]

# Configuración de Azure Blob Storage desde secrets
# Conexiones y Clientes (Cacheado)
@st.cache_resource
def get_container_client():
    """Crea y devuelve un cliente para el contenedor de Azure, cacheado para reutilización."""
    blob_service_client = BlobServiceClient.from_connection_string(st.secrets["AZURE_CONNECTION_STRING"])
    container_client = blob_service_client.get_container_client("archivos-app")
    return container_client

container_client = get_container_client()

# Configuración del servidor SMTP (correo)
SMTP_SERVER = st.secrets["SMTP_SERVER"]
SMTP_PORT = st.secrets["SMTP_PORT"]
SMTP_USER = st.secrets["SMTP_USER"]
SMTP_PASS = st.secrets["SMTP_PASS"]

# URL base para enlaces de recuperación
APP_URL = st.secrets["APP_URL"]

# --- AUTENTICACIÓN ---

SECRET_KEY = st.secrets["SECRET_KEY"]
SALT = "salt-recovery"
serializer = URLSafeTimedSerializer(SECRET_KEY)

# --- FUNCIONES ---

@st.cache_data
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

@st.cache_data(ttl="5m")
def get_archivos_area(prefix):
    """
    Obtiene y cachea una lista de diccionarios, cada uno con los datos y metadatos de un archivo.
    """
    archivos_con_meta = []
    for blob in container_client.list_blobs(name_starts_with=prefix):
        if not blob.name.endswith(".meta.json") and not blob.name.endswith("enlaces.txt"):
            meta = {}
            try:
                # Intenta descargar y parsear el archivo de metadatos asociado
                meta_blob_name = f"{blob.name}.meta.json"
                meta_bytes = container_client.get_blob_client(meta_blob_name).download_blob().readall()
                meta = json.loads(meta_bytes)
            except Exception:
                # Si no hay metadatos, se usan valores por defecto
                meta = {"nombre_original": Path(blob.name).name, "comentario": "", "usuario": "N/A", "fecha": "N/A"}

            archivos_con_meta.append({
                "blob_name": blob.name,
                "last_modified": blob.last_modified,
                "meta": meta
            })
    return archivos_con_meta

@st.cache_data(ttl="5m")
def get_enlaces(prefix):
    """Obtiene y cachea la lista de enlaces compartidos desde enlaces.txt."""
    enlaces = []
    enlace_blob_path = f"{prefix}enlaces.txt"
    try:
        enlaces_bytes = container_client.get_blob_client(enlace_blob_path).download_blob().readall()
        for line in enlaces_bytes.decode("utf-8").splitlines():
            if "::" in line:
                nombre, enlace = line.strip().split("::", 1)
                enlaces.append((nombre, enlace))
    except Exception:
        pass # Si no existe el archivo, devuelve una lista vacía
    return enlaces

def send_recovery_email(mail_destino: str, token: str):
    # El token ya está en formato URL-safe, no lo volvemos a codificar
    recover_url = f"{APP_URL}?token={token}"

    # Construir correo multipart (texto + HTML)
    texto_plano = (
        "Hola,\n\n"
        "Para restablecer tu contraseña copia o haz clic en el siguiente enlace:\n\n"
        f"{recover_url}\n\n"
        "Si no fuiste tú, ignora este mensaje."
    )
    html = f"""
    <html><body>
      <p>Hola,</p>
      <p>Para restablecer tu contraseña, pulsa este botón:</p>
      <p><a href="{recover_url}"
            style="display:inline-block;padding:10px 15px;
                   background-color:#007bff;color:#ffffff;
                   text-decoration:none;border-radius:4px;">
          Restablecer contraseña
      </a></p>
      <p>Si no fuiste tú, ignora este mensaje.</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔐 Recuperación de contraseña"
    msg["From"]    = "Centro de Recursos <noreply@autoanalyzerpro.com>"
    msg["To"]      = mail_destino
    msg.attach(MIMEText(texto_plano, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        st.success("✅ Enlace de recuperación enviado correctamente.")
    except Exception as e:
        st.error(f"❌ Error al enviar correo: {e}")


# Funciones Azure Blob
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

# Funciones auxiliares
def generar_id_archivo(nombre_archivo):
    base = Path(nombre_archivo).stem
    base = base.lower().replace(" ", "_")
    base = re.sub(r'\W+', '', base)
    return f"id_{base}"

def icono_archivo(nombre_archivo):
    ext = Path(nombre_archivo).suffix.lower()
    if ext == ".pdf":
        return "📄"
    elif ext in [".doc", ".docx"]:
        return "📝"
    elif ext in [".ppt", ".pptx"]:
        return "📊"
    elif ext in [".xlsx", ".xls", ".csv"]:
        return "📈"
    elif ext in [".mp4", ".mov"]:
        return "🎥"
    elif ext in [".jpg", ".jpeg", ".png", ".gif"]:
        return "🖼️"
    else:
        return "📁"

# Procesar token desde URL
params      = st.query_params
token_param = params.get("token")

if token_param:

    try:
        email = serializer.loads(token_param, salt=SALT, max_age=1800)

    except SignatureExpired:
        st.error("❌ Este enlace ha caducado. Solicita uno nuevo.")
    except BadSignature as e:
        st.error("❌ Enlace inválido. Asegúrate de copiarlo completo desde tu correo.")
        st.error(f"Detalles del error de firma: {e}")
        st.stop()

    # Mostrar formulario de nueva contraseña
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.markdown("""<div style='padding: 2rem; background-color: #fafafa;
                        border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.1);'>""",
                    unsafe_allow_html=True)

        st.subheader("🔑 Restablecer contraseña")
        nueva = st.text_input("Nueva contraseña", type="password", key="new_pass")
        confirmar = st.text_input("Confirmar contraseña", type="password", key="confirm_pass")

        if st.button("Cambiar contraseña"):
            if nueva and nueva == confirmar:
                hashed = bcrypt.hashpw(nueva.encode(), bcrypt.gensalt()).decode()
                usuarios_df = cargar_usuarios_desde_blob()
                usuarios_df.loc[usuarios_df["mail"] == email, "contraseña"] = hashed
                guardar_usuarios_en_blob(usuarios_df)
                cargar_usuarios_desde_blob.clear() 
                st.success("🔄 Contraseña actualizada. Por favor vuelve a iniciar sesión.")
            else:
                st.error("❌ Las contraseñas no coinciden.")

        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()


# --- LOGIN ---
usuarios_df = cargar_usuarios_desde_blob()

# Inicializar cookies con clave secreta desde st.secrets
cookies = EncryptedCookieManager(
    prefix="app_",
    password=st.secrets["SECRET_KEY"]
)
if not cookies.ready():
    st.stop()
 
 # Si se acaba de cerrar sesión, no hacemos nada en esta recarga para dar tiempo a que las cookies se borren
if not st.session_state.get("logout_flag"):
    # Si no hay usuario en sesión pero sí en cookies, restaurar
    if "usuario" not in st.session_state and cookies.get("usuario"):
        st.session_state.usuario = cookies.get("usuario")
        st.session_state.area = cookies.get("area")
        st.session_state.permisos = cookies.get("permisos").split(",")
        st.session_state.rol = cookies.get("rol")
# Limpiamos la bandera para la siguiente interacción
if "logout_flag" in st.session_state:
    del st.session_state.logout_flag


# --- LOGO Y TÍTULO --
if "usuario" not in st.session_state and not cookies.get("usuario"):
    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        try:
            logo_base64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
            st.markdown(
                f"""
                <div style='text-align: center; margin-top: -2rem; margin-bottom: 1rem;'>
                    <img src='data:image/png;base64,{logo_base64}' style='height: 100px;' />
                    <h1 style='font-size: 1.8rem; margin-top: 0.5rem;'>Centro de Recursos Colaborativo</h1>
                </div>
                """,
                unsafe_allow_html=True
            )
        except Exception as e:
            st.warning(f"No se pudo cargar el logo: {e}")
    else:
        st.title("Centro de Recursos Colaborativo")

# ...

if "usuario" not in st.session_state:
    # Oculta el sidebar en la pantalla de acceso
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {
            display: none;
        }
        [data-testid="collapsedControl"] {
            display: none;
        }
        </style>
        """, unsafe_allow_html=True)

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

                # Guardar también en cookies
                cookies["usuario"] = st.session_state.usuario
                cookies["area"] = st.session_state.area
                cookies["permisos"] = ",".join(st.session_state.permisos)
                cookies["rol"] = st.session_state.rol
                cookies.save()

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
            else:
                st.error("Correo no registrado.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.stop()

# Botón de logout (borrar cookies + sesión)
if "usuario" in st.session_state:
    if st.sidebar.button("Cerrar sesión"):
        del cookies["usuario"]
        del cookies["area"]
        del cookies["permisos"]
        del cookies["rol"]
        cookies.save()
        st.session_state.clear()
        st.session_state.logout_flag = True
        st.rerun()

# --- VARIABLES DE SESIÓN ---
usuario_actual = st.session_state.usuario
area_original = st.session_state.area
permisos = st.session_state.permisos
rol = st.session_state.rol

# --- MAPA DE ÁREAS DISPONIBLES ---
area_map = {
    "Dirección Deportiva": "direccion_deportiva",
    "Cuerpo Técnico": "cuerpo_tecnico",
    "Servicios Médicos": "servicios_medicos"
}

# Sidebar con logo y temporada
if "usuario" in st.session_state:
    st.sidebar.markdown("&nbsp;") 

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

# --- MENSAJE DE SESIÓN ---
st.sidebar.markdown("### 🧑‍💼 Sesión iniciada")
st.sidebar.success(f"{usuario_actual} ({rol})")

# --- SELECCIÓN DE ÁREA (si tiene acceso total) ---
if area_original == "todas":
    st.sidebar.markdown("---")
    area_opciones = list(area_map.keys())
    area = st.sidebar.selectbox("Selecciona área", area_opciones)
else:
    area = area_original

# --- DEFINICIÓN DE PREFIJO PARA BLOB STORAGE ---
azure_prefix = area_map[area] + "/" 

# Llamamos a las funciones cacheadas UNA SOLA VEZ aquí.
enlaces_lista = get_enlaces(azure_prefix)
archivos_sidebar = get_archivos_area(azure_prefix) 

# Ordenar por fecha de modificación
archivos_sidebar.sort(key=lambda x: x["last_modified"], reverse=True)

# --- LISTADO DE ARCHIVOS EN SIDEBAR ---
with st.sidebar.expander(f"📂 Archivos disponibles: {len(archivos_sidebar)}"):
    for archivo_info in archivos_sidebar:
        # La nueva estructura de datos es un diccionario
        visible_name = archivo_info["meta"].get("nombre_original", Path(archivo_info["blob_name"]).name)
        ancla = generar_id_archivo(visible_name)
        icono = icono_archivo(visible_name)
        st.markdown(f"- {icono} [{visible_name}](#{ancla})")

# --- ENLACES EN SIDEBAR (usando la variable ya cargada) ---
with st.sidebar.expander(f"🔗 Enlaces compartidos: {len(enlaces_lista)}"):
    for nombre, enlace in enlaces_lista:
        st.markdown(f"- [{nombre}]({enlace})")


# --- INTERFAZ PRINCIPAL ---
st.markdown(f"## {area}")
st.markdown("### 🔎 Buscar archivos")
search_query = st.text_input("Buscar por nombre o descripción").lower()


#--- SUBIDA DE ARCHIVOS ---

def find_existing_blob_by_original_name(original_name_to_find, prefix):
    """
    Busca en Azure Blob Storage si ya existe un blob con el mismo nombre original.
    Devuelve el nombre del blob si lo encuentra, de lo contrario None.
    """
    for blob in container_client.list_blobs(name_starts_with=prefix):
        # Nos interesan los archivos de metadatos para leer el nombre original
        if blob.name.endswith(".meta.json"):
            try:
                meta_bytes = container_client.get_blob_client(blob.name).download_blob().readall()
                meta = json.loads(meta_bytes)
                # Si el nombre original coincide, hemos encontrado el archivo
                if meta.get("nombre_original") == original_name_to_find:
                    # Devolvemos el nombre del blob de datos (sin .meta.json)
                    return blob.name.replace(".meta.json", "")
            except Exception:
                # Si hay un error al leer un meta, lo ignoramos y continuamos
                continue
    return None

def fecha_actual_madrid():
    return datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")

if "subir" in permisos:
    st.markdown("### 📤 Subida de archivos")
    comentario_input = st.text_area("Comentario o descripción (opcional)", key="comentario_subida")
    uploaded_file = st.file_uploader(
        "Arrastra un archivo o haz clic en ‘Browse files’ para seleccionarlo desde tu dispositivo",
        type=TIPOS_ARCHIVO
    )

    if uploaded_file:
        original_name = uploaded_file.name

        # 1. VERIFICAR SI EL ARCHIVO YA EXISTE
        existing_blob_name = find_existing_blob_by_original_name(original_name, azure_prefix)

        if existing_blob_name:
            # 2. SI EXISTE, MOSTRAR OPCIONES DE SOBRESCRITURA
            st.warning(f"⚠️ Ya existe un archivo llamado **{original_name}**. ¿Qué deseas hacer?")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Sobrescribir archivo existente"):
                    # Subir el nuevo contenido sobre el blob existente
                    subir_a_blob(existing_blob_name, uploaded_file.getvalue())

                    # Actualizar los metadatos del archivo existente
                    meta_blob_name = existing_blob_name + ".meta.json"
                    try:
                        # Intentar leer metadatos antiguos para mantenerlos si es posible
                        meta_bytes = descargar_blob(meta_blob_name)
                        meta = json.loads(meta_bytes)
                    except Exception:
                        meta = {} # Si no hay meta, se crea uno nuevo

                    meta["usuario"] = st.session_state.usuario
                    meta["fecha"] = fecha_actual_madrid()
                    meta["comentario"] = comentario_input.strip()
                    meta["nombre_original"] = original_name # Asegurarse que se mantiene

                    meta_str = json.dumps(meta, ensure_ascii=False)
                    subir_a_blob(meta_blob_name, meta_str.encode("utf-8"))
                    get_archivos_area.clear()
                    st.success(f"✅ Archivo **{original_name}** sobrescrito correctamente.")
            with col2:
                if st.button("❌ Cancelar subida"):
                    st.info("Subida cancelada.")
                    # No se hace nada, el rerun limpiará el estado
        else:
            # 3. SI NO EXISTE, PROCEDER CON LA SUBIDA NORMAL
            timestamp_fn = fecha_actual_madrid()
            safe_filename = f"{timestamp_fn}_{original_name}"
            blob_name = f"{azure_prefix}{safe_filename}"

            # Subir archivo
            subir_a_blob(blob_name, uploaded_file.getvalue())

            # Crear metadatos
            meta = {
                "usuario": st.session_state.usuario,
                "fecha": fecha_actual_madrid(),
                "comentario": comentario_input.strip(),
                "nombre_original": original_name
            }
            meta_str = json.dumps(meta, ensure_ascii=False)
            subir_a_blob(f"{blob_name}.meta.json", meta_str.encode("utf-8"))
            get_archivos_area.clear()
            st.success(f"✅ Archivo **{original_name}** subido.")
            st.rerun()


# --- VISUALIZACIÓN Y GESTIÓN DE ARCHIVOS ---
st.markdown("---")
st.markdown("### 📁 Archivos disponibles")

# Controles de Vista
col1, col2 = st.columns(2)
with col1:
    orden = st.selectbox("Ordenar por", ["Más recientes", "Más antiguos", "Nombre A-Z", "Nombre Z-A"],index=0)
with col2:
    vista = st.selectbox("Vista", ["1 columna", "2 columnas", "3 columnas"],index=1)
    num_cols = int(vista.split()[0])

# Aplicar filtro
filtered_files = []
for archivo_info in archivos_sidebar:
    nombre = archivo_info["meta"].get("nombre_original", "").lower()
    comentario = archivo_info["meta"].get("comentario", "").lower()
    if search_query in nombre or search_query in comentario:
        filtered_files.append(archivo_info)

# Aplicar orden
if orden == "Más recientes":
    # Ordenamos por la fecha de modificación del blob
    filtered_files.sort(key=lambda x: x["last_modified"], reverse=True)
elif orden == "Más antiguos":
    filtered_files.sort(key=lambda x: x["last_modified"])
elif orden == "Nombre A-Z":
    # Ordenamos por el nombre original guardado en los metadatos
    filtered_files.sort(key=lambda x: x["meta"].get("nombre_original", "").lower())
elif orden == "Nombre Z-A":
    filtered_files.sort(key=lambda x: x["meta"].get("nombre_original", "").lower(), reverse=True)

# Mostrar archivos en cuadrícula
chunks = [filtered_files[i:i + num_cols] for i in range(0, len(filtered_files), num_cols)]
for chunk in chunks:
    cols = st.columns(num_cols)
    for archivo_info, col in zip(chunk, cols):
        with col:
            blob_name = archivo_info["blob_name"]
            meta = archivo_info["meta"]
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
            elif suffix in [".xlsx", ".xls", ".csv"]:
                st.download_button("📥 Descargar Excel/CSV", data=contenido, file_name=blob_path.name)
            elif suffix in [".mp4", ".mov"]:
                st.download_button("📥 Descargar Vídeo", data=contenido, file_name=blob_path.name)
                #st.video(contenido)
            elif suffix in [".jpg", ".jpeg", ".png", ".gif"]:
                st.download_button("📥 Descargar Imagen", data=contenido, file_name=blob_path.name)
                #st.image(contenido, use_container_width=True)
            else:
                st.download_button("📥 Descargar Archivo", data=contenido, file_name=blob_path.name)

            comentario = st.text_area("💬 Comentario", value=meta.get("comentario", ""), key=f"comentario_{blob_name}")
            if st.button("💾 Actualizar comentario", key=f"guardar_comentario_{blob_name}"):
                meta["comentario"] = comentario
                meta_str = json.dumps(meta, ensure_ascii=False)
                subir_a_blob(blob_name + ".meta.json", meta_str.encode("utf-8"))
                get_archivos_area.clear()
                st.success("Comentario actualizado.")

            if st.button("🗑️ Eliminar archivo", key=f"eliminar_{blob_name}"):
                eliminar_blob(blob_name)
                eliminar_blob(blob_name + ".meta.json")
                get_archivos_area.clear()
                st.warning("Archivo eliminado")
                st.rerun()

            st.markdown("---")


# --- ENLACES COMPARTIDOS ---
st.markdown("### 🔗 Enlaces compartidos")

# Formulario para añadir un nuevo enlace
if "subir" in permisos:
    nombre_url = st.text_input("Título")
    url = st.text_input("Introduce un enlace (https://...)")

    if st.button("Guardar enlace"):
        # Se comprueba que el título no esté vacío y la URL sea válida
        if url and "https://" in url and nombre_url:
            enlaces_lista.append((nombre_url, url))
            nuevo_contenido = "\n".join([f"{nombre}::{enlace}" for nombre, enlace in enlaces_lista])
            subir_a_blob(f"{azure_prefix}enlaces.txt", nuevo_contenido.encode("utf-8"))
            get_enlaces.clear()
            st.success("✅ Enlace guardado correctamente.")
            st.rerun()
        else:
            st.warning("El título y la URL (debe incluir https://) no pueden estar vacíos.")

# Visualización de los enlaces existentes
if enlaces_lista:
    st.markdown("---")

    for i, (nombre, enlace) in enumerate(enlaces_lista):
        col1, col2 = st.columns([0.5, 0.5])
        with col1:
            st.markdown(f"""
                <p style='font-size: 1.25rem; font-weight: 600; margin: 0 0 0.5rem 0;'>
                    🔗 <a href="{enlace}" target="_blank" style="text-decoration: none; color: #0066cc;">
                        {nombre}
                    </a>
                </p>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown("<div style='display: flex; justify-content: flex-start;'>", unsafe_allow_html=True)
            if "subir" in permisos and st.button("🗑️", key=f"eliminar_enlace_{i}", help="Eliminar enlace"):
                enlaces_lista.pop(i)
                nuevo_contenido = "\n".join([f"{n}::{u}" for n, u in enlaces_lista])
                subir_a_blob(f"{azure_prefix}enlaces.txt", nuevo_contenido.encode("utf-8"))
                get_enlaces.clear()
                st.success("✅ Enlace eliminado.")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("No hay enlaces compartidos en esta área.")


