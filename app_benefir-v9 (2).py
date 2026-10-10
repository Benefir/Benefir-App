import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import json
import datetime
from datetime import date, timedelta
import os
import hashlib
import random
import base64

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y BASE DE DATOS
# ==========================================
st.set_page_config(
    page_title="BENEFIR - Sistema de Gestión Comercial",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# CONECTOR DE BASE DE DATOS DUAL (SUPABASE POSTGRESQL + SQLITE LOCAL)
# ==========================================
import os
import sqlite3
import re

try:
    import psycopg2
    from psycopg2.extras import DictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

class PGRowWrapper:
    def __init__(self, row_dict_or_tuple, cursor_description=None):
        if isinstance(row_dict_or_tuple, dict):
            self._dict = row_dict_or_tuple
            self._tuple = tuple(row_dict_or_tuple.values())
        elif hasattr(row_dict_or_tuple, 'keys'):
            self._dict = dict(row_dict_or_tuple)
            self._tuple = tuple(row_dict_or_tuple.values())
        else:
            self._tuple = row_dict_or_tuple
            colnames = [desc[0] for desc in cursor_description] if cursor_description else []
            self._dict = {col: val for col, val in zip(colnames, row_dict_or_tuple)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._tuple[key]
        return self._dict.get(key)

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

class PGCursorWrapper:
    def __init__(self, pg_cursor):
        self.cursor = pg_cursor
        self.lastrowid = None
        self.description = None

    def execute(self, sql, params=None):
        adapted_sql = self._adapt_sql(sql)
        params = params or ()
        
        is_insert = adapted_sql.strip().upper().startswith('INSERT')
        if is_insert and 'RETURNING' not in adapted_sql.upper():
            adapted_sql_returning = adapted_sql.rstrip('; ') + ' RETURNING id;'
            try:
                self.cursor.execute(adapted_sql_returning, params)
                self.description = self.cursor.description
                row = self.cursor.fetchone()
                if row:
                    self.lastrowid = row[0]
                return self
            except Exception:
                pass

        self.cursor.execute(adapted_sql, params)
        self.description = self.cursor.description
        return self

    def _adapt_sql(self, sql):
        # Convert PRAGMA table_info(tbl)
        m = re.search(r'PRAGMA\s+table_info\((.*?)\)', sql, re.IGNORECASE)
        if m:
            tbl = m.group(1).strip("'\"")
            return f"SELECT 0 AS cid, column_name AS name FROM information_schema.columns WHERE table_name = '{tbl}'"

        # Convert AUTOINCREMENT -> SERIAL
        sql = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', sql, flags=re.IGNORECASE)

        # Convert INSERT OR IGNORE INTO -> INSERT INTO ... ON CONFLICT DO NOTHING
        sql = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)', 
                     r'INSERT INTO  () VALUES () ON CONFLICT DO NOTHING', sql, flags=re.IGNORECASE)

        # Convert ? placeholders to %s
        sql = sql.replace('?', '%s')
        return sql

    def fetchone(self):
        res = self.cursor.fetchone()
        if res is None:
            return None
        return PGRowWrapper(res, self.cursor.description)

    def fetchall(self):
        res = self.cursor.fetchall()
        if not res:
            return []
        return [PGRowWrapper(row, self.cursor.description) for row in res]

    def fetchmany(self, size=None):
        res = self.cursor.fetchmany(size) if size else self.cursor.fetchmany()
        if not res:
            return []
        return [PGRowWrapper(row, self.cursor.description) for row in res]

    def close(self):
        try:
            self.cursor.close()
        except Exception:
            pass

class PGConnectionWrapper:
    def __init__(self, pg_conn):
        self.conn = pg_conn

    def cursor(self):
        return PGCursorWrapper(self.conn.cursor())

    def commit(self):
        try:
            self.conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

def get_db_connection():
    db_url = None
    try:
        if "DATABASE_URL" in st.secrets:
            db_url = st.secrets["DATABASE_URL"]
    except Exception:
        pass

    if not db_url:
        db_url = os.environ.get("DATABASE_URL")

    if db_url and HAS_PSYCOPG2:
        try:
            pg_conn = psycopg2.connect(db_url)
            pg_conn.autocommit = True
            return PGConnectionWrapper(pg_conn)
        except Exception as e:
            st.warning(f"⚠️ Conectando a respaldo local: {e}")

    conn = sqlite3.connect("benefir.db")
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Configuración Modo Admin
    c.execute("""CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)""")
    
    # 2. Usuarios y Permisos
    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        usuario TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        rol TEXT DEFAULT 'Empleado',
        permisos TEXT DEFAULT 'ALL',
        fecha_creacion DATETIME
    )""")
    
    c.execute("PRAGMA table_info(usuarios)")
    cols_usr = [row[1] for row in c.fetchall()]
    if 'permisos' not in cols_usr:
        try: c.execute("ALTER TABLE usuarios ADD COLUMN permisos TEXT DEFAULT 'ALL'")
        except: pass

    # 3. Productos / Inventario
    c.execute("""CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT,
        precio_venta REAL NOT NULL,
        costo_compra REAL NOT NULL,
        stock INTEGER NOT NULL,
        stock_minimo INTEGER DEFAULT 5,
        codigo_barras TEXT
    )""")
    
    # 4. Clientes
    c.execute("""CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        telefono TEXT,
        direccion TEXT,
        email TEXT,
        saldo_pendiente REAL DEFAULT 0.0
    )""")
    
    c.execute("PRAGMA table_info(clientes)")
    cols_cli = [row[1] for row in c.fetchall()]
    if 'direccion' not in cols_cli:
        try: c.execute("ALTER TABLE clientes ADD COLUMN direccion TEXT")
        except: pass

    # 5. Proveedores
    c.execute("""CREATE TABLE IF NOT EXISTS proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        telefono TEXT,
        nit_cc TEXT,
        email TEXT,
        direccion TEXT,
        dia_visita TEXT,
        nota TEXT
    )""")

    # 6. Cotizaciones
    c.execute("""CREATE TABLE IF NOT EXISTS cotizaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_nombre TEXT NOT NULL,
        direccion TEXT,
        pedido TEXT NOT NULL,
        precio_pedido REAL NOT NULL,
        precio_domicilio REAL DEFAULT 0.0,
        total REAL NOT NULL,
        fecha_entrega TEXT,
        fecha_creacion DATETIME NOT NULL,
        estado TEXT DEFAULT 'Pendiente',
        mensaje_generado TEXT
    )""")

    # 7. Gastos
    c.execute("""CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATE NOT NULL,
        tipo_gasto TEXT NOT NULL,
        categoria TEXT NOT NULL,
        descripcion TEXT,
        monto REAL NOT NULL,
        metodo_pago TEXT DEFAULT 'Efectivo'
    )""")

    # 8. Compras
    c.execute("""CREATE TABLE IF NOT EXISTS compras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATE NOT NULL,
        tipo_compra TEXT NOT NULL,
        proveedor TEXT NOT NULL,
        descripcion TEXT,
        monto REAL NOT NULL,
        metodo_pago TEXT DEFAULT 'Efectivo'
    )""")

    # 9. Costos y Presupuesto
    c.execute("""CREATE TABLE IF NOT EXISTS costos_presupuesto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        concepto TEXT NOT NULL,
        categoria TEXT NOT NULL,
        cantidad REAL DEFAULT 1.0,
        costo_unitario REAL NOT NULL,
        costo_total REAL NOT NULL,
        presupuesto_asignado REAL DEFAULT 0.0,
        notas TEXT,
        fecha DATE NOT NULL
    )""")

    # 10. Cuentas por Cobrar
    c.execute("""CREATE TABLE IF NOT EXISTS cuentas_por_cobrar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        cliente_nombre TEXT NOT NULL,
        concepto TEXT NOT NULL,
        monto_total REAL NOT NULL,
        monto_pagado REAL DEFAULT 0.0,
        saldo REAL NOT NULL,
        fecha_emision DATE NOT NULL,
        fecha_vencimiento DATE,
        estado TEXT DEFAULT 'Pendiente'
    )""")

    # 11. Cuentas por Pagar (Proveedores)
    c.execute("""CREATE TABLE IF NOT EXISTS cuentas_por_pagar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor TEXT NOT NULL,
        concepto TEXT,
        monto REAL NOT NULL,
        fecha_vencimiento DATE NOT NULL,
        estado TEXT DEFAULT 'Pendiente'
    )""")

    # 12. Caja y Banco
    c.execute("""CREATE TABLE IF NOT EXISTS caja_banco (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATETIME NOT NULL,
        tipo_cuenta TEXT NOT NULL,
        tipo_movimiento TEXT NOT NULL,
        monto REAL NOT NULL,
        concepto TEXT NOT NULL,
        cuenta_destino TEXT
    )""")

    # 13. Ventas Directas
    c.execute("""CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATETIME NOT NULL,
        cliente_id INTEGER,
        cliente_nombre TEXT,
        metodo_pago TEXT NOT NULL,
        subtotal REAL NOT NULL,
        descuento REAL DEFAULT 0.0,
        impuesto REAL NOT NULL,
        total REAL NOT NULL,
        ganancia_neta REAL NOT NULL,
        comentario TEXT,
        usuario TEXT
    )""")

    c.execute("PRAGMA table_info(ventas)")
    cols_vta = [row[1] for row in c.fetchall()]
    if 'cliente_nombre' not in cols_vta:
        try: c.execute("ALTER TABLE ventas ADD COLUMN cliente_nombre TEXT")
        except: pass
    if 'descuento' not in cols_vta:
        try: c.execute("ALTER TABLE ventas ADD COLUMN descuento REAL DEFAULT 0.0")
        except: pass
    if 'comentario' not in cols_vta:
        try: c.execute("ALTER TABLE ventas ADD COLUMN comentario TEXT")
        except: pass

    # 14. Detalle de Ventas
    c.execute("""CREATE TABLE IF NOT EXISTS detalle_ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id INTEGER NOT NULL,
        producto_id INTEGER NOT NULL,
        producto_nombre TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        precio_unitario REAL NOT NULL,
        costo_unitario REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (venta_id) REFERENCES ventas (id)
    )""")

    # 15. Módulos Personalizados
    c.execute("""CREATE TABLE IF NOT EXISTS modulos_personalizados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clave TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        icono TEXT NOT NULL,
        descripcion TEXT,
        campos_json TEXT NOT NULL,
        activo INTEGER DEFAULT 1
    )""")

    # 16. Registros de Módulos Personalizados
    c.execute("""CREATE TABLE IF NOT EXISTS registros_modulo_pers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modulo_clave TEXT NOT NULL,
        datos_json TEXT NOT NULL,
        fecha_creacion DATETIME NOT NULL,
        usuario TEXT
    )""")

    # Valores por defecto en la configuración
    default_modules = ["pos", "ventas", "inventario", "clientes", "proveedores", "cotizaciones", "gastos", "compras", "costos", "cxc", "cxp", "tesoreria", "rendimiento"]
    defaults = {
        "app_nombre": "BENEFIR",
        "app_eslogan": "Plataforma de Gestión Comercial e Inteligencia de Negocios",
        "app_icono": "💼",
        "color_primario": "#2563EB",
        "color_secundario": "#1D4ED8",
        "color_fondo": "#F8FAFC",
        "color_tarjetas": "#FFFFFF",
        "color_texto": "#0F172A",
        "fuente": "Poppins",
        "bg_image_url": "",
        "logo_data": "",
        "moneda": "$",
        "impuesto_pct": "0.0",
        "saldo_inicial_efectivo": "0.0",
        "saldo_inicial_banco": "0.0",
        "modulos_activos": json.dumps(default_modules)
    }
    
    for key, val in defaults.items():
        c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, val))
        
    # Usuario Admin maestro si no existen usuarios
    c.execute("SELECT COUNT(*) FROM usuarios")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO usuarios (nombre, usuario, password, rol, permisos, fecha_creacion)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  ("Administrador Maestro", "admin", hash_password("admin123"), "Admin", "ALL", datetime.datetime.now()))
        
    conn.commit()
    conn.close()

init_db()

# Cargar configuración activa
def load_config():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM config")
    rows = c.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

cfg = load_config()

# Lista de fuentes Google Fonts para la interfaz
LISTA_FUENTES_GOOGLE = [
    "Poppins", "Inter", "Montserrat", "Roboto", "Open Sans", "Lato", "Oswald", "Raleway", 
    "Nunito", "Ubuntu", "Playfair Display", "Merriweather", "Rubik", "Work Sans", "Fira Sans", 
    "Quicksand", "Plus Jakarta Sans", "Outfit", "Space Grotesk", "Syne", "Cabinet Grotesk", 
    "Urbanist", "Sora", "DM Sans", "Manrope", "Lexend", "Bebas Neue", "Barlow", "Josefin Sans", 
    "Epilogue", "Space Mono", "Public Sans", "Overpass", "Albert Sans", "Chivo", "Kanit", 
    "Archivo", "Cinzel", "Cormorant Garamond", "Fraunces", "Red Hat Display", 
    "Figtree", "Bricolage Grotesque", "Instrument Sans", "Schibsted Grotesk", "Spline Sans",
    "Noto Sans", "PT Sans", "Source Sans 3", "Cabin", "Titillium Web", "Bitter", "Arvo", 
    "Varela Round", "Assistant", "Questrial", "Comfortaa", "Teko", "Abel", "Righteous", 
    "Exo 2", "Mulish", "Catamaran", "Hind", "Dosis", "Antic Didot", "Bodoni Moda", "Bungee",
    "Golos Text", "Geist", "Hanken Grotesk", "Onest", "Rethink Sans", "WIX Madefor Text"
]

# ==========================================
# 2. INYECCIÓN DE CSS Y DISEÑO ESTÉTICO DE ALTO NIVEL
# ==========================================
def apply_custom_styles():
    primary_color = cfg.get("color_primario", "#2563EB")
    sec_color = cfg.get("color_secundario", "#1D4ED8")
    card_bg = cfg.get("color_tarjetas", "#FFFFFF")
    bg_color = cfg.get("color_fondo", "#F8FAFC")
    text_color = cfg.get("color_texto", "#0F172A")
    font_family = cfg.get("fuente", "Poppins")
    bg_img = cfg.get("bg_image_url", "")

    bg_style = f"background-color: {bg_color};"
    if bg_img:
        bg_style = f"background-image: url('{bg_img}'); background-size: cover; background-attachment: fixed;"

    # Note: 0 leading whitespace in style block to prevent Streamlit code block rendering
    css_content = f"""<style>
