"""
Monitor de resultados SIMO (CNSC) -> notificación push vía ntfy.

Entra a SIMO con tu usuario, lee tus inscripciones ("Mis empleos") y la tabla
de resultados de cada una. Si aparece una prueba nueva o cambia un resultado,
te manda una notificación a ntfy.

Variables de entorno (en GitHub van como Secrets):
  SIMO_USER        usuario de SIMO (normalmente tu cédula)
  SIMO_PASS        contraseña de SIMO
  NTFY_TOPIC       tema de ntfy (usa uno largo y difícil de adivinar)
  NTFY_SERVER      opcional, por defecto https://ntfy.sh
  NTFY_TOKEN       opcional, si tu servidor/tema ntfy tiene token
  INCLUIR_PUNTAJE  opcional, "1" para incluir el puntaje en la notificación
  FILTRO           opcional, texto para vigilar solo ciertas inscripciones (ej. "DIAN")
  STATE_FILE       opcional, por defecto estado_simo.json
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import requests

try:  # evita errores de emojis/tildes en la consola de Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

BASE = "https://simo.cnsc.gov.co/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

USER = os.environ.get("SIMO_USER", "").strip()
PASS = os.environ.get("SIMO_PASS", "")
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "").strip()
INCLUIR_PUNTAJE = os.environ.get("INCLUIR_PUNTAJE", "") == "1"
FILTRO = os.environ.get("FILTRO", "").strip().lower()
STATE_FILE = os.environ.get("STATE_FILE", "estado_simo.json")


def ntfy(titulo, mensaje, prioridad="default", tags=""):
    if not TOPIC:
        print(f"[ntfy desactivado] {titulo}: {mensaje}")
        return
    headers = {"Title": titulo.encode("utf-8"), "Priority": prioridad}
    if tags:
        headers["Tags"] = tags
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    headers["Click"] = BASE
    r = requests.post(f"{NTFY_SERVER}/{TOPIC}", data=mensaje.encode("utf-8"),
                      headers=headers, timeout=20)
    r.raise_for_status()


def cargar_estado():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_estado(estado):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)


def get_json(s, path):
    # SIMO usa dojo JsonRest: paginación con el header Range
    r = s.get(BASE + path, timeout=40, headers={
        "Accept": "application/json", "Range": "items=0-99",
        "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return r.json()


def preparar_certificados(s):
    """SIMO no envía el certificado intermedio (GeoTrust TLS RSA CA G1), así que
    en Linux/Python la verificación TLS falla. Lo descargamos de la URL oficial
    de DigiCert y lo sumamos a los certificados raíz de certifi (la verificación
    sigue siendo completa)."""
    import ssl
    import tempfile

    import certifi
    ruta = os.path.join(tempfile.gettempdir(), "simo_ca_bundle.pem")
    if not os.path.exists(ruta):
        der = requests.get(
            "http://cacerts.geotrust.com/GeoTrustTLSRSACAG1.crt", timeout=30).content
        pem = ssl.DER_cert_to_PEM_cert(der)
        with open(certifi.where(), encoding="utf-8") as f:
            base = f.read()
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(base + "\n" + pem)
    s.verify = ruta


def login(s):
    s.get(BASE, timeout=40)
    r = s.post(BASE + "users/authenticate",
               data={"username": USER, "password": PASS},
               headers={"Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest"},
               timeout=40)
    if r.status_code in (401, 403):
        raise RuntimeError("Usuario o contraseña rechazados por SIMO")
    r.raise_for_status()


def texto(v):
    if isinstance(v, dict):
        return v.get("nombre") or v.get("descripcion") or v.get("label") or ""
    return "" if v is None else str(v)


def nombre_prueba(p):
    for k in ("prueba", "nombrePrueba", "nombre", "tipoPrueba", "descripcion"):
        if p.get(k):
            return texto(p[k])
    return "Prueba"


def resumen_inscripcion(ins):
    partes = []
    for k in ("convocatoria", "nombreConvocatoria", "empleo", "denominacion",
              "codigoEmpleo", "numeroOpec", "opec"):
        if ins.get(k):
            partes.append(texto(ins[k]))
    return " · ".join(p for p in partes if p)[:120] or f"Inscripción {ins.get('id')}"


def huella(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def main():
    if not USER or not PASS:
        sys.exit("Faltan SIMO_USER / SIMO_PASS")

    estado = cargar_estado()
    primera_vez = not estado.get("inscripciones")
    s = requests.Session()
    s.headers["User-Agent"] = UA

    try:
        preparar_certificados(s)
        login(s)
        inscripciones = get_json(s, "inscripcion/empleos/")
        if not isinstance(inscripciones, list):
            raise RuntimeError("SIMO no devolvió la lista de inscripciones "
                               "(¿login fallido?)")
    except Exception as e:  # noqa: BLE001
        print("ERROR:", e)
        # avisa solo la primera vez que falla, no en cada ejecución
        if not estado.get("error"):
            ntfy("Monitor SIMO: error", f"No pude revisar SIMO: {e}",
                 "low", "warning")
        estado["error"] = str(e)
        guardar_estado(estado)
        sys.exit(1)

    if estado.get("error"):
        ntfy("Monitor SIMO: funcionando otra vez", "Volví a entrar a SIMO.",
             "low", "white_check_mark")
    estado["error"] = None

    nuevas = []
    previas = estado.get("inscripciones", {})
    actuales = {}

    for ins in inscripciones:
        idi = ins.get("id")
        if idi is None:
            continue
        titulo = resumen_inscripcion(ins)
        if FILTRO and FILTRO not in json.dumps(ins, ensure_ascii=False).lower():
            continue
        try:
            pruebas = get_json(s, f"evaluacion/inscripcion/{idi}")
        except Exception as e:  # noqa: BLE001
            print(f"No pude leer resultados de {idi}: {e}")
            pruebas = previas.get(str(idi), {}).get("pruebas", {})
            actuales[str(idi)] = {"titulo": titulo, "pruebas": pruebas}
            continue

        mapa = {}
        for p in pruebas if isinstance(pruebas, list) else []:
            clave = str(p.get("id") or p.get("idEvaluaPrueba") or nombre_prueba(p))
            mapa[clave] = {
                "nombre": nombre_prueba(p),
                "resultado": texto(p.get("resultado")),
                "fecha": texto(p.get("fechaPublicacion")),
                "huella": huella(p),
            }
        actuales[str(idi)] = {"titulo": titulo, "pruebas": mapa}

        antes = previas.get(str(idi), {}).get("pruebas", {})
        for clave, p in mapa.items():
            a = antes.get(clave)
            if a is None or a.get("resultado") != p["resultado"] \
                    or a.get("fecha") != p["fecha"]:
                nuevas.append((titulo, p))

    estado["inscripciones"] = actuales
    estado["ultima_revision"] = datetime.now(timezone.utc).isoformat()
    guardar_estado(estado)

    total = sum(len(v["pruebas"]) for v in actuales.values())
    print(f"OK: {len(actuales)} inscripciones, {total} pruebas registradas, "
          f"{len(nuevas)} cambios.")
    for t, p in nuevas:
        print(f"  cambio en: {t} -> {p['nombre']} ({p['fecha']})")

    if primera_vez:
        lineas = [f"• {v['titulo']}: {len(v['pruebas'])} pruebas publicadas"
                  for v in actuales.values()]
        ntfy("Monitor SIMO activo ✅",
             "Entré a SIMO correctamente. Te aviso cuando haya resultados nuevos.\n"
             + "\n".join(lineas), "low", "eyes")
        return

    for titulo, p in nuevas:
        msg = f"{p['nombre']}\n{titulo}"
        if p["fecha"]:
            msg += f"\nPublicado: {p['fecha']}"
        if INCLUIR_PUNTAJE and p["resultado"]:
            msg += f"\nResultado: {p['resultado']}"
        ntfy("🚨 ¡Nuevo resultado en SIMO!", msg, "urgent", "rotating_light,tada")


if __name__ == "__main__":
    main()
