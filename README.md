# HDMI Selector & OLED Saver

<img src="assets/icon.png" width="64" align="right" alt="icono">

Utilidad para Windows pensada para laptops con pantalla **OLED** conectadas a un proyector o monitor externo por HDMI. Cambia la configuración de pantallas con un clic y protege el panel OLED contra el quemado (*burn-in*).

## Modos

| Modo | Pantallas | Salvapantallas | Uso |
|---|---|---|---|
| **Presentación** | Solo proyector | Pausado | Diapositivas a pantalla completa; la laptop se apaga. |
| **Docente** | Extendido + telón negro en la laptop | Pausado | El proyector siempre encendido; la pantalla OLED queda en negro puro y se despierta al mover el mouse sobre ella. |
| **Ejercicios** | Extendido, ambas encendidas | Pausado | Resolver ejercicios junto a los estudiantes. |
| **Normal** | Solo laptop | Activo | Uso habitual. |

Si el cable HDMI se desconecta en Presentación o Docente, la app vuelve sola a **Normal** para que nunca te quedes sin imagen.

## Requisitos

- Windows 10/11
- Python 3.12+ (probado con 3.14)

```powershell
pip install -r requirements.txt
```

## Uso

El paquete se importa como `HDMI_selector`, así que la carpeta del repo debe llamarse así (es el nombre por defecto al clonar).

```powershell
git clone https://github.com/DAG94S/HDMI_selector.git
cd HDMI_selector

# Interfaz gráfica
python main.py

# Línea de comandos
python main.py --status            # estado en JSON
python main.py --mode presentation
python main.py --mode teacher      # el telón OLED solo funciona con la GUI abierta
python main.py --mode exercises
python main.py --mode normal
```

## Compilar el ejecutable

Desde la carpeta **padre** del repo:

```powershell
pip install pyinstaller
pyinstaller --noconfirm HDMI_selector/HDMI_Selector_GUI.spec   # GUI sin consola
pyinstaller --noconfirm HDMI_selector/HDMI_Selector.spec       # CLI
```

Los ejecutables quedan en `dist/`.

## Pruebas

```powershell
pytest -q
```

## Para desarrolladores

Consulta [AGENTS.md](AGENTS.md): arquitectura, reglas Win32 (bloqueos entre hilos, detección de monitores, auto-restauración) y patrones de prueba.
