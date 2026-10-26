# AGENTS.md — Guía para Desarrolladores y Agentes de IA

Este documento describe la arquitectura, directrices técnicas, gotchas del sistema Win32 y flujos de trabajo de **HDMI Selector & OLED Saver**. Debe ser consultado por cualquier agente o desarrollador antes de realizar modificaciones en el código.

---

## 1. Visión General del Proyecto

**HDMI Selector & OLED Saver** es una utilidad para Windows diseñada especialmente para laptops con pantallas **OLED** conectadas a proyectores o monitores externos vía HDMI.

Su objetivo principal es:
1. Conmutar instantáneamente la topología de pantalla de Windows (`SetDisplayConfig`).
2. Gestionar el salvapantallas del sistema para evitar el quemado de paneles OLED (*burn-in*).
3. Permitir una docencia interactiva fluida (**Modo Docente**), manteniendo el proyector activo al 100% mientras la pantalla OLED de la laptop permanece apagada en reposo (negro puro `#000000`, 0 lúmenes) y se reactiva automáticamente únicamente cuando el cursor entra en la pantalla de la laptop.

---

## 2. Modos de Operación (`AppMode`)

Definidos en [`core/display_manager.py`](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/core/display_manager.py):

| Modo (`AppMode`) | Topología CCD | Salvapantallas | Telón OLED (`OledCurtain`) | Comportamiento |
|---|---|---|---|---|
| `PRESENTATION` (`presentation`) | `SDC_TOPOLOGY_EXTERNAL` | Pausado | Inactivo | Pantalla de laptop apagada por hardware; proyector activo al 100%. |
| `TEACHER` (`teacher`) | `SDC_TOPOLOGY_EXTEND` | Pausado | **Activo** | Escritorio extendido; proyector siempre encendido; pantalla OLED cubierta con `#000000`; se despierta al pasar el mouse a la laptop y se apaga tras inactividad (`teacher_timeout_seconds`). |
| `EXERCISES` (`exercises`) | `SDC_TOPOLOGY_EXTEND` | Pausado | Inactivo | Ambas pantallas encendidas para resolver ejercicios junto a alumnos. |
| `NORMAL` (`normal`) | `SDC_TOPOLOGY_INTERNAL` | **Activo** | Inactivo | Solo pantalla de la laptop; salvapantallas activo para proteger el panel OLED tras inactividad (`screensaver_timeout`). |

---

## 3. Estructura del Código

```text
HDMI_selector/
├── AGENTS.md                  # Este documento
├── conftest.py                # Configuración de entorno de pruebas (TCL/TK)
├── main.py                    # Entrada unificada CLI y GUI (argparse)
├── core/
│   ├── __init__.py            # Exporta AppConfig, DisplayManager, AppMode, HdmiMonitor, OledCurtain
│   ├── config.py              # AppConfig: dataclass con serialización JSON (~/.hdmi_selector_config.json)
│   ├── display_manager.py     # Win32 SetDisplayConfig, SystemParametersInfoW, registro
│   ├── hdmi_monitor.py        # Hilo daemon de detección de conexión HDMI y auto-recuperación
│   └── oled_curtain.py        # Telón negro puro Win32 y rastreador de cursor por monitor
├── ui/
│   ├── __init__.py
│   └── app.py                 # CustomTkinter GUI: tarjetas de modo, pie de configuración y ciclo de vida
└── tests/
    ├── test_config.py          # Pruebas de configuración y persistencia
    ├── test_display_manager.py # Pruebas de topología y llamadas Win32
    ├── test_hdmi_monitor.py    # Pruebas de hilo detector y auto-restore
    ├── test_main.py            # Pruebas de parser CLI, salidas JSON y códigos de salida
    ├── test_oled_curtain.py    # Pruebas del telón OLED, Win32 mocks y smoke test
    └── test_ui_app.py          # Pruebas de la interfaz gráfica y eventos CustomTkinter
```

---

## 4. Reglas Críticas y Gotchas del Sistema (Win32 & Tkinter)

### A. Win32 Ctypes y Bloqueos entre Hilos (Cross-Thread Deadlocks)
- **JAMÁS llamar a `UpdateWindow(hwnd)` de forma síncrona desde otro hilo** si el hilo propietario de la ventana está esperando en un `threading.Event.wait()`. En Windows, `UpdateWindow` envía un mensaje síncrono `WM_PAINT` que bloqueará al llamador hasta que el hilo de la ventana despache mensajes, causando un deadlock irrecuperable.
- **Solución implementada:** Usar siempre `ShowWindowAsync(hwnd, nCmdShow)` y `SetWindowPos` con flags asíncronas `0x4000` (`SWP_ASYNCWINDOWPOS | SWP_NOACTIVATE | SWP_SHOWWINDOW`).
- La creación y destrucción de la ventana `OledCurtainWindow` debe ejecutarse **exclusivamente dentro de su propio hilo** (`OledCurtainThread`).

