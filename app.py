import streamlit as st
from pathlib import Path
import os
from datetime import datetime, timedelta
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

# --- CONSTANTES Y CONFIGURACIÓN INICIAL ---
TIPOS_ARCHIVO = [
    "pdf", "doc", "docx", "ppt", "pptx",
    "xlsx", "xls", "csv", "mp4", "mov",
    "jpg", "jpeg", "png", "gif"
]
SALT = "salt-recovery"
AREA_MAP = {
    "Dirección Deportiva": "direccion_deportiva",
    "Cuerpo Técnico": "cuerpo_tecnico",
    "Servicios Médicos": "servicios_medicos"
}

# --- FUNCIONES DE CACHÉ Y DATOS ---

@st.cache_resource
def get_container_client():
    """Crea y devuelve un cliente para el contenedor de Azure, cacheado para reutilización."""
    blob_service_client = BlobServiceClient.from_connection_string(st.secrets["AZURE_CONNECTION_STRING"])
    container_client = blob_service_client.get_container_client("archivos-app")
    return container_client

@st.cache_data
def cargar_usuarios_desde_blob():
    """Carga el dataframe de usuarios desde Azure, cacheado para rendimiento."""
    blob_client = get_container_client().get_blob_client("usuarios.xlsx")
    stream = BytesIO()
    blob_client.download_blob().readinto(stream)
    stream.seek(0)
    return pd.read_excel(stream)

@st.cache_data(ttl="5m")
def get_archivos_area(prefix):
    """Obtiene y cachea una lista de diccionarios con datos y metadatos de archivos."""
    archivos_con_meta = []
    for blob in get_container_client().list_blobs(name_starts_with=prefix):
        if not blob.name.endswith((".meta.json", "enlaces.txt")):
            meta = {}
            try:
                meta_blob_name = f"{blob.name}.meta.json"
                meta_bytes = get_container_client().get_blob_client(meta_blob_name).download_blob().readall()
                meta = json.loads(meta_bytes)
            except Exception:
                meta = {"nombre_original": Path(blob.name).name, "comentario": "", "usuario": "N/A", "fecha": "N/A"}
            archivos_con_meta.append({"blob_name": blob.name, "last_modified": blob.last_modified, "meta": meta})
    return archivos_con_meta

@st.cache_data(ttl="5m")
def get_enlaces(prefix):
    """Obtiene y cachea la lista de enlaces compartidos."""
    enlaces = []
    enlace_blob_path = f"{prefix}enlaces.txt"
    try:
        enlaces_bytes = get_container_client().get_blob_client(enlace_blob_path).download_blob().readall()
        for line in enlaces_bytes.decode("utf-8").splitlines():
            if "::" in line:
                nombre, enlace = line.strip().split("::", 1)
                enlaces.append((nombre, enlace))
    except Exception:
        pass
    return enlaces

# --- FUNCIONES AUXILIARES ---

def guardar_usuarios_en_blob(df):
    blob_client = get_container_client().get_blob_client("usuarios.xlsx")
    stream = BytesIO()
    df.to_excel(stream, index=False)
    stream.seek(0)
    blob_client.upload_blob(stream, overwrite=True)