@import url('https://fonts.googleapis.com/css2?family={font_family.replace(" ", "+")}:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {{
    font-family: '{font_family}', sans-serif !important;
    color: {text_color};
    {bg_style}
}}

/* Ocultar elementos nativos de Streamlit */
#MainMenu {{visibility: hidden; display: none;}}
footer {{visibility: hidden; display: none;}}
header {{visibility: hidden; display: none;}}
.stDeployButton {{display:none;}}

/* Tarjetas Principales y Elevadas */
.benefir-card {{
    background: {card_bg};
    border-radius: 18px;
    padding: 24px;
    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
    border: 1px solid rgba(226, 232, 240, 0.9);
    margin-bottom: 22px;
    transition: all 0.3s ease;
}}

/* Tarjetas del Mosaico de Módulos (Diseño Arte v9) */
.module-card {{
    background: {card_bg};
    border-radius: 20px;
    padding: 24px 20px;
    text-align: center;
    border: 1.5px solid #E2E8F0;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.03);
    margin-bottom: 16px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}}
.module-card:hover {{
    border-color: {primary_color};
    transform: translateY(-5px);
    box-shadow: 0 16px 32px -8px rgba(37, 99, 235, 0.18);
}}

/* Banner Principal de Encabezado */
.app-header {{
    background: linear-gradient(135deg, {primary_color} 0%, {sec_color} 100%);
    color: white;
    padding: 30px 32px;
    border-radius: 24px;
    margin-bottom: 28px;
    box-shadow: 0 14px 32px -6px rgba(37, 99, 235, 0.32);
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.app-header h1 {{
    color: white !important;
    margin: 0;
    font-weight: 800;
    font-size: 2.2rem;
    letter-spacing: -0.5px;
}}
.app-header p {{
    color: rgba(255, 255, 255, 0.92) !important;
    margin: 6px 0 0 0;
    font-size: 1.05rem;
}}

/* Métricas KPIs Resaltadas */
[data-testid="stMetricValue"] {{
    font-weight: 800 !important;
    color: {primary_color} !important;
    font-size: 1.8rem !important;
}}

/* Botones de Estilo Premium */
.stButton>button {{
    border-radius: 12px !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.3rem !important;
    transition: all 0.25s ease !important;
}}
.stButton>button[kind="primary"] {{
    background: linear-gradient(135deg, {primary_color} 0%, {sec_color} 100%) !important;
    border: none !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.28) !important;
}}
.stButton>button[kind="primary"]:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 18px rgba(37, 99, 235, 0.38) !important;
}}

