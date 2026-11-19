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
MODO = os.environ.get("MODO", "").strip().lower()  # "resumen" = enviar resumen ya


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
    # SIMO pagina con ?page=N&size=M (por defecto devuelve solo 20 filas)
    r = s.get(BASE + path, timeout=60, params={"page": 0, "size": 5000},
              headers={"Accept": "application/json",
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
    partes = [texto(ins.get(k)) for k in
              ("convocatoriaNombre", "denominacionNombre", "codigoEmpleo")]
    return " · ".join(p for p in partes if p)[:150] or f"Inscripción {ins.get('id')}"


def huella(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def numero(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def fmt(v):
    n = numero(v)
    return texto(v) if n is None else f"{n:.2f}".rstrip("0").rstrip(".")


def estructura(nombre, data):
    """Imprime en el log solo los NOMBRES de los campos (sin valores), para
    poder ajustar el script si SIMO cambia algo."""
    fila = data[0] if isinstance(data, list) and data else data
    claves = sorted(fila.keys()) if isinstance(fila, dict) else type(fila).__name__
    n = len(data) if isinstance(data, list) else 1
    print(f"  [estructura] {nombre}: {n} filas, campos={claves}")


def detalle(s, ins):
    """Puntaje por prueba + total y puesto entre los aspirantes del empleo."""
    idi = ins.get("id")
    emp = ins.get("empleoId")
    if not emp and isinstance(ins.get("empleo"), dict):
        emp = ins["empleo"].get("id")
    out = {"pruebas": [], "total": None, "puesto": None, "aspirantes": None}

    try:
        filas = get_json(s, f"evaluacion/inscripcion/resultadospruebas/{idi}")
        estructura("resultadospruebas", filas)
        out["_raw"] = filas if isinstance(filas, list) else []
        for p in filas if isinstance(filas, list) else []:
            out["pruebas"].append({
                "nombre": nombre_prueba(p),
                "calificacion": fmt(p.get("calificacion")),
                "puesto": texto(p.get("puesto")),
                "aprobatorio": fmt(p.get("valorAprobatorio")),
                "ponderacion": fmt(p.get("ponderacion")),
            })
    except Exception as e:  # noqa: BLE001
        print(f"  no pude leer resultados por prueba: {e}")

    if emp:
        try:
            # igual que la pantalla "Resultados" de SIMO: mi registro consolidado
            mia = get_json(s, f"evaluacion/inscripcion/resultadosconsolidados/{emp}/{idi}")
            estructura("resultadoconsolidado", mia)
            if isinstance(mia, dict) and mia:
                if mia.get("calificacion") not in (None, ""):
                    out["total"] = fmt(mia.get("calificacion"))
                if mia.get("puesto"):
                    out["puesto"] = texto(mia["puesto"])
                out["estado"] = texto(mia.get("estado"))
        except Exception as e:  # noqa: BLE001
            print(f"  no pude leer resultado consolidado: {e}")
    if ins.get("totalCiudadanosInscritos"):
        out["aspirantes"] = ins["totalCiudadanosInscritos"]
    out.pop("_raw", None)
    return out


def texto_detalle(d):
    lineas = []
    for p in d["pruebas"]:
        l = f"• {p['nombre']}: {p['calificacion'] or 'sin publicar'}"
        extra = []
        if p.get("puesto"):
            extra.append(f"puesto {p['puesto']}")
        if p["aprobatorio"]:
            extra.append(f"aprueba con {p['aprobatorio']}")
        if p["ponderacion"]:
            extra.append(f"peso {p['ponderacion']}%")
        if extra:
            l += f" ({', '.join(extra)})"
        lineas.append(l)
    if d["total"] is not None:
        lineas.append(f"TOTAL: {d['total']}")
    if d["puesto"]:
        de = f" de {d['aspirantes']}" if d.get("aspirantes") else ""
        lineas.append(f"PUESTO GENERAL: {d['puesto']}{de}")
    if d.get("estado"):
        lineas.append(f"Estado: {d['estado']}")
    return "\n".join(lineas)


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
    resumenes = []
    previas = estado.get("inscripciones", {})
    actuales = {}

    for ins in inscripciones:
        idi = ins.get("id")
        if idi is None:
            continue
        titulo = resumen_inscripcion(ins)
        if FILTRO and FILTRO not in json.dumps(ins, ensure_ascii=False).lower():
            continue
        print(f"- Inscripción: {titulo}")
        if os.environ.get("DEBUG"):
            print("  [debug] campos inscripción:",
                  {k: (sorted(v.keys()) if isinstance(v, dict) else type(v).__name__)
                   for k, v in ins.items()})
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
        det = detalle(s, ins)
        det_txt = texto_detalle(det)
        actuales[str(idi)] = {"titulo": titulo, "pruebas": mapa,
                              "detalle": huella(det), "v": 2}
        resumenes.append((titulo, det_txt))

        prev = previas.get(str(idi), {})
        antes = prev.get("pruebas", {})
        cambios = [p for clave, p in mapa.items()
                   if antes.get(clave) is None
                   or antes[clave].get("resultado") != p["resultado"]
                   or antes[clave].get("fecha") != p["fecha"]]
        if prev.get("v") == 2 and prev.get("detalle") != huella(det) and (det["pruebas"] or det["total"]):
            cambios.append({"nombre": "Puntajes actualizados", "resultado": "",
                            "fecha": ""})
        # una inscripción que no estaba en el estado se registra sin avisar
        if cambios and str(idi) in previas:
            nuevas.append((titulo, cambios, det_txt))

    if MODO == "resumen" or FILTRO:
        # ejecución filtrada: no borrar del estado lo que ya se había visto
        actuales = {**previas, **actuales} if previas else actuales
    estado["inscripciones"] = actuales
    estado["ultima_revision"] = datetime.now(timezone.utc).isoformat()
    guardar_estado(estado)

    total = sum(len(v["pruebas"]) for v in actuales.values())
    print(f"OK: {len(actuales)} inscripciones, {total} pruebas registradas, "
          f"{len(nuevas)} cambios.")
    for t, cambios, _ in nuevas:
        for p in cambios:
            print(f"  cambio en: {t} -> {p['nombre']} ({p['fecha']})")

    if MODO == "resumen":
        # un mensaje por inscripción (ntfy corta los mensajes muy largos)
        if not resumenes:
            ntfy("📊 Resumen SIMO", "No encontré inscripciones con ese filtro.")
        for t, d in resumenes:
            cuerpo = (d or "Aún no hay puntajes publicados.") if INCLUIR_PUNTAJE \
                else "(activa INCLUIR_PUNTAJE para ver puntajes)"
            ntfy(f"📊 {t}"[:200], cuerpo, "default", "bar_chart")
        return

    if primera_vez:
        lineas = [f"• {v['titulo']}: {len(v['pruebas'])} pruebas publicadas"
                  for v in actuales.values()]
        ntfy("Monitor SIMO activo ✅",
             "Entré a SIMO correctamente. Te aviso cuando haya resultados nuevos.\n"
             + "\n".join(lineas), "low", "eyes")
        return

    for titulo, cambios, det_txt in nuevas:
        msg = titulo
        for p in cambios:
            msg += f"\n➡ {p['nombre']}"
            if p["fecha"]:
                msg += f" (publicado {p['fecha']})"
        if INCLUIR_PUNTAJE and det_txt:
            msg += "\n\n" + det_txt
        ntfy("🚨 ¡Nuevo resultado en SIMO!", msg, "urgent", "rotating_light,tada")


if __name__ == "__main__":
    main()