def send_recovery_email(mail_destino: str, token: str, app_url: str):
    recover_url = f"{app_url}?token={token}"
    texto_plano = f"Hola,\n\nPara restablecer tu contraseña, haz clic en el siguiente enlace:\n\n{recover_url}\n\nSi no fuiste tú, ignora este mensaje."
    html = f"""<html><body><p>Hola,</p><p>Para restablecer tu contraseña, pulsa este botón:</p><p><a href="{recover_url}" style="display:inline-block;padding:10px 15px;background-color:#007bff;color:#ffffff;text-decoration:none;border-radius:4px;">Restablecer contraseña</a></p><p>Si no fuiste tú, ignora este mensaje.</p></body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔐 Recuperación de contraseña"
    msg["From"] = "Centro de Recursos <noreply@autoanalyzerpro.com>"
    msg["To"] = mail_destino
    msg.attach(MIMEText(texto_plano, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(st.secrets["SMTP_SERVER"], st.secrets["SMTP_PORT"]) as server:
            server.starttls()
            server.login(st.secrets["SMTP_USER"], st.secrets["SMTP_PASS"])
            server.send_message(msg)
        st.success("✅ Enlace de recuperación enviado correctamente.")
    except Exception as e:
        st.error(f"❌ Error al enviar correo: {e}")

def find_existing_blob_by_original_name(original_name_to_find, prefix):
    """
    Busca en Azure Blob Storage si ya existe un blob con el mismo nombre original.
    Devuelve el nombre del blob de datos si lo encuentra, de lo contrario None.
    """
    container_client = get_container_client()
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

def subir_a_blob(nombre_archivo, contenido_bytes):
    get_container_client().get_blob_client(nombre_archivo).upload_blob(contenido_bytes, overwrite=True)

def descargar_blob(nombre_archivo):
    return get_container_client().get_blob_client(nombre_archivo).download_blob().readall()

def eliminar_blob(nombre_archivo):
    get_container_client().get_blob_client(nombre_archivo).delete_blob()

def generar_id_archivo(nombre_archivo):
    base = Path(nombre_archivo).stem.lower().replace(" ", "_")
    return f"id_{re.sub(r'[^a-zA-Z0-9_]', '', base)}"

def icono_archivo(nombre_archivo):
    ext_map = {".pdf": "📄", ".doc": "📝", ".docx": "📝", ".ppt": "📊", ".pptx": "📊", ".xlsx": "📈", ".xls": "📈", ".csv": "📈", ".mp4": "🎥", ".mov": "🎥", ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️"}
    return ext_map.get(Path(nombre_archivo).suffix.lower(), "📁")

def fecha_actual_madrid():
    return datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")

# --- FUNCIONES DE RENDERIZADO DE PÁGINAS ---

def render_login_page(cookies):
    """Dibuja toda la interfaz de la página de login y recuperación."""
    st.markdown("""<style>[data-testid="stSidebar"], [data-testid="collapsedControl"] {display: none;}</style>""", unsafe_allow_html=True)
    
    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        logo_base64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
        st.markdown(f"<div style='text-align: center; margin-top: -2rem; margin-bottom: 1rem;'><img src='data:image/png;base64,{logo_base64}' style='height: 100px;' /><h1 style='font-size: 1.8rem; margin-top: 0.5rem;'>Centro de Recursos Colaborativo</h1></div>", unsafe_allow_html=True)
    else:
        st.title("Centro de Recursos Colaborativo")

    cols = st.columns([1, 2, 1])
    with cols[1]:
        with st.container(border=True):
            st.subheader("🔐 Iniciar sesión")
            usuario_input = st.text_input("Correo electrónico")
            contrasena_input = st.text_input("Contraseña", type="password")

            if st.button("Acceder"):
                usuarios_df = cargar_usuarios_desde_blob()
                user_row = usuarios_df[usuarios_df["mail"] == usuario_input]
                if not user_row.empty and bcrypt.checkpw(contrasena_input.encode(), user_row.iloc[0]["contraseña"].encode()):
                    # Limpiamos el '?action=logout' de la URL antes de continuar
                    if "action" in st.query_params:
                        st.query_params.clear()

                    st.session_state.usuario = user_row.iloc[0]["usuario"]
                    st.session_state.area = user_row.iloc[0]["area"]
                    st.session_state.permisos = user_row.iloc[0]["permisos"].split(",")
                    st.session_state.rol = user_row.iloc[0]["rol"]
                    
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
                usuarios_df = cargar_usuarios_desde_blob()
                if mail_recup in usuarios_df["mail"].values:
                    serializer = URLSafeTimedSerializer(st.secrets["SECRET_KEY"])
                    token = serializer.dumps(mail_recup, salt=SALT)
                    send_recovery_email(mail_recup, token, st.secrets["APP_URL"])
                else:
                    st.error("Correo no registrado.")

def render_password_reset_page(token, serializer):
    """Dibuja la página para restablecer la contraseña."""
    try:
        email = serializer.loads(token, salt=SALT, max_age=1800)
        cols = st.columns([1, 2, 1])
        with cols[1]:
            with st.container(border=True):
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
                        if st.button("Volver al inicio"):
                           st.query_params.clear()
                    else:
                        st.error("❌ Las contraseñas no coinciden.")
    except SignatureExpired:
        st.error("❌ Este enlace ha caducado. Solicita uno nuevo.")
    except BadSignature:
        st.error("❌ Enlace inválido. Asegúrate de copiarlo completo desde tu correo.")

def render_main_app(cookies):
    """Dibuja toda la interfaz de la aplicación principal una vez logueado."""
    st.sidebar.markdown("&nbsp;")
    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        logo_base64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
        st.sidebar.markdown(f"<div style='display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;'><span style='font-weight: bold; font-size: 3em;'>25/26</span><img src='data:image/png;base64,{logo_base64}' style='height: 120px;' /></div>", unsafe_allow_html=True)

    if st.sidebar.button("Cerrar sesión"):
        st.query_params["action"] = "logout"

    st.sidebar.markdown("### 🧑‍💼 Sesión iniciada")
    st.sidebar.success(f"{st.session_state.usuario} ({st.session_state.rol})")

    if st.session_state.area == "todas":
        st.sidebar.markdown("---")
        area = st.sidebar.selectbox("Selecciona área", list(AREA_MAP.keys()))
    else:
        area = st.session_state.area
    
    azure_prefix = AREA_MAP[area] + "/"
    enlaces_lista = get_enlaces(azure_prefix)
    archivos_sidebar = get_archivos_area(azure_prefix)
    
    if archivos_sidebar:
        archivos_sidebar.sort(key=lambda x: x["last_modified"], reverse=True)
    
    with st.sidebar.expander(f"📂 Archivos disponibles: {len(archivos_sidebar)}"):
        for archivo_info in archivos_sidebar:
            visible_name = archivo_info["meta"].get("nombre_original", Path(archivo_info["blob_name"]).name)
            st.markdown(f"- {icono_archivo(visible_name)} [{visible_name}](#{generar_id_archivo(visible_name)})")
    
    with st.sidebar.expander(f"🔗 Enlaces compartidos: {len(enlaces_lista)}"):
        for nombre, enlace in enlaces_lista:
            st.markdown(f"- [{nombre}]({enlace})")

    # --- INTERFAZ PRINCIPAL ---
    st.markdown(f"## {area}")
    st.markdown("### 🔎 Buscar archivos")
    search_query = st.text_input("Buscar por nombre o descripción").lower()

    if "subir" in st.session_state.permisos:
        render_upload_section(azure_prefix)

    render_file_display(archivos_sidebar, search_query, azure_prefix)
    render_links_section(enlaces_lista, azure_prefix)

def render_upload_section(azure_prefix):
    """Dibuja la sección para subir archivos."""
    st.markdown("### 📤 Subida de archivos")
    comentario_input = st.text_area("Comentario o descripción (opcional)", key="comentario_subida")
    uploaded_file = st.file_uploader(
        "Arrastra un archivo o haz clic en ‘Browse files’ para seleccionarlo desde tu dispositivo",
        type=TIPOS_ARCHIVO
    )

    if uploaded_file:
        original_name = uploaded_file.name

        # 1. VERIFICAR SI EL ARCHIVO YA EXISTE
        # Esta función busca en los metadatos si ya hay un archivo con el mismo nombre original.
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
                        meta_bytes = descargar_blob(meta_blob_name)
                        meta = json.loads(meta_bytes)
                    except Exception:
                        meta = {}

                    meta["usuario"] = st.session_state.usuario
                    meta["fecha"] = fecha_actual_madrid()
                    meta["comentario"] = comentario_input.strip()
                    meta["nombre_original"] = original_name

                    meta_str = json.dumps(meta, ensure_ascii=False)
                    subir_a_blob(meta_blob_name, meta_str.encode("utf-8"))
                    get_archivos_area.clear() # Limpiamos caché para reflejar el cambio
                    st.success(f"✅ Archivo **{original_name}** sobrescrito correctamente.")
                    st.rerun()
            with col2:
                if st.button("❌ Cancelar subida"):
                    st.info("Subida cancelada.")
                    
        else:
            # 3. SI NO EXISTE, PROCEDER CON LA SUBIDA NORMAL
            timestamp_fn = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y%m%d-%H%M%S")
            safe_filename = f"{timestamp_fn}_{original_name}"
            blob_name = f"{azure_prefix}{safe_filename}"

            subir_a_blob(blob_name, uploaded_file.getvalue())

            meta = {
                "usuario": st.session_state.usuario,
                "fecha": fecha_actual_madrid(),
                "comentario": comentario_input.strip(),
                "nombre_original": original_name
            }
            meta_str = json.dumps(meta, ensure_ascii=False)
            subir_a_blob(f"{blob_name}.meta.json", meta_str.encode("utf-8"))
            get_archivos_area.clear() # Limpiamos caché para que aparezca el nuevo archivo
            st.success(f"✅ Archivo **{original_name}** subido.")
            st.rerun()

def render_file_display(archivos, search_query, azure_prefix):
    """Dibuja la cuadrícula de archivos filtrados y ordenados."""
    st.markdown("---")
    st.markdown("### 📁 Archivos disponibles")

    # Controles de Vista
    col1, col2 = st.columns(2)
    with col1:
        orden = st.selectbox("Ordenar por", ["Más recientes", "Más antiguos", "Nombre A-Z", "Nombre Z-A"], index=0)
    with col2:
        vista = st.selectbox("Vista", ["1 columna", "2 columnas", "3 columnas"], index=1)
        num_cols = int(vista.split()[0])

    # Aplicar filtro de búsqueda (opera sobre la lista cacheada, es muy rápido)
    filtered_files = []
    if search_query:
        for archivo_info in archivos:
            nombre = archivo_info["meta"].get("nombre_original", "").lower()
            comentario = archivo_info["meta"].get("comentario", "").lower()
            if search_query in nombre or search_query in comentario:
                filtered_files.append(archivo_info)
    else:
        filtered_files = archivos

    # Aplicar orden
    if orden == "Más recientes":
        filtered_files.sort(key=lambda x: x["last_modified"], reverse=True)
    elif orden == "Más antiguos":
        filtered_files.sort(key=lambda x: x["last_modified"])
    elif orden == "Nombre A-Z":
        filtered_files.sort(key=lambda x: x["meta"].get("nombre_original", "").lower())
    elif orden == "Nombre Z-A":
        filtered_files.sort(key=lambda x: x["meta"].get("nombre_original", "").lower(), reverse=True)

    # Mostrar archivos en cuadrícula
    if not filtered_files:
        st.info("No se encontraron archivos que coincidan con la búsqueda.")
        return

    chunks = [filtered_files[i:i + num_cols] for i in range(0, len(filtered_files), num_cols)]
    for chunk in chunks:
        cols = st.columns(num_cols)
        for archivo_info, col in zip(chunk, cols):
            with col:
                blob_name = archivo_info["blob_name"]
                meta = archivo_info["meta"]
                original = meta.get("nombre_original", Path(blob_name).name)
                ancla = generar_id_archivo(original)

                st.markdown(f"<div id='{ancla}'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {icono_archivo(original)} {original}")
                
                usuario = meta.get("usuario", "desconocido")
                fecha = meta.get("fecha", "")
                st.markdown(f"*Subido por {usuario} el {fecha}*")
                
                # Para la descarga, SÍ necesitamos el contenido
                with st.spinner("Preparando descarga..."):
                    contenido = descargar_blob(blob_name)
                st.download_button("📥 Descargar", data=contenido, file_name=original, key=f"descarga_{blob_name}")

                comentario = st.text_area("💬 Comentario", value=meta.get("comentario", ""), key=f"comentario_{blob_name}", height=120)
                if st.button("💾 Actualizar", key=f"guardar_comentario_{blob_name}"):
                    meta["comentario"] = comentario
                    meta_str = json.dumps(meta, ensure_ascii=False)
                    subir_a_blob(blob_name + ".meta.json", meta_str.encode("utf-8"))
                    get_archivos_area.clear()
                    st.success("Comentario actualizado.")
                    st.rerun()

                if "borrar" in st.session_state.permisos:
                    if st.button("🗑️ Eliminar", key=f"eliminar_{blob_name}", type="primary"):
                        eliminar_blob(blob_name)
                        eliminar_blob(blob_name + ".meta.json")
                        get_archivos_area.clear()
                        st.warning(f"Archivo '{original}' eliminado.")
                        st.rerun()
                st.markdown("---")

def render_links_section(enlaces, azure_prefix):
    """Dibuja la sección de enlaces compartidos."""
    st.markdown("### 🔗 Enlaces compartidos")

    # Formulario para añadir un nuevo enlace
    if "subir" in st.session_state.permisos:
        nombre_url = st.text_input("Título del enlace", key="link_title")
        url = st.text_input("Introduce un enlace (https://...)", key="link_url")

        if st.button("Guardar enlace"):
            if url and "https://" in url and nombre_url:
                enlaces.append((nombre_url, url))
                nuevo_contenido = "\n".join([f"{nombre}::{enlace}" for nombre, enlace in enlaces])
                subir_a_blob(f"{azure_prefix}enlaces.txt", nuevo_contenido.encode("utf-8"))
                get_enlaces.clear()
                st.success("✅ Enlace guardado correctamente.")
                st.rerun()
            else:
                st.warning("El título y la URL (debe incluir https://) no pueden estar vacíos.")

    # Visualización de los enlaces existentes
    if enlaces:
        st.markdown("---")
        for i, (nombre, enlace) in enumerate(enlaces):
            col1, col2 = st.columns([0.9, 0.1])
            with col1:
                st.markdown(f"""
                    <p style='font-size: 1.25rem; font-weight: 600; margin: 0;'>
                        🔗 <a href="{enlace}" target="_blank" style="text-decoration: none; color: #0066cc;">
                            {nombre}
                        </a>
                    </p>
                """, unsafe_allow_html=True)
            with col2:
                if "borrar" in st.session_state.permisos:
                    st.markdown("<div style='display: flex; justify-content: flex-start; padding-top: 4px;'>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"eliminar_enlace_{i}", help="Eliminar enlace"):
                        enlaces.pop(i)
                        nuevo_contenido = "\n".join([f"{n}::{u}" for n, u in enlaces])
                        subir_a_blob(f"{azure_prefix}enlaces.txt", nuevo_contenido.encode("utf-8"))
                        get_enlaces.clear()
                        st.success("✅ Enlace eliminado.")
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No hay enlaces compartidos en esta área.")


# --- BLOQUE DE CONTROL PRINCIPAL (VERSIÓN FINAL INTEGRADA) ---

st.set_page_config(page_title="Centro de Recursos Colaborativo", layout="wide", initial_sidebar_state="expanded")

cookies = EncryptedCookieManager(password=st.secrets["SECRET_KEY"], prefix="app_")
if not cookies.ready():
    st.stop()

params = st.query_params
token = params.get("token")
action = params.get("action")

# --- Lógica de Enrutamiento Central ---

# 1. PRIORIDAD MÁXIMA: El usuario acaba de pedir cerrar sesión
if action == "logout":
    st.session_state.clear()
    render_login_page(cookies) # Mostramos el login
    st.stop() # Detenemos el script aquí para no mostrar nada más

# 2. SEGUNDA PRIORIDAD: El usuario viene de un enlace de reseteo
elif token:
    serializer = URLSafeTimedSerializer(st.secrets["SECRET_KEY"])
    render_password_reset_page(token, serializer)

# 3. LÓGICA NORMAL
else:
    # Intentar restaurar sesión desde la cookie "zombi" si es necesario
    if "usuario" not in st.session_state and cookies.get("usuario"):
        st.session_state.usuario = cookies.get("usuario")
        st.session_state.area = cookies.get("area")
        permisos_cookie = cookies.get("permisos")
        st.session_state.permisos = permisos_cookie.split(",") if permisos_cookie else []
        st.session_state.rol = cookies.get("rol")
    
    # Decisión final: Mostrar app o login
    if "usuario" in st.session_state:
        render_main_app(cookies)
    else:
        render_login_page(cookies)