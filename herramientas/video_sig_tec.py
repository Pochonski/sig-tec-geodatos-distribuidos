"""Monta un video narrado con capturas reales e informes existentes; no escribe en la BD.

Requiere Pillow, FFmpeg/ffprobe y los WAV creados con narrar_video.ps1.
Las capturas y consultas deben estar en entrega/evidencias antes de ejecutarlo.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "entrega"
W, H = 1920, 1080
BG, PANEL, TEXT, MUTED, GREEN = "#0b1823", "#142b3a", "#f4f8fa", "#b6cbd5", "#48d1b5"
NODES = ["central", "cartago", "san_jose", "san_carlos", "alajuela", "limon"]
LABEL = dict(zip(NODES, ["Central", "Cartago", "San José", "San Carlos", "Alajuela", "Limón"]))


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def font(size, bold=False):
    candidates = [Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    return ImageFont.truetype(str(next(p for p in candidates if p.is_file())), size)


def text(draw, value, box, size=32, color=TEXT, bold=False):
    left, top, right, bottom = box
    face = font(size, bold)
    lines = []
    for paragraph in str(value).split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if line and draw.textlength(candidate, font=face) > right-left:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    step = round(size*1.35)
    if top + step*len(lines) > bottom:
        raise ValueError(f"Texto fuera del panel: {value!r}")
    for line in lines:
        draw.text((left, top), line, font=face, fill=color)
        top += step
    return top


def panel(draw, box, fill=PANEL):
    draw.rounded_rectangle(box, radius=24, fill=fill)


def picture(canvas, path, box, crop=None):
    with Image.open(path) as source:
        img = source.convert("RGB")
        if crop:
            img = img.crop(crop)
        img = ImageOps.contain(img, (box[2]-box[0], box[3]-box[1]), Image.Resampling.LANCZOS)
        canvas.paste(img, (box[0]+(box[2]-box[0]-img.width)//2,
                           box[1]+(box[3]-box[1]-img.height)//2))


def table(draw, headers, rows, x, y, widths, height=66, size=28):
    starts = [x]
    for width in widths:
        starts.append(starts[-1]+width)
    for col, header in enumerate(headers):
        text(draw, header, (starts[col]+16, y, starts[col+1]-12, y+60), size, GREEN, True)
    y += 58
    for index, row in enumerate(rows):
        draw.rounded_rectangle((x, y, starts[-1], y+height-6), radius=9,
                               fill=PANEL if index % 2 == 0 else "#102431")
        for col, value in enumerate(row):
            text(draw, value, (starts[col]+16, y+10, starts[col+1]-12, y+height-5), size)
        y += height


def render(scene, index, evidence):
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    text(draw, "SIG-TEC / DEMOSTRACIÓN FINAL", (64, 35, 1600, 80), 23, GREEN, True)
    text(draw, scene["titulo"], (64, 95, 1860, 185), 58, TEXT, True)
    text(draw, scene["subtitulo"], (64, 190, 1850, 240), 30, MUTED)
    kind = scene["visual"]
    if kind == "portada":
        panel(draw, (64, 275, 860, 915))
        text(draw, "Bases de Datos II", (104, 320, 810, 400), 47, TEXT, True)
        text(draw, "Joseph · Joyce · Armando", (104, 415, 810, 480), 34, GREEN)
        text(draw, "5 campus + 1 central\nPostgreSQL 17 + PostGIS 3.6\nQGIS 3.44 LTR", (104, 535, 810, 730), 36)
        text(draw, "Capturas y consultas reales\nNarración sintética en español", (104, 780, 810, 900), 29, MUTED)
        picture(canvas, ROOT / "docs/imagenes/cartago-referencia.png", (905, 260, 1855, 930))
    elif kind == "arquitectura":
        assert len(evidence["preflight"]["nodes"]) == 6
        panel(draw, (600, 265, 1320, 470))
        text(draw, "CENTRAL", (650, 295, 1270, 360), 44, GREEN, True)
        text(draw, "Autenticación · campus · estilos\nCopias por esquema y redistribución", (650, 365, 1280, 460), 28)
        draw.line((960, 470, 960, 570), fill=GREEN, width=5)
        draw.line((220, 570, 1700, 570), fill=GREEN, width=5)
        for i, node in enumerate(NODES[1:]):
            x = 64 + i*363
            draw.line((x+170, 570, x+170, 655), fill=GREEN, width=4)
            panel(draw, (x, 650, x+340, 890))
            text(draw, LABEL[node], (x+23, 675, x+320, 730), 35, TEXT, True)
            text(draw, "Datos propios\nRéplicas globales\nPuerto " + str(55431+i), (x+23, 755, x+322, 885), 27)
        text(draw, "Nivel 1: campus → central     |     Nivel 2: central → otros campus", (100, 490, 1810, 550), 30, MUTED)
    elif kind == "modelo":
        rows = [[LABEL.get(l["name"], l["name"].replace("_", " ").capitalize()),
                 {"POLYGON":"Polygon", "LINESTRING":"LineString", "POINT":"Point"}[l["type"]], str(l["srid"])]
                for l in evidence["preflight"]["nodes"]["central"]["layers"]]
        table(draw, ["Capa", "Geometría", "SRID"], rows, 64, 270, [540, 350, 180], 69, 29)
        panel(draw, (1200, 300, 1855, 875))
        text(draw, "40 objetos de prueba", (1240, 335, 1820, 410), 37, GREEN, True)
        text(draw, "id BIGINT global\ncampus_id de pertenencia\ngeom del tipo definido\n\nSecuencia por campus:\ninicio = campus_id\nincremento = 5", (1240, 450, 1810, 860), 31)
    elif kind == "acceso":
        panel(draw, (64, 275, 720, 920))
        text(draw, "1   Cuenta individual\n2   Autenticar en el central\n3   Obtener campus\n4   Conectar al nodo\n5   Cargar ocho vistas", (105, 335, 680, 675), 35)
        text(draw, "Sesión: demo_cartago\nEstilos desde layer_styles\nEdición controlada en la BD", (105, 740, 680, 900), 29, GREEN)
        picture(canvas, OUT / "evidencias/qgis-mapa.png", (760, 275, 1855, 920))
    elif kind == "mapas":
        picture(canvas, OUT / "evidencias/qgis-mapa.png", (64, 265, 1855, 920))
    elif kind == "edicion":
        panel(draw, (64, 280, 1855, 910))
        picture(canvas, OUT / "evidencias/qgis-edificios.png", (85, 310, 1830, 700), (0, 0, 1180, 245))
        text(draw, "Guardado desde la vista sig.edificios", (110, 740, 1790, 805), 38, GREEN, True)
        text(draw, "Cuenta demo_cartago · identificador 1 · propietario Cartago", (110, 825, 1780, 885), 30)
    elif kind == "replica":
        names = evidence["replica"]["nodes"]
        assert all(r["nombre"] == evidence["replica"]["expected_name"] for r in names.values())
        table(draw, ["Nodo", "ID", "Campus", "Nombre confirmado"],
              [[LABEL[n], str(names[n]["id"]), str(names[n]["campus_id"]), names[n]["nombre"]] for n in NODES],
              64, 290, [300, 130, 190, 1170], 80, 29)
        text(draw, "Mismo objeto y pertenencia después de ambos saltos de replicación", (85, 860, 1810, 920), 32, GREEN)
    elif kind == "permisos":
        assert evidence["permisos"]["rejected"]
        picture(canvas, OUT / "evidencias/qgis-rechazo.png", (64, 285, 1110, 900), (300, 125, 1160, 510))
        panel(draw, (1150, 290, 1855, 900), "#39262c")
        text(draw, "RECHAZADO", (1190, 340, 1810, 420), 52, "#ff9d9d", True)
        text(draw, "Solo puede editar edificios de su campus", (1190, 470, 1805, 660), 38)
        text(draw, "Cuenta: Cartago (1)\nObjeto: San Carlos (3)\nDisparador: sig.editar_capa()", (1190, 720, 1805, 885), 29, MUTED)
    elif kind == "fallos":
        table(draw, ["Nodo detenido", "Escritura local", "Tras reiniciar", "Limpieza"],
              [[LABEL[s["stopped_node"]], "Confirmada" if s["local_write_while_node_down"] else "NO",
                "6 nodos convergen", "Fila temporal retirada" if s["temporary_row_removed_everywhere"] else "PENDIENTE"]
               for s in evidence["fallos"]["scenarios"]], 64, 300, [320, 410, 460, 600], 110, 31)
        panel(draw, (65, 635, 1855, 900))
        text(draw, "Central detenido", (105, 675, 1750, 740), 38, GREEN, True)
        text(draw, "Sesión existente: puede guardar en su campus.\nNuevo ingreso: central indisponible.\nCentral recuperado: acceso y propagación restablecidos.", (105, 755, 1785, 895), 31)
    elif kind == "dos_fases":
        labels = ["1  Preparar participantes", "2  Decisión duradera", "3  Resolver ambas ramas"]
        for i, label in enumerate(labels):
            x=64+i*608
            panel(draw, (x, 280, x+575, 420))
            text(draw, label, (x+25, 313, x+550, 410), 31, GREEN, True)
        selected = ["test_after_first_prepare", "test_after_both_prepare_before_decision", "test_after_commit_decision", "test_after_only_one_commit"]
        descriptions = ["Fallo tras primer PREPARE", "Caída antes de la decisión", "Caída después de COMMIT", "Solo un participante finalizado"]
        cases={s["scenario"]:s for s in evidence["dos_fases"]["scenarios"]}
        table(draw, ["Caso del laboratorio", "Decisión", "Auditorías", "Preparadas"],
              [[description, cases[key]["decision"], str(cases[key]["audit_rows"]), str(cases[key]["prepared_transactions"])]
               for key,description in zip(selected,descriptions)], 64, 485, [920, 300, 280, 290], 76, 28)
        text(draw, "9 casos aprobados · UUID estable · reintentos sin duplicar efectos", (85, 870, 1820, 930), 32, GREEN)
    elif kind == "respaldos":
        backup=evidence["respaldos"]
        def ok(value):
            assert value is True
            return "Verificado"
        table(draw, ["Nodo", "pg_dump", "pg_basebackup", "Restauración lógica"],
              [[LABEL[n], ok(backup["nodes"][n]["logical"]["verified"]),
                ok(backup["nodes"][n]["physical"]["verified"]),
                ok(backup["logical_restore_test"]["nodes"][n]["verified"])] for n in NODES],
              64, 290, [320, 430, 470, 570], 80, 29)
        text(draw, "Archivo WAL por instancia · respaldo físico comprobado con pg_verifybackup", (85, 860, 1820, 930), 30, GREEN)
    elif kind == "pitr":
        pitr=evidence["pitr"]
        assert pitr["checks"]["restored_fixture_matches"] and pitr["checks"]["original_fixture_deleted"]
        row=pitr["recovery_finished"]["restored_fixture"]
        panel(draw, (64, 280, 1855, 435))
        text(draw, "Respaldo  →  Punto nombrado  →  DELETE  →  Recuperar copia aislada", (100, 325, 1815, 425), 36, GREEN, True)
        panel(draw, (65, 490, 1000, 915))
        text(draw, "Edificio recuperado", (105, 525, 960, 595), 38, TEXT, True)
        text(draw, f"id: {row['id']}   |   campus: {row['campus_id']}\nNombre: {row['nombre']}\nCódigo: {row['codigo']}\nÁrea: {row['area']} m²   |   pisos: {row['pisos']}", (105, 635, 955, 895), 30)
        text(draw, "OK  Objetivo alcanzado\nOK  Atributos y geometría coinciden\nOK  Fila eliminada en el origen\nOK  Copia sin puertos publicados\nOK  WAL de solo lectura", (1060, 530, 1830, 910), 32, GREEN)
    elif kind == "reincorporacion":
        checks=evidence["reincorporacion"]["checks"]
        values=[("new_owner_only","Un solo propietario activo"), ("all_geography_converged","Datos geográficos convergentes"),
                ("insert_update_delete_both_hops","Altas, cambios y bajas en ambos saltos"),
                ("sequence_class_and_high_water","Secuencia por encima de IDs emitidos"),
                ("two_phase_retry","Operaciones 2PC reconciliadas"), ("outsiders_unchanged","Otros nodos conservados")]
        table(draw, ["Comprobación del laboratorio", "Resultado"],
              [[description, "Aprobado" if checks[key] else "NO"] for key,description in values],
              64, 290, [1290, 500], 80, 31)
        text(draw, "Propietario anterior detenido · volumen conservado · 0 transacciones preparadas", (85, 860, 1820, 930), 29, GREEN)
    elif kind == "cierre":
        panel(draw, (64, 280, 1855, 500))
        text(draw, "github.com/Pochonski/", (110, 320, 1805, 385), 44, GREEN, True)
        text(draw, "sig-tec-geodatos-distribuidos", (110, 395, 1805, 465), 47, TEXT, True)
        text(draw, "6 nodos saludables   ·   8 capas   ·   40 objetos ficticios\nNombres originales restaurados   ·   0 transacciones preparadas", (95, 560, 1820, 700), 35)
        text(draw, "Pendiente de confirmación docente: CRS institucional y escenario 2PC.\nCréditos cartográficos: © OpenStreetMap contributors · ODbL 1.0\nhttps://www.openstreetmap.org/copyright", (95, 770, 1820, 935), 28, MUTED)
    else:
        raise ValueError(kind)
    draw.line((64, 960, 1855, 960), fill="#315064", width=2)
    text(draw, scene["fuente"], (64, 980, 1800, 1045), 21, MUTED)
    draw.text((1810, 1012), f"{index:02d}/14", font=font(23, True), fill=GREEN)
    path=OUT / "video" / (scene["id"]+".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path


def seconds(path):
    with wave.open(str(path)) as stream:
        return stream.getnframes()/stream.getframerate()


def stamp(seconds_value):
    milliseconds=round(seconds_value*1000)
    return f"{milliseconds//3600000:02}:{milliseconds//60000%60:02}:{milliseconds//1000%60:02},{milliseconds%1000:03}"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo-imagenes", action="store_true")
    parser.add_argument("--recodificar", nargs="+", help="IDs de escenas a recodificar; reutiliza los otros clips existentes")
    args=parser.parse_args()
    scenes=read("docs/video-guion.json")
    if args.recodificar and set(args.recodificar)-{s["id"] for s in scenes}:
        parser.error("IDs de escena desconocidos")
    evidence={key:read(path) for key,path in {
        "preflight":"entrega/evidencias/preflight.json", "replica":"entrega/evidencias/qgis-replica.json",
        "permisos":"entrega/evidencias/qgis-permisos.json", "fallos":"db/outage-results.json",
        "dos_fases":"ops/recovery-results.json", "respaldos":"ops/backup-results.json",
        "pitr":"ops/pitr-results.json", "reincorporacion":"ops/rejoin-execution-results.json"}.items()}
    assert evidence["dos_fases"]["success"] and evidence["dos_fases"]["tests"]==9
    images=[render(scene, i+1, evidence) for i,scene in enumerate(scenes)]
    if args.solo_imagenes:
        return
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg y ffprobe deben estar en PATH")
    clips=[]
    chapters=[]
    subtitles=[]
    position=0
    for scene,img in zip(scenes,images):
        wav=OUT / "audio" / (scene["id"]+".wav")
        narrated=seconds(wav)
        duration=narrated+1
        clip=OUT / "video" / (scene["id"]+".mp4")
        if args.recodificar is None or scene["id"] in args.recodificar:
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-loop","1","-framerate","25","-i",str(img),
                        "-i",str(wav),"-af","apad=pad_dur=1","-t",str(duration),"-c:v","libx264","-preset","veryfast",
                        "-tune","stillimage","-crf","20","-pix_fmt","yuv420p","-c:a","aac","-b:a","160k","-ar","48000",str(clip)],check=True)
        elif not clip.exists():
            raise RuntimeError("Falta el clip que se desea reutilizar: "+str(clip))
        actual_duration=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration",
                               "-of","default=noprint_wrappers=1:nokey=1",str(clip)],text=True))
        chapters.append({"title":scene["titulo"],"start_seconds":round(position,3),"duration_seconds":round(actual_duration,3)})
        # Subtítulos en frases breves; intervalos repartidos dentro de cada voz.
        sentences=[s.strip().rstrip(".")+"." for s in scene["narracion"].split(". ")]
        weights=[len(s) for s in sentences]
        offset=position
        for sentence,weight in zip(sentences,weights):
            end=offset+narrated*weight/sum(weights)
            subtitles.append(f"{len(subtitles)+1}\n{stamp(offset)} --> {stamp(end)}\n{sentence}\n")
            offset=end
        position+=actual_duration
        clips.append(clip)
        print("Renderizado:",scene["id"],flush=True)
    if position>600:
        raise RuntimeError("El video excedería diez minutos")
    concat=OUT / "video" / "clips.txt"
    concat.write_text("\n".join("file '"+p.name+"'" for p in clips)+"\n",encoding="utf-8")
    video=OUT / "SIG-TEC-demostracion.mp4"
    srt=OUT / "SIG-TEC-demostracion.srt"
    srt.write_text("\n".join(subtitles),encoding="utf-8")
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),
                    "-i",str(srt),"-map","0:v:0","-map","0:a:0","-map","1:0","-c:v","copy","-c:a","copy",
                    "-c:s","mov_text","-metadata:s:s:0","language=spa","-movflags","+faststart",str(video)],check=True)
    probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(video)],text=True))
    duration=float(probe["format"]["duration"])
    assert 0<duration<=600
    assert any(s["codec_type"]=="audio" for s in probe["streams"])
    assert any(s.get("width")==1920 and s.get("height")==1080 for s in probe["streams"])
    (OUT / "narracion.txt").write_text("\n\n".join(s["titulo"]+"\n"+s["narracion"] for s in scenes),encoding="utf-8")
    report={"created_at_utc":datetime.now(timezone.utc).isoformat(),"duration_seconds":duration,
            "resolution":"1920x1080","voice":"Microsoft Sabina Desktop (es-MX), sintética",
            "sha256":hashlib.sha256(video.read_bytes()).hexdigest(),"bytes":video.stat().st_size,"chapters":chapters,
            "evidence_note":"Capturas reales de Desktop y consultas actuales; informes históricos del laboratorio rotulados con su fecha."}
    (OUT / "video-manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
