[README.md](https://github.com/user-attachments/files/33090281/README.md)
# 💼 BENEFIR v9.0 - Sistema Integral de Gestión Comercial e Inventarios

¡Bienvenido al repositorio oficial de **BENEFIR v9.0 (Edición Final - Arte Visual & Gestión Total)**!

BENEFIR es una plataforma web integral de gestión empresarial diseñada para optimizar el control de ventas, inventario, clientes, proveedores, caja/bancos, cotizaciones, cuentas por cobrar/pagar y analítica financiera en tiempo real.

---

## 🚀 Despliegue y Ejecución

### ☁️ Opción 1: En la Nube (Streamlit Cloud)
Esta aplicación está lista para ejecutarse directamente en **Streamlit Cloud**:
1. Archivo principal de ejecución: `app_benefir-v9.py`
2. Dependencias del sistema: `requirements.txt`

### 💻 Opción 2: Ejecución Local en Windows (1 solo Clic)
1. Clona o descarga este repositorio en tu computadora.
2. Asegúrate de tener los archivos `app_benefir-v9.py` e `iniciar_benefir.bat` en la misma carpeta.
3. Haz doble clic en **`iniciar_benefir.bat`**.

---

## 🔑 Credenciales Maestras por Defecto

* **Usuario:** `admin`
* **Contraseña:** `admin123`

> *Nota: Puedes cambiar la contraseña predeterminada o crear nuevos usuarios con permisos personalizados desde el módulo **Modo Admin Plus**.*

---

## ✨ Características Destacadas de la Versión 9.0

* **🎨 Diseño "Arte Visual"**: Interfaz moderna con tarjetas elevadas, sombras suaves, micro-interacciones hover y cero código o etiquetas expuestas.
* **🏠 Navegación Limpia de 1 Clic**: Barra lateral despejada, mosaico interactivo en la pantalla de inicio y botón *🏠 Volver al Inicio* en la parte superior e inferior de todos los módulos.
* **⚙️ Modo Admin Plus Avanzado**:
  * **+100 Fuentes de Google Fonts**: Personalización tipográfica instantánea desde menú desplegable.
  * **🖼️ Logo Corporativo**: Carga y gestión de logo de la empresa (`PNG`, `JPG`, `WEBP`).
  * **👥 Gestión Granular de Usuarios**: Control de roles (*Admin, Empleado, Supervisor*), asignación de permisos módulo por módulo y opción de expulsión.
  * **🧩 Creador de Módulos Personalizados**: Creación de nuevos campos y paneles a la medida del negocio sin tocar código.
  * **🛠️ Personalización de Módulos**: Habilita o deshabilita módulos estándar según la necesidad operativa.
* **📊 Módulos Comerciales y Financieros Completo**:
  * Puntos de Venta (POS) y Gestión de Catálogo de Productos.
  * Control de Clientes, Abonos y Historial Crediticio.
  * Gestión de Proveedores, Compras y Cuentas por Pagar.
  * Control de Caja Chica y Cuentas Bancarias.
  * Cotizaciones en PDF/Texto y Mensajes Personalizados para Clientes.
  * Gráficos Interactivos y Balances Financieros con Plotly.

---

## 🛠️ Tecnologías Utilizadas

* **Python 3.10+**
* **Streamlit** (Interfaz web interactiva)
* **Pandas** (Procesamiento y análisis de datos)
* **Plotly** (Visualizaciones e indicadores gráficos)
* **SQLite3** (Base de datos relacional integrada)

---

## 📄 Estructura del Repositorio

```text
├── app_benefir-v9.py     # Código fuente principal de la aplicación BENEFIR v9
├── requirements.txt      # Archivo de dependencias para despliegue en la nube
└── README.md             # Documentación oficial del repositorio
```