/* Pestañas (Tabs) Estilizadas */
.stTabs [data-baseweb="tab-list"] {{
    gap: 8px;
    background-color: #F1F5F9;
    padding: 6px;
    border-radius: 14px;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 10px;
    padding: 8px 18px;
    font-weight: 600;
    color: #475569;
}}
.stTabs [aria-selected="true"] {{
    background-color: #FFFFFF !important;
    color: {primary_color} !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

/* Badges de Estado */
.badge-success {{ background-color: #DCFCE7; color: #15803D; padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.82rem; }}
.badge-warning {{ background-color: #FEF9C3; color: #A16207; padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.82rem; }}
.badge-danger {{ background-color: #FEE2E2; color: #B91C1C; padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.82rem; }}
</style>"""
    st.markdown(css_content, unsafe_allow_html=True)

apply_custom_styles()

# ==========================================
# 3. CONTROL DE SESIÓN Y AUTENTICACIÓN
# ==========================================
if "user_authenticated" not in st.session_state:
    st.session_state.user_authenticated = False
if "user_name" not in st.session_state:
    st.session_state.user_name = ""
if "user_role" not in st.session_state:
    st.session_state.user_role = ""
if "user_permissions" not in st.session_state:
    st.session_state.user_permissions = "ALL"
if "current_module" not in st.session_state:
    st.session_state.current_module = "inicio"

def login_register_page():
    st.markdown(f"""<div style="text-align: center; padding: 20px 0 10px 0;">
        <h1 style="color: {cfg.get('color_primario', '#2563EB')}; font-weight: 800; font-size: 2.8rem; margin:0;">
            {cfg.get('app_icono', '💼')} {cfg.get('app_nombre', 'BENEFIR')}
        </h1>
        <p style="color: #64748B; font-size: 1.1rem;">{cfg.get('app_eslogan', 'Plataforma Comercial e Inteligencia de Negocios')}</p>
    </div>""", unsafe_allow_html=True)

    col_box1, col_box2, col_box3 = st.columns([1, 2, 1])
    with col_box2:
        tab_login, tab_register = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

        with tab_login:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("form_login_main"):
                u_input = st.text_input("Nombre de Usuario", placeholder="Ej: admin")
                p_input = st.text_input("Contraseña", type="password")
                btn_login = st.form_submit_button("Ingresar al Sistema", type="primary", use_container_width=True)

                if btn_login:
                    if u_input and p_input:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT * FROM usuarios WHERE usuario = ? AND password = ?",
                                  (u_input.strip(), hash_password(p_input.strip())))
                        user_row = c.fetchone()
                        conn.close()

                        if user_row:
                            st.session_state.user_authenticated = True
                            st.session_state.user_name = user_row["nombre"]
                            st.session_state.user_role = user_row["rol"]
                            st.session_state.user_permissions = user_row["permisos"] if "permisos" in user_row.keys() else "ALL"
                            st.session_state.current_module = "inicio"
                            st.success(f"¡Bienvenido de nuevo, {user_row['nombre']}!")
                            st.rerun()
                        else:
                            st.error("Usuario o contraseña incorrectos.")
                    else:
                        st.warning("Por favor completa todos los campos.")

        with tab_register:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("form_register_main"):
                reg_nom = st.text_input("Nombre Completo")
                reg_usr = st.text_input("Nombre de Usuario")
                reg_pwd = st.text_input("Contraseña", type="password")
                reg_rol = st.selectbox("Rol de Acceso", ["Empleado", "Admin"])
                btn_reg = st.form_submit_button("Crear Cuenta", use_container_width=True)

                if btn_reg:
                    if reg_nom and reg_usr and reg_pwd:
                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            c.execute("""INSERT INTO usuarios (nombre, usuario, password, rol, permisos, fecha_creacion)
                                         VALUES (?, ?, ?, ?, ?, ?)""",
                                      (reg_nom.strip(), reg_usr.strip(), hash_password(reg_pwd.strip()), reg_rol, "ALL", datetime.datetime.now()))
                            conn.commit()
                            st.success("¡Cuenta creada con éxito! Ya puedes iniciar sesión.")
                        except sqlite3.IntegrityError:
                            st.error("El nombre de usuario ya está registrado.")
                        conn.close()
                    else:
                        st.warning("Completa todos los datos requeridos.")

if not st.session_state.user_authenticated:
    login_register_page()
    st.stop()

# ==========================================
# 4. BARRA LATERAL (VERSIÓN 7 - 100% LIMPIA)
# ==========================================
with st.sidebar:
    logo_data = cfg.get("logo_data", "")
    logo_url = cfg.get("logo_url", "")
    
    if logo_data:
        st.markdown(f'<div style="text-align:center; padding:10px;"><img src="{logo_data}" style="max-width:140px; max-height:80px; border-radius:10px;"></div>', unsafe_allow_html=True)
    elif logo_url:
        st.markdown(f'<div style="text-align:center; padding:10px;"><img src="{logo_url}" style="max-width:140px; max-height:80px; border-radius:10px;"></div>', unsafe_allow_html=True)

    st.markdown(f"""<div style="text-align: center; padding: 10px 0;">
        <h2 style="margin:0; font-weight: 800; color:{cfg.get('color_primario', '#2563EB')};">
            {cfg.get('app_icono', '💼')} {cfg.get('app_nombre', 'BENEFIR')}
        </h2>
        <p style="font-size: 0.85rem; color: #64748B; margin-top:2px;">{cfg.get('app_eslogan', '')}</p>
    </div>
    <hr style="margin: 10px 0;">""", unsafe_allow_html=True)

    st.markdown(f"""<div style="background: #F1F5F9; border-radius: 12px; padding: 12px; margin-bottom: 20px;">
        <p style="margin:0; font-weight:700; color:#0F172A; font-size: 0.95rem;">👤 {st.session_state.user_name}</p>
        <p style="margin:0; color:#64748B; font-size: 0.8rem;">Rol: <b>{st.session_state.user_role}</b></p>
    </div>""", unsafe_allow_html=True)

    if st.button("🏠 Menú Principal / Módulos", type="primary", use_container_width=True):
        st.session_state.current_module = "inicio"
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.user_authenticated = False
        st.session_state.user_name = ""
        st.session_state.user_role = ""
        st.session_state.user_permissions = "ALL"
        st.session_state.current_module = "inicio"
        st.rerun()

# Auxiliares para encabezado y pie de página de módulos (VERSIÓN 7 - BOTÓN ARRIBA Y ABAJO)
def render_module_header(title, icon, description):
    col_t, col_b = st.columns([3, 1])
    with col_t:
        st.markdown(f"## {icon} {title}")
        st.caption(description)
    with col_b:
        if st.button("🏠 Volver al Inicio", key=f"btn_nav_top_{title}", type="secondary", use_container_width=True):
            st.session_state.current_module = "inicio"
            st.rerun()
    st.markdown("---")

def render_module_footer():
    st.markdown("<br><hr>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("🏠 Volver al Menú Principal", key=f"btn_nav_bot_{random.randint(1000,9999)}", use_container_width=True):
            st.session_state.current_module = "inicio"
            st.rerun()

# Auxiliar de permisos
def has_permission(module_key):
    if st.session_state.user_role == "Admin":
        return True
    perm = st.session_state.user_permissions
    if not perm or perm == "ALL":
        return True
    try:
        allowed = json.loads(perm)
        return module_key in allowed
    except:
        return True

# ==========================================
# 5. MENÚ PRINCIPAL (HUB DE MÓDULOS)
# ==========================================
if st.session_state.current_module == "inicio":
    logo_data = cfg.get("logo_data", "")
    logo_url = cfg.get("logo_url", "")
    logo_html = ""
    if logo_data:
        logo_html = f'<img src="{logo_data}" style="max-height:60px; margin-right:15px; border-radius:8px;">'
    elif logo_url:
        logo_html = f'<img src="{logo_url}" style="max-height:60px; margin-right:15px; border-radius:8px;">'

    st.markdown(f"""<div class="app-header">
        <div style="display:flex; align-items:center;">
            {logo_html}
            <div>
                <h1>{cfg.get('app_icono', '💼')} Panel de Control - {cfg.get('app_nombre', 'BENEFIR')}</h1>
                <p>Bienvenido, <b>{st.session_state.user_name}</b>. Selecciona un módulo para gestionar tu negocio.</p>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # Métricas Rápidas
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT SUM(total) FROM ventas WHERE date(fecha) = date('now')")
    ventas_hoy = c.fetchone()[0] or 0.0

    c.execute("SELECT SUM(monto) FROM caja_banco WHERE tipo_cuenta = 'Efectivo'")
    caja_efectivo = c.fetchone()[0] or float(cfg.get("saldo_inicial_efectivo", "0.0"))

    c.execute("SELECT SUM(monto) FROM caja_banco WHERE tipo_cuenta = 'Banco'")
    caja_banco = c.fetchone()[0] or float(cfg.get("saldo_inicial_banco", "0.0"))

    c.execute("SELECT COUNT(*) FROM productos WHERE stock <= stock_minimo")
    stock_alerta = c.fetchone()[0] or 0

    conn.close()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ventas de Hoy", f"{cfg.get('moneda', '$')}{ventas_hoy:,.2f}")
    m2.metric("Efectivo en Caja", f"{cfg.get('moneda', '$')}{caja_efectivo:,.2f}")
    m3.metric("Saldo en Banco", f"{cfg.get('moneda', '$')}{caja_banco:,.2f}")
    m4.metric("Productos Bajo Stock", f"{stock_alerta} items", delta="-Alerta" if stock_alerta > 0 else "OK")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🚀 Módulos Comerciales y Operativos")

    modulos_std_dict = {
        "pos": ("🛒 Punto de Venta (POS)", "Cobro rápido con carrito interactivo y catálogo"),
        "ventas": ("🛍️ Registro de Ventas", "Formulario directo para ventas, descuentos y clientes"),
        "inventario": ("📦 Inventario y Productos", "Gestión de catálogo, existencias y precios"),
        "clientes": ("👥 Clientes", "Directorio de clientes con teléfonos y direcciones"),
        "proveedores": ("🏭 Proveedores", "Registro de proveedores, NIT/RUT y días de visita"),
        "cotizaciones": ("📝 Cotizaciones", "Cotizaciones rápidas y mensajes amables para clientes"),
        "gastos": ("💸 Gastos", "Control de gastos simples, generales y administrativos"),
        "compras": ("🛍️ Compras", "Registro de mercancía e insumos recibidos"),
        "costos": ("💰 Costos y Presupuesto", "Cálculo de materia prima, mano de obra e insumos"),
        "cxc": ("💵 Cuentas por Cobrar", "Gestión de créditos a clientes y cobro de deudas"),
        "cxp": ("🚚 Cuentas por Pagar", "Fechas de vencimiento y pagos a proveedores"),
        "tesoreria": ("🏦 Caja y Banco", "Control de efectivo en caja física y cuentas bancarias"),
        "rendimiento": ("📈 Rendimiento & Balance", "Análisis consolidado, estado de resultados y gráficos")
    }

    try:
        modulos_activos_cfg = json.loads(cfg.get("modulos_activos", "[]"))
    except:
        modulos_activos_cfg = list(modulos_std_dict.keys())

    cols_hub = st.columns(3)
    idx_col = 0

    for m_key in modulos_activos_cfg:
        if m_key in modulos_std_dict and has_permission(m_key):
            m_title, m_desc = modulos_std_dict[m_key]
            with cols_hub[idx_col % 3]:
                st.markdown('<div class="module-card">', unsafe_allow_html=True)
                st.markdown(f"#### {m_title}")
                st.caption(m_desc)
                if st.button(f"Abrir {m_title.split()[1]}", key=f"nav_hub_{m_key}", use_container_width=True):
                    st.session_state.current_module = m_key
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            idx_col += 1

    # Cargar Módulos Personalizados
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM modulos_personalizados WHERE activo = 1")
    modulos_pers = c.fetchall()
    conn.close()

    if modulos_pers:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🧩 Módulos Personalizados del Negocio")
        for p_mod in modulos_pers:
            p_key = f"pers_{p_mod['id']}"
            if has_permission(p_key):
                with cols_hub[idx_col % 3]:
                    st.markdown('<div class="module-card" style="border-color: #3B82F6;">', unsafe_allow_html=True)
                    st.markdown(f"#### {p_mod['icono']} {p_mod['nombre']}")
                    st.caption(p_mod['descripcion'] or "Módulo personalizado")
                    if st.button(f"Abrir {p_mod['nombre']}", key=f"nav_pers_{p_mod['id']}", use_container_width=True):
                        st.session_state.current_module = p_key
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                idx_col += 1

    if st.session_state.user_role == "Admin":
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="module-card" style="border-color: #2563EB; background: #EFF6FF;">', unsafe_allow_html=True)
        st.markdown("#### ⚙️ Modo Admin Plus (Configuración Avanzada)")
        st.caption("Personaliza colores, fuentes (+100 estilos), logo, usuarios, permisos y crea nuevos módulos sin modificar el código")
        if st.button("Abrir Modo Admin Plus", key="nav_admin", type="primary", use_container_width=True):
            st.session_state.current_module = "admin"
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 6. MÓDULO: PUNTO DE VENTA (POS)
# ==========================================
elif st.session_state.current_module == "pos":
    render_module_header("Punto de Venta (POS)", "🛒", "Procesa ventas rápidamente agregando productos al carrito interactivo.")

    if "carrito" not in st.session_state:
        st.session_state.carrito = []

    conn = get_db_connection()
    df_prod = pd.read_sql_query("SELECT id, nombre, categoria, precio_venta, costo_compra, stock FROM productos", conn)
    clis = pd.read_sql_query("SELECT id, nombre FROM clientes", conn).to_dict('records')
    conn.close()

    col_cat, col_cart = st.columns([3, 2])

    with col_cat:
        st.markdown("### 📦 Catálogo de Productos")
        busqueda = st.text_input("🔍 Buscar por Nombre o Categoría")
        
        df_filtered = df_prod
        if busqueda:
            df_filtered = df_prod[df_prod['nombre'].str.contains(busqueda, case=False, na=False) | 
                                  df_filtered['categoria'].str.contains(busqueda, case=False, na=False)]

        if not df_filtered.empty:
            for idx, row in df_filtered.iterrows():
                c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                c1.write(f"**{row['nombre']}** ({row['categoria']})")
                c2.write(f"{cfg.get('moneda', '$')}{row['precio_venta']:,.2f}")
                c3.write(f"Stock: `{row['stock']}`")
                
                with c4:
                    if row['stock'] > 0:
                        if st.button(f"➕ Agregar", key=f"add_{row['id']}", use_container_width=True):
                            encontrado = False
                            for item in st.session_state.carrito:
                                if item['id'] == row['id']:
                                    if item['cantidad'] < row['stock']:
                                        item['cantidad'] += 1
                                        encontrado = True
                                    else:
                                        st.warning("No hay más stock disponible.")
                                        encontrado = True
                                    break
                            if not encontrado:
                                st.session_state.carrito.append({
                                    "id": row['id'],
                                    "nombre": row['nombre'],
                                    "precio": row['precio_venta'],
                                    "costo": row['costo_compra'],
                                    "cantidad": 1
                                })
                            st.rerun()
                    else:
                        st.error("Agotado")
                st.divider()
        else:
            st.info("No se encontraron productos.")

    with col_cart:
        st.markdown("### 🛒 Carrito de Compras")
        if st.session_state.carrito:
            total_carrito = 0
            for idx, item in enumerate(st.session_state.carrito):
                subt = item['precio'] * item['cantidad']
                total_carrito += subt
                st.markdown(f"**{item['nombre']}** - {item['cantidad']} x {cfg.get('moneda', '$')}{item['precio']:,.2f} = `{cfg.get('moneda', '$')}{subt:,.2f}`")

            st.markdown("---")
            st.markdown(f"### Total: `{cfg.get('moneda', '$')}{total_carrito:,.2f}`")

            cliente_pos = st.selectbox("Cliente", ["Cliente Ocasional"] + [c['nombre'] for c in clis])
            metodo_pos = st.selectbox("Método de Pago", ["Efectivo", "Transferencia / Nequi", "Tarjeta", "Crédito / Fiado"])

            c_cob, c_vac = st.columns(2)
            with c_cob:
                if st.button("💳 Registrar y Cobrar Venta", type="primary", use_container_width=True):
                    conn = get_db_connection()
                    c = conn.cursor()
                    
                    cli_id = None
                    if cliente_pos != "Cliente Ocasional":
                        for c_obj in clis:
                            if c_obj['nombre'] == cliente_pos:
                                cli_id = c_obj['id']
                                break

                    ganancia_total = sum((item['precio'] - item['costo']) * item['cantidad'] for item in st.session_state.carrito)
                    
                    c.execute("""INSERT INTO ventas (fecha, cliente_id, cliente_nombre, metodo_pago, subtotal, descuento, impuesto, total, ganancia_neta, usuario)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                              (datetime.datetime.now(), cli_id, cliente_pos, metodo_pos, total_carrito, 0.0, 0.0, total_carrito, ganancia_total, st.session_state.user_name))
                    venta_id = c.lastrowid

                    for item in st.session_state.carrito:
                        c.execute("""INSERT INTO detalle_ventas (venta_id, producto_id, producto_nombre, cantidad, precio_unitario, costo_unitario, subtotal)
                                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                  (venta_id, item['id'], item['nombre'], item['cantidad'], item['precio'], item['costo'], item['precio'] * item['cantidad']))
                        
                        c.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (item['cantidad'], item['id']))

                    if metodo_pos == "Crédito / Fiado":
                        c.execute("""INSERT INTO cuentas_por_cobrar (cliente_id, cliente_nombre, concepto, monto_total, monto_pagado, saldo, fecha_emision, estado)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                  (cli_id, cliente_pos, f"Venta POS #{venta_id}", total_carrito, 0.0, total_carrito, datetime.date.today(), 'Pendiente'))
                        if cli_id:
                            c.execute("UPDATE clientes SET saldo_pendiente = saldo_pendiente + ? WHERE id = ?", (total_carrito, cli_id))
                    else:
                        tipo_cta = "Efectivo" if "Efectivo" in metodo_pos else "Banco"
                        c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto)
                                     VALUES (?, ?, 'Ingreso', ?, ?)""",
                                  (datetime.datetime.now(), tipo_cta, total_carrito, f"Venta POS #{venta_id} ({cliente_pos})"))

                    conn.commit()
                    conn.close()
                    
                    st.session_state.carrito = []
                    st.success("¡Venta registrada exitosamente!")
                    st.rerun()

            with c_vac:
                if st.button("🗑️ Vaciar Carrito", use_container_width=True):
                    st.session_state.carrito = []
                    st.rerun()
        else:
            st.info("El carrito está vacío.")

    render_module_footer()

# ==========================================
# 7. MÓDULO: REGISTRO DIRECTO DE VENTAS
# ==========================================
elif st.session_state.current_module == "ventas":
    render_module_header("Registro Directo de Ventas", "🛍️", "Ingresa manualmente el detalle de tus ventas completadas.")

    conn = get_db_connection()
    clis = pd.read_sql_query("SELECT id, nombre FROM clientes", conn).to_dict('records')
    conn.close()

    with st.form("form_registro_venta_directa"):
        c1, c2, c3 = st.columns(3)
        with c1:
            f_fecha = st.date_input("Fecha de la Venta", value=datetime.date.today())
            f_cli = st.selectbox("Nombre del Cliente", ["Cliente Ocasional"] + [cli['nombre'] for cli in clis])
        with c2:
            f_metodo = st.selectbox("Método de Pago", ["Efectivo", "Transferencia / Nequi", "Tarjeta", "Crédito / Fiado"])
            f_desc = st.number_input("Descuento Aplicado ($)", min_value=0.0, value=0.0, step=1000.0)
        with c3:
            f_total = st.number_input("Total Neto ($)", min_value=0.0, value=0.0, step=5000.0)
            f_obs = st.text_input("Comentario / Observación")

        if st.form_submit_button("💾 Guardar Venta Directa", type="primary"):
            if f_total > 0:
                conn = get_db_connection()
                c = conn.cursor()
                
                cli_id = None
                if f_cli != "Cliente Ocasional":
                    for c_o in clis:
                        if c_o['nombre'] == f_cli:
                            cli_id = c_o['id']
                            break

                c.execute("""INSERT INTO ventas (fecha, cliente_id, cliente_nombre, metodo_pago, subtotal, descuento, impuesto, total, ganancia_neta, comentario, usuario)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (f_fecha, cli_id, f_cli, f_metodo, f_total + f_desc, f_desc, 0.0, f_total, f_total * 0.3, f_obs, st.session_state.user_name))
                venta_id = c.lastrowid

                if f_metodo == "Crédito / Fiado":
                    c.execute("""INSERT INTO cuentas_por_cobrar (cliente_id, cliente_nombre, concepto, monto_total, monto_pagado, saldo, fecha_emision, estado)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                              (cli_id, f_cli, f"Venta Directa #{venta_id}", f_total, 0.0, f_total, f_fecha, 'Pendiente'))
                    if cli_id:
                        c.execute("UPDATE clientes SET saldo_pendiente = saldo_pendiente + ? WHERE id = ?", (f_total, cli_id))
                else:
                    tipo_cta = "Efectivo" if "Efectivo" in f_metodo else "Banco"
                    c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto)
                                 VALUES (?, ?, 'Ingreso', ?, ?)""",
                              (f_fecha, tipo_cta, f_total, f"Venta Directa #{venta_id} ({f_cli})"))

                conn.commit()
                conn.close()
                st.success("¡Venta directa guardada correctamente!")
                st.rerun()
            else:
                st.warning("Ingresa un monto de total neto válido.")

    st.markdown("### 📋 Historial Reciente de Ventas")
    conn = get_db_connection()
    df_v = pd.read_sql_query("SELECT id, fecha, cliente_nombre, metodo_pago, total, descuento, comentario FROM ventas ORDER BY id DESC LIMIT 15", conn)
    conn.close()
    if not df_v.empty:
        st.dataframe(df_v, use_container_width=True)

    render_module_footer()

# ==========================================
# 8. MÓDULO: INVENTARIO Y PRODUCTOS
# ==========================================
elif st.session_state.current_module == "inventario":
    render_module_header("Inventario y Catálogo de Productos", "📦", "Administra tus existencias, precios de costo y precios de venta.")

    with st.expander("➕ Agregar Nuevo Producto", expanded=False):
        with st.form("form_add_prod"):
            c1, c2, c3 = st.columns(3)
            with c1:
                p_nom = st.text_input("Nombre del Producto *")
                p_cat = st.text_input("Categoría")
            with c2:
                p_pv = st.number_input("Precio de Venta ($) *", min_value=0.0, step=1000.0)
                p_pc = st.number_input("Costo de Compra ($) *", min_value=0.0, step=1000.0)
            with c3:
                p_stk = st.number_input("Stock Inicial *", min_value=0, step=1)
                p_min = st.number_input("Stock Mínimo Alerta", min_value=1, value=5)

            if st.form_submit_button("💾 Guardar Producto", type="primary"):
                if p_nom and p_pv >= 0 and p_stk >= 0:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO productos (nombre, categoria, precio_venta, costo_compra, stock, stock_minimo)
                                 VALUES (?, ?, ?, ?, ?, ?)""",
                              (p_nom.strip(), p_cat.strip(), p_pv, p_pc, p_stk, p_min))
                    conn.commit()
                    conn.close()
                    st.success(f"¡Producto '{p_nom}' guardado!")
                    st.rerun()

    conn = get_db_connection()
    df_p = pd.read_sql_query("SELECT id, nombre, categoria, precio_venta, costo_compra, stock, stock_minimo FROM productos", conn)
    conn.close()

    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
    else:
        st.info("No hay productos registrados en el inventario.")

    render_module_footer()

# ==========================================
# 9. MÓDULO: CLIENTES
# ==========================================
elif st.session_state.current_module == "clientes":
    render_module_header("Directorio de Clientes", "👥", "Guarda el registro completo de tus clientes.")

    with st.expander("➕ Registrar Nuevo Cliente", expanded=True):
        with st.form("form_add_cliente"):
            c1, c2 = st.columns(2)
            with c1:
                c_nom = st.text_input("Nombre Completo del Cliente *")
                c_tel = st.text_input("Número de Teléfono / WhatsApp")
            with c2:
                c_dir = st.text_input("Dirección de Residencia / Entrega")
                c_eml = st.text_input("Correo Electrónico")

            if st.form_submit_button("💾 Guardar Cliente", type="primary"):
                if c_nom:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO clientes (nombre, telefono, direccion, email, saldo_pendiente)
                                 VALUES (?, ?, ?, ?, 0.0)""",
                              (c_nom.strip(), c_tel.strip(), c_dir.strip(), c_eml.strip()))
                    conn.commit()
                    conn.close()
                    st.success(f"¡Cliente '{c_nom}' registrado correctamente!")
                    st.rerun()

    conn = get_db_connection()
    df_c = pd.read_sql_query("SELECT id, nombre, telefono, direccion, email, saldo_pendiente FROM clientes", conn)
    conn.close()

    if not df_c.empty:
        st.dataframe(df_c, use_container_width=True)

    render_module_footer()

# ==========================================
# 10. MÓDULO: PROVEEDORES
# ==========================================
elif st.session_state.current_module == "proveedores":
    render_module_header("Directorio de Proveedores", "🏭", "Administra los datos de contacto y días de atención de tus proveedores.")

    with st.expander("➕ Registrar Nuevo Proveedor", expanded=True):
        with st.form("form_add_proveedor"):
            c1, c2, c3 = st.columns(3)
            with c1:
                pr_nom = st.text_input("Nombre del Proveedor / Empresa *")
                pr_tel = st.text_input("Teléfono / WhatsApp")
            with c2:
                pr_nit = st.text_input("CC / NIT / RUT")
                pr_eml = st.text_input("Correo Electrónico")
            with c3:
                pr_dir = st.text_input("Dirección Física")
                pr_dia = st.selectbox("Día de Visita / Pedido", ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo", "Variable"])
            
            pr_nota = st.text_area("Nota / Observación Adicional")

            if st.form_submit_button("💾 Guardar Proveedor", type="primary"):
                if pr_nom:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO proveedores (nombre, telefono, nit_cc, email, direccion, dia_visita, nota)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
                              (pr_nom.strip(), pr_tel.strip(), pr_nit.strip(), pr_eml.strip(), pr_dir.strip(), pr_dia, pr_nota.strip()))
                    conn.commit()
                    conn.close()
                    st.success(f"¡Proveedor '{pr_nom}' guardado!")
                    st.rerun()

    conn = get_db_connection()
    df_prov = pd.read_sql_query("SELECT id, nombre, telefono, nit_cc, email, direccion, dia_visita, nota FROM proveedores", conn)
    conn.close()

    if not df_prov.empty:
        st.dataframe(df_prov, use_container_width=True)

    render_module_footer()

# ==========================================
# 11. MÓDULO: COTIZACIONES
# ==========================================
elif st.session_state.current_module == "cotizaciones":
    render_module_header("Cotizaciones y Generador de Mensajes", "📝", "Genera cotizaciones formales y mensajes cordiales listos para enviar a tus clientes.")

    with st.form("form_cotizacion"):
        c1, c2 = st.columns(2)
        with c1:
            q_cliente = st.text_input("Nombre del Cliente *")
            q_dir = st.text_input("Dirección (Uso interno - Excluida del mensaje)")
            q_pedido = st.text_area("Detalle del Pedido / Productos *")
        with c2:
            q_precio = st.number_input("Precio del Pedido ($) *", min_value=0.0, step=5000.0)
            q_domi = st.number_input("Precio de Domicilio / Envío ($)", min_value=0.0, step=1000.0)
            q_fecha = st.text_input("¿Para cuándo estaría listo? (Ej: Mañana a las 3:00 PM)")

        if st.form_submit_button("💾 Generar Cotización y Mensaje", type="primary"):
            if q_cliente and q_pedido and q_precio > 0:
                total_q = q_precio + q_domi
                
                saludos = ["¡Hola!", "¡Un gusto saludarte!", "¡Buenas tardes!", "¡Hola, qué tal!"]
                saludo = random.choice(saludos)
                
                msg = f"""{saludo} {q_cliente} 👋✨

Nos alegra atenderte en *{cfg.get('app_nombre', 'BENEFIR')}*. Con mucho gusto te compartimos el detalle de tu cotización:

🛍️ *Pedido:* {q_pedido}
💵 *Valor del Pedido:* {cfg.get('moneda', '$')}{q_precio:,.2f}
🚚 *Costo de Domicilio:* {cfg.get('moneda', '$')}{q_domi:,.2f}
💰 *TOTAL A PAGAR:* {cfg.get('moneda', '$')}{total_q:,.2f}

⏰ *Tiempo Estimado de Entrega:* {q_fecha if q_fecha else 'A convenir'}

Quedamos atentos a tu confirmación para procesar tu solicitud de inmediato. ¡Muchas gracias por preferirnos! 😊🙌"""

                conn = get_db_connection()
                c = conn.cursor()
                c.execute("""INSERT INTO cotizaciones (cliente_nombre, direccion, pedido, precio_pedido, precio_domicilio, total, fecha_entrega, fecha_creacion, estado, mensaje_generado)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', ?)""",
                          (q_cliente.strip(), q_dir.strip(), q_pedido.strip(), q_precio, q_domi, total_q, q_fecha, datetime.datetime.now(), msg))
                conn.commit()
                conn.close()

                st.session_state.last_quote_msg = msg
                st.success("¡Cotización creada correctamente!")
                st.rerun()

    if "last_quote_msg" in st.session_state:
        st.markdown("### 💬 Mensaje Personalizado Generado (Sin dirección por privacidad)")
        st.code(st.session_state.last_quote_msg, language="markdown")

    render_module_footer()

# ==========================================
# 12. MÓDULO: GASTOS
# ==========================================
elif st.session_state.current_module == "gastos":
    render_module_header("Control de Gastos Operativos", "💸", "Registra salidas de dinero por Gastos Simples, Generales y Administrativos.")

    with st.form("form_gastos"):
        c1, c2, c3 = st.columns(3)
        with c1:
            g_fecha = st.date_input("Fecha del Gasto", value=datetime.date.today())
            g_tipo = st.selectbox("Tipo de Gasto *", ["Gasto Simple", "Gasto General", "Gasto Administrativo"])
        with c2:
            g_cat = st.text_input("Categoría (Ej: Servicios, Arriendo, Papelería)")
            g_pago = st.selectbox("Origen del Dinero", ["Efectivo", "Banco / Transferencia"])
        with c3:
            g_monto = st.number_input("Monto ($) *", min_value=0.0, step=5000.0)
            g_desc = st.text_input("Descripción / Concepto")

        if st.form_submit_button("💾 Guardar Gasto", type="primary"):
            if g_monto > 0:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("""INSERT INTO gastos (fecha, tipo_gasto, categoria, descripcion, monto, metodo_pago)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (g_fecha, g_tipo, g_cat.strip(), g_desc.strip(), g_monto, g_pago))
                
                tipo_cta = "Efectivo" if "Efectivo" in g_pago else "Banco"
                c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto)
                             VALUES (?, ?, 'Egreso', ?, ?)""",
                          (g_fecha, tipo_cta, -g_monto, f"{g_tipo}: {g_desc}"))
                conn.commit()
                conn.close()
                st.success("¡Gasto registrado correctamente!")
                st.rerun()

    render_module_footer()

# ==========================================
# 13. MÓDULO: COMPRAS
# ==========================================
elif st.session_state.current_module == "compras":
    render_module_header("Control de Compras e Insumos", "🛍️", "Registra adquisiciones de mercancía, insumos o equipo.")

    conn = get_db_connection()
    provs = [p['nombre'] for p in pd.read_sql_query("SELECT nombre FROM proveedores", conn).to_dict('records')]
    conn.close()

    with st.form("form_compras"):
        c1, c2, c3 = st.columns(3)
        with c1:
            cmp_fecha = st.date_input("Fecha de Compra", value=datetime.date.today())
            cmp_tipo = st.selectbox("Tipo de Compra *", ["Compra Simple", "Compra General", "Compra Administrativa"])
        with c2:
            cmp_prov = st.selectbox("Proveedor", ["Proveedor Varios"] + provs)
            cmp_pago = st.selectbox("Método de Pago", ["Efectivo", "Banco / Transferencia", "Crédito (Cuenta por Pagar)"])
        with c3:
            cmp_monto = st.number_input("Monto Total ($) *", min_value=0.0, step=10000.0)
            cmp_desc = st.text_input("Descripción de lo comprado")

        if st.form_submit_button("💾 Guardar Compra", type="primary"):
            if cmp_monto > 0:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("""INSERT INTO compras (fecha, tipo_compra, proveedor, descripcion, monto, metodo_pago)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (cmp_fecha, cmp_tipo, cmp_prov, cmp_desc.strip(), cmp_monto, cmp_pago))

                if "Crédito" in cmp_pago:
                    c.execute("""INSERT INTO cuentas_por_pagar (proveedor, concepto, monto, fecha_vencimiento, estado)
                                 VALUES (?, ?, ?, ?, 'Pendiente')""",
                              (cmp_prov, f"{cmp_tipo}: {cmp_desc}", cmp_monto, cmp_fecha + datetime.timedelta(days=30)))
                else:
                    tipo_cta = "Efectivo" if "Efectivo" in cmp_pago else "Banco"
                    c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto)
                                 VALUES (?, ?, 'Egreso', ?, ?)""",
                              (cmp_fecha, tipo_cta, -cmp_monto, f"{cmp_tipo}: {cmp_desc} ({cmp_prov})"))

                conn.commit()
                conn.close()
                st.success("¡Compra guardada correctamente!")
                st.rerun()

    render_module_footer()

# ==========================================
# 14. MÓDULO: COSTOS Y PRESUPUESTO
# ==========================================
elif st.session_state.current_module == "costos":
    render_module_header("Costos y Presupuesto de Producción", "💰", "Estructura tus costos de materia prima, mano de obra y presupuestos.")

    with st.form("form_costos"):
        c1, c2, c3 = st.columns(3)
        with c1:
            cp_con = st.text_input("Concepto / Insumo / Material *")
            cp_cat = st.selectbox("Categoría de Costo", ["Materia Prima / Materiales", "Insumos Operativos", "Mano de Obra Directa", "Costos Fijos", "Costos Variables"])
        with c2:
            cp_cant = st.number_input("Cantidad", min_value=0.1, value=1.0, step=1.0)
            cp_unit = st.number_input("Costo Unitario ($) *", min_value=0.0, step=1000.0)
        with c3:
            cp_pres = st.number_input("Presupuesto Asignado ($)", min_value=0.0, step=10000.0)
            cp_fecha = st.date_input("Fecha", value=datetime.date.today())

        cp_notas = st.text_input("Notas / Observaciones")

        if st.form_submit_button("💾 Guardar Costo / Presupuesto", type="primary"):
            if cp_con and cp_unit >= 0:
                costo_total = cp_cant * cp_unit
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("""INSERT INTO costos_presupuesto (concepto, categoria, cantidad, costo_unitario, costo_total, presupuesto_asignado, notas, fecha)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (cp_con.strip(), cp_cat, cp_cant, cp_unit, costo_total, cp_pres, cp_notas.strip(), cp_fecha))
                conn.commit()
                conn.close()
                st.success("¡Costo guardado!")
                st.rerun()

    conn = get_db_connection()
    df_cost = pd.read_sql_query("SELECT id, concepto, categoria, cantidad, costo_unitario, costo_total, presupuesto_asignado, fecha FROM costos_presupuesto", conn)
    conn.close()

    if not df_cost.empty:
        st.dataframe(df_cost, use_container_width=True)

    render_module_footer()

# ==========================================
# 15. MÓDULO: CUENTAS POR COBRAR
# ==========================================
elif st.session_state.current_module == "cxc":
    render_module_header("Cuentas por Cobrar (Créditos a Clientes)", "💵", "Lleva el control de deudas pendientes de tus clientes y registra sus abonos.")

    conn = get_db_connection()
    df_cxc = pd.read_sql_query("SELECT id, cliente_nombre, concepto, monto_total, monto_pagado, saldo, fecha_emision, estado FROM cuentas_por_cobrar WHERE saldo > 0", conn)
    conn.close()

    if not df_cxc.empty:
        st.dataframe(df_cxc, use_container_width=True)

        st.markdown("### 📥 Registrar Abono o Pago de Cliente")
        with st.form("form_abono_cxc"):
            c1, c2, c3 = st.columns(3)
            with c1:
                cxc_id = st.selectbox("Selecciona la Cuenta a Abonar", df_cxc['id'].tolist())
            with c2:
                monto_abono = st.number_input("Monto del Abono ($) *", min_value=0.0, step=5000.0)
            with c3:
                metodo_abono = st.selectbox("Recibido en", ["Efectivo", "Banco / Transferencia"])

            if st.form_submit_button("💾 Registrar Abono", type="primary"):
                if monto_abono > 0:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT cliente_id, saldo FROM cuentas_por_cobrar WHERE id = ?", (cxc_id,))
                    row_cxc = c.fetchone()
                    if row_cxc:
                        cli_id = row_cxc["cliente_id"]
                        saldo_actual = row_cxc["saldo"]
                        
                        nuevo_saldo = max(0.0, saldo_actual - monto_abono)
                        nuevo_estado = 'Pagado' if nuevo_saldo == 0 else 'Pendiente'

                        c.execute("UPDATE cuentas_por_cobrar SET monto_pagado = monto_pagado + ?, saldo = ?, estado = ? WHERE id = ?",
                                  (monto_abono, nuevo_saldo, nuevo_estado, cxc_id))
                        
                        if cli_id:
                            c.execute("UPDATE clientes SET saldo_pendiente = MAX(0.0, saldo_pendiente - ?) WHERE id = ?", (monto_abono, cli_id))

                        tipo_cta = "Efectivo" if "Efectivo" in metodo_abono else "Banco"
                        c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto)
                                     VALUES (?, ?, 'Ingreso', ?, ?)""",
                                  (datetime.datetime.now(), tipo_cta, monto_abono, f"Abono a Cuenta por Cobrar #{cxc_id}"))

                        conn.commit()
                        st.success("¡Abono registrado correctamente!")
                    conn.close()
                    st.rerun()
    else:
        st.info("No hay créditos o cuentas por cobrar pendientes.")

    render_module_footer()

# ==========================================
# 16. MÓDULO: CUENTAS POR PAGAR
# ==========================================
elif st.session_state.current_module == "cxp":
    render_module_header("Cuentas por Pagar (Proveedores)", "🚚", "Gestiona tus compromisos financieros y fechas de vencimiento con proveedores.")

    conn = get_db_connection()
    df_cxp = pd.read_sql_query("SELECT id, proveedor, concepto, monto, fecha_vencimiento, estado FROM cuentas_por_pagar", conn)
    conn.close()

    if not df_cxp.empty:
        st.dataframe(df_cxp, use_container_width=True)
    else:
        st.info("No tienes cuentas por pagar pendientes.")

    render_module_footer()

# ==========================================
# 17. MÓDULO: CAJA Y BANCO (TESORERÍA)
# ==========================================
elif st.session_state.current_module == "tesoreria":
    render_module_header("Caja y Banco (Flujo de Tesorería)", "🏦", "Supervisa el efectivo disponible y dinero en cuentas de banco.")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT SUM(monto) FROM caja_banco WHERE tipo_cuenta = 'Efectivo'")
    efectivo = c.fetchone()[0] or float(cfg.get("saldo_inicial_efectivo", "0.0"))

    c.execute("SELECT SUM(monto) FROM caja_banco WHERE tipo_cuenta = 'Banco'")
    banco = c.fetchone()[0] or float(cfg.get("saldo_inicial_banco", "0.0"))
    conn.close()

    col_e, col_b, col_t = st.columns(3)
    col_e.metric("Efectivo en Caja Chica", f"{cfg.get('moneda', '$')}{efectivo:,.2f}")
    col_b.metric("Cuentas de Banco", f"{cfg.get('moneda', '$')}{banco:,.2f}")
    col_t.metric("TOTAL TESORERÍA", f"{cfg.get('moneda', '$')}{(efectivo + banco):,.2f}")

    st.markdown("### 🔄 Transferencia entre Cuentas")
    with st.form("form_transferencia"):
        c1, c2, c3 = st.columns(3)
        with c1:
            origen = st.selectbox("Desde la cuenta:", ["Efectivo", "Banco"])
        with c2:
            destino = "Banco" if origen == "Efectivo" else "Efectivo"
            st.text_input("Hacia la cuenta:", value=destino, disabled=True)
        with c3:
            monto_trans = st.number_input("Monto a Transferir ($)", min_value=0.0, step=10000.0)

        if st.form_submit_button("💾 Transferir Dinero", type="primary"):
            if monto_trans > 0:
                conn = get_db_connection()
                c = conn.cursor()
                now = datetime.datetime.now()
                c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto, cuenta_destino)
                             VALUES (?, ?, 'Transferencia Salida', ?, ?, ?)""",
                          (now, origen, -monto_trans, f"Transferencia a {destino}", destino))
                
                c.execute("""INSERT INTO caja_banco (fecha, tipo_cuenta, tipo_movimiento, monto, concepto, cuenta_destino)
                             VALUES (?, ?, 'Transferencia Entrada', ?, ?, ?)""",
                          (now, destino, monto_trans, f"Transferencia desde {origen}", origen))
                conn.commit()
                conn.close()
                st.success(f"¡Transferencia de {cfg.get('moneda', '$')}{monto_trans:,.2f} realizada con éxito!")
                st.rerun()

    render_module_footer()

# ==========================================
# 18. MÓDULO: RENDIMIENTO Y BALANCE GENERAL
# ==========================================
elif st.session_state.current_module == "rendimiento":
    render_module_header("Rendimiento & Balance General", "📈", "Consolidado financiero e inteligencia de negocios de BENEFIR.")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT SUM(total) FROM ventas")
    tot_v = c.fetchone()[0] or 0.0

    c.execute("SELECT SUM(monto) FROM gastos")
    tot_g = c.fetchone()[0] or 0.0

    c.execute("SELECT SUM(monto) FROM compras")
    tot_c = c.fetchone()[0] or 0.0

    c.execute("SELECT SUM(saldo) FROM cuentas_por_cobrar")
    tot_cxc = c.fetchone()[0] or 0.0

    conn.close()

    utilidad_estimada = tot_v - (tot_g + tot_c)

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Ventas Totales Históricas", f"{cfg.get('moneda', '$')}{tot_v:,.2f}")
    b2.metric("Gastos Totales", f"{cfg.get('moneda', '$')}{tot_g:,.2f}")
    b3.metric("Compras Totales", f"{cfg.get('moneda', '$')}{tot_c:,.2f}")
    b4.metric("Utilidad Bruta Estimada", f"{cfg.get('moneda', '$')}{utilidad_estimada:,.2f}", delta="Positiva" if utilidad_estimada >= 0 else "Crítica")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📊 Gráficos de Balance Financiero")

    df_res = pd.DataFrame({
        'Categoría': ['Ventas', 'Gastos', 'Compras', 'Por Cobrar'],
        'Monto': [tot_v, tot_g, tot_c, tot_cxc]
    })

    fig = px.bar(df_res, x='Categoría', y='Monto', color='Categoría', title="Comparativo General de Entradas y Salidas", text_auto='.2s')
    st.plotly_chart(fig, use_container_width=True)

    render_module_footer()

# ==========================================
# 19. MÓDULO: MODO ADMIN PLUS (CONFIGURACIÓN)
# ==========================================
elif st.session_state.current_module == "admin":
    if st.session_state.user_role != "Admin":
        st.error("No tienes permisos de Administrador para acceder a este módulo.")
        st.stop()

    render_module_header("Modo Admin Plus - Configuración Avanzada", "⚙️", "Personaliza la interfaz, marca, usuarios, permisos y módulos sin tocar código.")

    adm_tab1, adm_tab2, adm_tab3, adm_tab4, adm_tab5 = st.tabs([
        "🎨 Interfaz, Marca, Fuentes & Logo", 
        "👥 Control de Usuarios & Permisos", 
        "🧩 Agregar Módulos Personalizados", 
        "🛠️ Personalización de Módulos",
        "🏦 Saldos Iniciales & Finanzas"
    ])

    # TAB 1: INTERFAZ, MARCA, FUENTES Y LOGO
    with adm_tab1:
        st.subheader("🎨 Personalización Visual, Tipografía y Logo")
        
        with st.form("form_cfg_visual_v9"):
            c1, c2 = st.columns(2)
            with c1:
                v_nombre = st.text_input("Nombre de la Aplicación", value=cfg.get("app_nombre", "BENEFIR"))
                v_eslogan = st.text_input("Eslogan o Subtítulo", value=cfg.get("app_eslogan", ""))
                v_icono = st.text_input("Icono Principal (Emoji)", value=cfg.get("app_icono", "💼"))
                v_moneda = st.text_input("Símbolo de Moneda", value=cfg.get("moneda", "$"))
                
                curr_font = cfg.get("fuente", "Poppins")
                idx_f = LISTA_FUENTES_GOOGLE.index(curr_font) if curr_font in LISTA_FUENTES_GOOGLE else 0
                v_fuente = st.selectbox("Tipografía de la Interfaz (+100 Fuentes Google)", LISTA_FUENTES_GOOGLE, index=idx_f)

            with c2:
                v_primario = st.color_picker("Color Primario", value=cfg.get("color_primario", "#2563EB"))
                v_secundario = st.color_picker("Color Secundario", value=cfg.get("color_secundario", "#1D4ED8"))
                v_fondo = st.color_picker("Color de Fondo", value=cfg.get("color_fondo", "#F8FAFC"))
                v_tarjetas = st.color_picker("Color de Tarjetas", value=cfg.get("color_tarjetas", "#FFFFFF"))
                v_bg_url = st.text_input("URL de Imagen de Fondo (Opcional)", value=cfg.get("bg_image_url", ""))

            st.markdown("---")
            st.markdown("##### 🖼️ Adjuntar Logo de la Empresa (PNG, JPG, WEBP)")
            uploaded_logo = st.file_uploader("Sube el archivo de tu logo desde tu computadora", type=["png", "jpg", "jpeg", "webp"])
            v_logo_url_input = st.text_input("O ingresa la URL directa del logo", value=cfg.get("logo_url", ""))

            if st.form_submit_button("💾 Guardar Ajustes Visuales & Marca", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                updates = {
                    "app_nombre": v_nombre, "app_eslogan": v_eslogan, "app_icono": v_icono,
                    "moneda": v_moneda, "fuente": v_fuente, "color_primario": v_primario,
                    "color_secundario": v_secundario, "color_fondo": v_fondo, "color_tarjetas": v_tarjetas,
                    "bg_image_url": v_bg_url, "logo_url": v_logo_url_input
                }

                if uploaded_logo is not None:
                    bytes_data = uploaded_logo.getvalue()
                    base64_str = base64.b64encode(bytes_data).decode('utf-8')
                    mime_type = uploaded_logo.type
                    updates["logo_data"] = f"data:{mime_type};base64,{base64_str}"

                for k, v in updates.items():
                    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, v))
                conn.commit()
                conn.close()
                st.success("¡Ajustes visuales y marca actualizados correctamente!")
                st.rerun()

    # TAB 2: CONTROL DE USUARIOS, ROLES Y PERMISOS GRANULARES
    with adm_tab2:
        st.subheader("👥 Administración de Usuarios, Roles y Permisos")
        
        conn = get_db_connection()
        df_users = pd.read_sql_query("SELECT id, nombre, usuario, rol, permisos, fecha_creacion FROM usuarios", conn)
        conn.close()
        st.dataframe(df_users, use_container_width=True)

        st.markdown("---")
        c_u1, c_u2 = st.columns(2)

        modulos_disponibles_keys = ["pos", "ventas", "inventario", "clientes", "proveedores", "cotizaciones", "gastos", "compras", "costos", "cxc", "cxp", "tesoreria", "rendimiento"]

        with c_u1:
            st.markdown("#### ➕ Crear Nuevo Usuario")
            with st.form("form_new_user_v9"):
                nu_nom = st.text_input("Nombre Completo")
                nu_usr = st.text_input("Nombre de Usuario")
                nu_pwd = st.text_input("Contraseña", type="password")
                nu_rol = st.selectbox("Rol", ["Empleado", "Admin", "Supervisor"])
                
                st.markdown("##### Permisos de Acceso a Módulos:")
                nu_perm_sel = []
                for m_k in modulos_disponibles_keys:
                    if st.checkbox(f"Acceso a {m_k.upper()}", value=True, key=f"chk_nu_{m_k}"):
                        nu_perm_sel.append(m_k)

                if st.form_submit_button("💾 Crear Usuario", type="primary"):
                    if nu_nom and nu_usr and nu_pwd:
                        perm_val = "ALL" if nu_rol == "Admin" else json.dumps(nu_perm_sel)
                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            c.execute("""INSERT INTO usuarios (nombre, usuario, password, rol, permisos, fecha_creacion)
                                         VALUES (?, ?, ?, ?, ?, ?)""",
                                      (nu_nom.strip(), nu_usr.strip(), hash_password(nu_pwd.strip()), nu_rol, perm_val, datetime.datetime.now()))
                            conn.commit()
                            st.success(f"¡Usuario '{nu_usr}' creado exitosamente!")
                        except sqlite3.IntegrityError:
                            st.error("Ese nombre de usuario ya existe.")
                        conn.close()
                        st.rerun()

        with c_u2:
            st.markdown("#### 🔑 Editar / Expulsar Usuario")
            with st.form("form_mod_user_v9"):
                usr_sel = st.selectbox("Selecciona Usuario", df_users['usuario'].tolist())
                new_pwd_usr = st.text_input("Nueva Contraseña (Opcional)", type="password")
                new_rol_usr = st.selectbox("Nuevo Rol", ["Empleado", "Admin", "Supervisor"])
                
                st.markdown("##### Actualizar Permisos Granulares:")
                mod_perm_sel = []
                for m_k in modulos_disponibles_keys:
                    if st.checkbox(f"Permitir {m_k.upper()}", value=True, key=f"chk_mod_{m_k}"):
                        mod_perm_sel.append(m_k)

                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    btn_chg = st.form_submit_button("💾 Actualizar Usuario", type="primary")
                with c_btn2:
                    btn_del = st.form_submit_button("❌ Expulsar / Eliminar Usuario")

                if btn_chg:
                    conn = get_db_connection()
                    c = conn.cursor()
                    perm_val = "ALL" if new_rol_usr == "Admin" else json.dumps(mod_perm_sel)
                    
                    if new_pwd_usr.strip():
                        c.execute("UPDATE usuarios SET password = ?, rol = ?, permisos = ? WHERE usuario = ?",
                                  (hash_password(new_pwd_usr.strip()), new_rol_usr, perm_val, usr_sel))
                    else:
                        c.execute("UPDATE usuarios SET rol = ?, permisos = ? WHERE usuario = ?",
                                  (new_rol_usr, perm_val, usr_sel))
                    conn.commit()
                    conn.close()
                    st.success("¡Usuario actualizado!")
                    st.rerun()

                if btn_del:
                    if usr_sel == "admin":
                        st.error("No se puede eliminar el usuario administrador maestro.")
                    else:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM usuarios WHERE usuario = ?", (usr_sel,))
                        conn.commit()
                        conn.close()
                        st.success(f"¡Usuario '{usr_sel}' expulsado y eliminado!")
                        st.rerun()

    # TAB 3: AGREGAR MÓDULOS PERSONALIZADOS (SIN TOUCH CODE)
    with adm_tab3:
        st.subheader("🧩 Agregar un Nuevo Módulo Personalizado (Sin Modificar Código)")
        st.caption("Crea paneles operativos a tu gusto para registrar cualquier tipo de dato de tu negocio.")

        with st.form("form_add_custom_mod"):
            c1, c2 = st.columns(2)
            with c1:
                cm_nom = st.text_input("Nombre del Módulo (Ej: Control de Vehículos)")
                cm_ico = st.text_input("Icono (Emoji)", value="🚀")
            with c2:
                cm_desc = st.text_input("Descripción breve del módulo")
            
            st.markdown("##### Configuración de Campos Personalizados:")
            st.caption("Ingresa los nombres de los campos separados por comas. Ej: `Placa, Modelo, Kilometraje, Estado, Costo Mantenimiento`")
            cm_campos = st.text_input("Nombres de Campos", value="Nombre, Categoria, Cantidad, Observaciones")

            if st.form_submit_button("💾 Crear Módulo Personalizado", type="primary"):
                if cm_nom and cm_campos:
                    lista_campos = [f.strip() for f in cm_campos.split(",") if f.strip()]
                    clave_mod = f"mod_{random.randint(1000, 9999)}"
                    campos_json_str = json.dumps(lista_campos)

                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO modulos_personalizados (clave, nombre, icono, descripcion, campos_json, activo)
                                 VALUES (?, ?, ?, ?, ?, 1)""",
                              (clave_mod, cm_nom.strip(), cm_ico.strip(), cm_desc.strip(), campos_json_str))
                    conn.commit()
                    conn.close()
                    st.success(f"¡Módulo '{cm_nom}' creado exitosamente y disponible en el Menú Principal!")
                    st.rerun()

    # TAB 4: PERSONALIZACIÓN DE MÓDULOS (ACTIVAR / OCULTAR / ELIMINAR)
    with adm_tab4:
        st.subheader("🛠️ Gestor y Personalizador de Módulos del Sistema")

        st.markdown("#### 🚀 Módulos Estándar del Sistema:")
        mod_dict_labels = {
            "pos": "🛒 Punto de Venta (POS)", "ventas": "🛍️ Registro Directo de Ventas",
            "inventario": "📦 Inventario y Productos", "clientes": "👥 Clientes",
            "proveedores": "🏭 Proveedores", "cotizaciones": "📝 Cotizaciones",
            "gastos": "💸 Gastos Operativos", "compras": "🛍️ Compras",
            "costos": "💰 Costos y Presupuesto", "cxc": "💵 Cuentas por Cobrar",
            "cxp": "🚚 Cuentas por Pagar", "tesoreria": "🏦 Caja y Banco",
            "rendimiento": "📈 Rendimiento & Balance"
        }

        try:
            curr_activos = json.loads(cfg.get("modulos_activos", "[]"))
        except:
            curr_activos = list(mod_dict_labels.keys())

        with st.form("form_toggle_std_mods"):
            sel_mods = []
            cols_m = st.columns(3)
            idx_m = 0
            for k_m, lbl_m in mod_dict_labels.items():
                with cols_m[idx_m % 3]:
                    is_on = k_m in curr_activos
                    if st.checkbox(lbl_m, value=is_on, key=f"chk_std_{k_m}"):
                        sel_mods.append(k_m)
                idx_m += 1

            if st.form_submit_button("💾 Guardar Visibilidad de Módulos Estándar", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('modulos_activos', ?)", (json.dumps(sel_mods),))
                conn.commit()
                conn.close()
                st.success("¡Visibilidad de módulos guardada!")
                st.rerun()

        st.markdown("---")
        st.markdown("#### 🧩 Módulos Personalizados (Gestión & Eliminación):")
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM modulos_personalizados")
        p_mods_all = c.fetchall()
        conn.close()

        if p_mods_all:
            for p_m in p_mods_all:
                col_p1, col_p2, col_p3 = st.columns([3, 1, 1])
                col_p1.write(f"**{p_m['icono']} {p_m['nombre']}** ({p_m['descripcion']})")
                
                with col_p2:
                    st.write("Estado: " + ("🟢 Activo" if p_m['activo'] == 1 else "🔴 Inactivo"))
                
                with col_p3:
                    if st.button("❌ Eliminar Módulo", key=f"del_mod_{p_m['id']}"):
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM modulos_personalizados WHERE id = ?", (p_m['id'],))
                        c.execute("DELETE FROM registros_modulo_pers WHERE modulo_clave = ?", (p_m['clave'],))
                        conn.commit()
                        conn.close()
                        st.success(f"Módulo '{p_m['nombre']}' eliminado.")
                        st.rerun()
        else:
            st.info("No has creado ningún módulo personalizado aún.")

    # TAB 5: SALDOS INICIALES Y FINANZAS
    with adm_tab5:
        st.subheader("🏦 Saldos Iniciales de Tesorería")
        with st.form("form_saldos_init_v9"):
            c1, c2 = st.columns(2)
            with c1:
                s_ef = st.number_input("Saldo Inicial Efectivo ($)", value=float(cfg.get("saldo_inicial_efectivo", "0.0")), step=10000.0)
            with c2:
                s_bc = st.number_input("Saldo Inicial Banco ($)", value=float(cfg.get("saldo_inicial_banco", "0.0")), step=10000.0)

            if st.form_submit_button("💾 Guardar Saldos Iniciales", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('saldo_inicial_efectivo', ?)", (str(s_ef),))
                c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('saldo_inicial_banco', ?)", (str(s_bc),))
                conn.commit()
                conn.close()
                st.success("¡Saldos iniciales guardados!")
                st.rerun()

    render_module_footer()

# ==========================================
# 20. MANEJADOR DE MÓDULOS PERSONALIZADOS
# ==========================================
elif st.session_state.current_module.startswith("pers_"):
    mod_id = st.session_state.current_module.replace("pers_", "")
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM modulos_personalizados WHERE id = ?", (mod_id,))
    mod_info = c.fetchone()
    conn.close()

    if mod_info:
        render_module_header(mod_info['nombre'], mod_info['icono'], mod_info['descripcion'] or "Módulo personalizado")
        
        try:
            campos_list = json.loads(mod_info['campos_json'])
        except:
            campos_list = ["Nombre", "Detalle"]

        st.markdown(f"### ➕ Agregar Nuevo Registro en {mod_info['nombre']}")
        with st.form(f"form_custom_reg_{mod_id}"):
            input_vals = {}
            cols_input = st.columns(min(len(campos_list), 3))
            for idx_field, field_name in enumerate(campos_list):
                with cols_input[idx_field % 3]:
                    input_vals[field_name] = st.text_input(f"{field_name} *")

            if st.form_submit_button("💾 Guardar Registro", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                datos_str = json.dumps(input_vals)
                c.execute("""INSERT INTO registros_modulo_pers (modulo_clave, datos_json, fecha_creacion, usuario)
                             VALUES (?, ?, ?, ?)""",
                          (mod_info['clave'], datos_str, datetime.datetime.now(), st.session_state.user_name))
                conn.commit()
                conn.close()
                st.success("¡Registro guardado exitosamente!")
                st.rerun()

        st.markdown("---")
        st.markdown(f"### 📋 Registros Almacenados en {mod_info['nombre']}")

        conn = get_db_connection()
        df_reg = pd.read_sql_query("SELECT id, datos_json, fecha_creacion, usuario FROM registros_modulo_pers WHERE modulo_clave = ? ORDER BY id DESC", conn, params=(mod_info['clave'],))
        conn.close()

        if not df_reg.empty:
            parsed_rows = []
            for _, r in df_reg.iterrows():
                try:
                    d_obj = json.loads(r['datos_json'])
                except:
                    d_obj = {}
                d_obj['ID'] = r['id']
                d_obj['Fecha'] = r['fecha_creacion']
                d_obj['Usuario'] = r['usuario']
                parsed_rows.append(d_obj)

            st.dataframe(pd.DataFrame(parsed_rows), use_container_width=True)
        else:
            st.info("No hay registros en este módulo personalizado aún.")

    render_module_footer()
