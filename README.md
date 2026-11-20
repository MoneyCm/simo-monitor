# Monitor SIMO → ntfy + correo

Revisa una cuenta de SIMO (CNSC) **cada 5 minutos** con GitHub Actions y avisa
al celular (ntfy) y por correo cuando aparece un resultado nuevo: puntaje por
prueba, puesto, total, puesto general y estado.

## Privacidad (el repositorio es público)

- El usuario, la contraseña, el tema de ntfy y el correo van como **Secrets**:
  GitHub nunca los muestra, ni siquiera en los registros.
- Los registros solo muestran conteos ("1 inscripción revisada, 0 con cambios"),
  nunca nombres ni puntajes.
- El estado guardado entre ejecuciones solo tiene huellas HMAC con clave, no
  los datos.
- Los puntajes solo viajan en la notificación, por eso conviene que el tema de
  ntfy sea largo y difícil de adivinar.

## Secrets

En *Settings → Secrets and variables → Actions*:

| Secret | Qué es |
|---|---|
| `SIMO_USER` | usuario de SIMO |
| `SIMO_PASS` | contraseña de SIMO |
| `NTFY_TOPIC` | tema de ntfy del celular |
| `NTFY_EMAIL` | *(opcional)* tu Gmail para recibir también las alertas urgentes |
| `GMAIL_APP_PASSWORD` | *(opcional)* contraseña de aplicación de ese Gmail ([crearla aquí](https://myaccount.google.com/apppasswords)) |

## Cómo funciona la frecuencia

Cada hora GitHub lanza un trabajo que revisa SIMO cada 5 minutos durante unas
5 h 40 min. Como siempre queda uno en fila, si GitHub se retrasa con el horario
el trabajo que ya está corriendo cubre el hueco. En un repo público los minutos
de Actions son gratis.

> GitHub pausa los workflows programados tras 60 días sin actividad en el repo.
> Si llega el correo de aviso, entra a *Actions* y dale **Enable workflow**.

## Comandos útiles

Enviar ya el resumen de puntajes al celular:

```powershell
gh workflow run simo.yml -R MoneyCm/simo-monitor -f resumen=true
```

Enviar una alerta urgente de prueba (push + correo):

```powershell
gh workflow run simo.yml -R MoneyCm/simo-monitor -f prueba=true
```

Apagar el monitor:

```powershell
gh workflow disable simo.yml -R MoneyCm/simo-monitor
```

## Notificaciones

| Notificación | Cuándo |
|---|---|
| Monitor SIMO activo ✅ | La primera vez que entra bien |
| 🚨 ¡Nuevo resultado en SIMO! (urgente, también por correo) | Aparece una prueba nueva o cambian los puntajes |
| Monitor SIMO: error | Falla el login o SIMO está caído (avisa una vez hasta que se arregle) |
| 📊 Resumen | Cuando lo pides con el comando de arriba |