### B. Delimitación Estricta de Monitores (`GetCursorPos` vs Monitor Bounds)
- En el Modo Docente, **solo los movimientos del cursor dentro de la pantalla principal (laptop)** deben despertar la pantalla o reiniciar el contador de inactividad.
- Los movimientos y clics dentro de la pantalla del proyector (Pantalla 2) **deben ignorarse**.
- Para detectar los límites exactos del monitor principal se utiliza `EnumDisplayMonitors` junto con `GetMonitorInfoW` (`MONITORINFOF_PRIMARY`). Si la enumeración falla, se utiliza el fallback `(0, 0, GetSystemMetrics(0), GetSystemMetrics(1))`.

### C. No Colapsar Ventanas en Modo Docente
- En el Modo Docente **nunca debe aplicarse `SDC_TOPOLOGY_EXTERNAL`**, ya que Windows colapsa todas las ventanas (notas de clase, Excel de calificaciones, etc.) hacia la pantalla externa. Siempre debe usarse `SDC_TOPOLOGY_EXTEND`.

### D. Auto-Restauración de Seguridad (`auto_restore`)
- Si el cable HDMI se desconecta físicamente mientras el sistema está en `AppMode.PRESENTATION` o `AppMode.TEACHER`, [`HdmiMonitor`](file:///C:/Users/diego/utilidades_codigo/HDMI_selector/core/hdmi_monitor.py) debe restaurar inmediatamente `AppMode.NORMAL` para encender la pantalla de la laptop y asegurar que el usuario nunca se quede sin señal ni a oscuras.

### E. Destrucción Limpia de Tkinter / CustomTkinter en Pruebas
- En Windows y Python 3.14+, `customtkinter.CTk` programa callbacks diferidos mediante `after()` (iconos de barra de título, escalado DPI).
- Si se destruye la ventana sin cancelar esos timers, los callbacks se ejecutan en el siguiente intérprete Tcl y causan errores `TclError: invalid command name` o conflictos de compartición de archivos (`sharing violation`).
- **Patrón obligatorio en tests:** Usar el helper `_safe_destroy(app)` que recorre `app.tk.call('after', 'info')` y cancela cada uno con `app.after_cancel(after_id)` antes de invocar `app.destroy()`.

### F. Detección de HDMI y Cambios de Topología
- La detección de HDMI usa `QDC_ALL_PATHS` + `targetAvailable`: con `QDC_ONLY_ACTIVE_PATHS` el HDMI es invisible en modo `NORMAL`.
- Un error de `QueryDisplayConfig` devuelve `None` (desconocido), **nunca** "desconectado". `HdmiMonitor` ignora `None`, exige 2 sondeos consecutivos desconectados y respeta un periodo de gracia tras `notify_mode_change()`; Windows reporta el HDMI ausente durante el cambio de topología.
- `apply_mode()` devuelve `topology_ok` / `screensaver_ok`; `success` equivale a `topology_ok`. `set_display_topology` reintenta y verifica (bloquea varios segundos).

### G. Hilos en la GUI
- `select_mode` y `refresh_status` corren en segundo plano (`_run_in_background`) y entregan resultados por una `queue.Queue` que se vacía con `after(50)`. Nunca llamar `after()` ni tocar widgets desde otros hilos.
- La GUI y el auto-restore se excluyen mediante `HdmiMonitor.mode_lock`.
- El telón se arranca solo cuando se conoce la topología real (`_on_detected_mode`) o tras aplicar Docente con éxito, y se detiene **antes** de aplicar otro modo.
- En tests, el ejecutor es síncrono y se usa `app.process_pending()` para vaciar la cola.

### H. Telón OLED
- La clase de ventana se registra una sola vez por proceso y el `WNDPROC` se conserva siempre (re-registrar libera el thunk y provoca crashes).
- El monitor interno se identifica por nombre de dispositivo GDI, no por geometría (sin DPI awareness las coordenadas difieren).

---

## 5. Comandos de Verificación y Compilación

### Ejecución de Pruebas Unitarias
Todas las pruebas del proyecto deben pasar al 100%:
```powershell
pytest -v
```

### Ejecución de la Aplicación
```powershell
# Interfaz Gráfica
python main.py

# Consultar Estado del Sistema (JSON)
python main.py --status

# Cambiar Modo por Línea de Comandos
python main.py --mode teacher
python main.py --mode presentation
python main.py --mode exercises
python main.py --mode normal
```

### Compilación con PyInstaller
Los archivos de especificación (`.spec`) residen en la raíz del repositorio (`C:\Users\diego\utilidades_codigo`):
```powershell
# Compilar versión con Interfaz Gráfica (sin consola)
pyinstaller --noconfirm HDMI_Selector_GUI.spec

# Compilar versión CLI
pyinstaller --noconfirm HDMI_Selector.spec
```
Los ejecutables resultantes se generan en `dist/`:
- `dist/HDMI_Selector_GUI.exe`
- `dist/HDMI_Selector.exe`

### Acceso Directo de Windows
El acceso directo de escritorio está ubicado en:
- `C:\Users\diego\Desktop\HDMI Selector.lnk`
- Apunta a: `C:\Users\diego\utilidades_codigo\dist\HDMI_Selector_GUI.exe`
