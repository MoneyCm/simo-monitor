# Monitor SIMO → ntfy

Revisa tu cuenta de SIMO cada 30 minutos con GitHub Actions y te manda una
notificación al celular (ntfy) cuando aparece un resultado nuevo, por ejemplo
el de las pruebas escritas de la DIAN.

## Instalación (unos 5 minutos)

1. **ntfy en el celular**: suscríbete a un tema con un nombre largo y difícil de
   adivinar, ej. `simo-dian-k38fhq2zx7`. Los temas de ntfy.sh son públicos para
   quien sepa el nombre.
2. **Repositorio en GitHub**: crea uno **privado** (ej. `simo-monitor`) y sube
   `simo_monitor.py`, `.gitignore` y `.github/workflows/simo.yml`.
3. **Secrets**: en el repo, *Settings → Secrets and variables → Actions → New
   repository secret*, crea:
   - `SIMO_USER`: tu usuario de SIMO
   - `SIMO_PASS`: tu contraseña de SIMO
   - `NTFY_TOPIC`: el tema del paso 1
4. **Probar**: pestaña *Actions → Monitor SIMO → Run workflow*. Deberías recibir
   **"Monitor SIMO activo ✅"** con la lista de tus inscripciones. Desde ahí
   corre solo cada 30 minutos.

## Notificaciones que vas a recibir

| Notificación | Cuándo |
|---|---|
| Monitor SIMO activo ✅ | La primera vez que entra bien |
| 🚨 ¡Nuevo resultado en SIMO! (prioridad urgente) | Aparece una prueba nueva o cambia un resultado |
| Monitor SIMO: error | Falló el login o SIMO está caído (solo avisa una vez hasta que se arregle) |

## Opciones (en `simo.yml`)

- `INCLUIR_PUNTAJE: "1"`: pone el puntaje en la notificación (por defecto no va,
  porque el tema de ntfy es semipúblico).
- `FILTRO: "DIAN"`: vigila solo las inscripciones que contengan ese texto.
- Frecuencia: cambia `*/30` en el `cron`. En un repo privado tienes 2000
  minutos gratis al mes; cada 30 min usa unos 1500. Cada 15 min se pasa del
  límite gratis, a menos que el repo sea público. Los secrets siguen ocultos en
  un repo público, pero los registros de ejecución sí se ven.

## Probarlo en tu PC (opcional)

```powershell
pip install requests
$env:SIMO_USER="tu_usuario"; $env:SIMO_PASS="tu_clave"; $env:NTFY_TOPIC="tu_tema"; python simo_monitor.py
```
