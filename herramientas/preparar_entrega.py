"""Captura evidencia de lectura o empaqueta el commit actual para entregar en Moodle."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"entrega"
NODES=("central","cartago","san_jose","san_carlos","alajuela","limon")


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT)


def capture():
    output=OUT/"evidencias"
    output.mkdir(parents=True,exist_ok=True)
    sql="""BEGIN READ ONLY;
SELECT json_build_object(
 'postgresql',current_setting('server_version'),'postgis',postgis_lib_version(),
 'edificios',(SELECT json_agg(json_build_object('id',id,'campus_id',campus_id,'nombre',nombre) ORDER BY campus_id) FROM sig.edificios),
 'layers',(SELECT json_agg(json_build_object('name',f_table_name,'type',type,'srid',srid) ORDER BY f_table_name) FROM geometry_columns WHERE f_table_schema='sig'),
 'subscriptions',(SELECT json_agg(json_build_object('name',s.subname,'enabled',s.subenabled,'tables',(SELECT count(*) FROM pg_subscription_rel r WHERE r.srsubid=s.oid),'ready',(SELECT count(*) FROM pg_subscription_rel r WHERE r.srsubid=s.oid AND r.srsubstate='r'))) FROM pg_subscription s),
 'slots',(SELECT json_agg(json_build_object('name',slot_name,'active',active)) FROM pg_replication_slots),
 'styles',(SELECT count(*) FROM public.layer_styles WHERE useasdefault),
 'prepared',(SELECT count(*) FROM pg_prepared_xacts));
COMMIT;"""
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"source_commit":git("rev-parse","HEAD").decode().strip(),
            "project":"iiiproyectobasesii","nodes":{}}
    for node in NODES:
        command=["docker","compose","-p",report["project"],"exec","-T",node,"psql","-XqAt","-v","ON_ERROR_STOP=1","-U","postgres","-d","sig_tec"]
        data=json.loads(subprocess.check_output([*command,"-c",sql],text=True,encoding="utf-8"))
        if len(data["layers"])!=8 or data["styles"]!=8 or data["prepared"]!=0:
            raise RuntimeError(node+": inventario inesperado")
        if not all(l["srid"]==8908 for l in data["layers"]):
            raise RuntimeError(node+": SRID inesperado")
        if not all(s["enabled"] and s["tables"]==s["ready"] for s in data["subscriptions"]):
            raise RuntimeError(node+": sincronización pendiente")
        if not all(s["active"] for s in data["slots"]):
            raise RuntimeError(node+": slot inactivo")
        report["nodes"][node]=data
        result=subprocess.run([*command,"-f","-"],input=(ROOT/"db/demo_lectura.sql").read_text(encoding="utf-8"),
                              text=True,encoding="utf-8",capture_output=True,check=True)
        (output/(node+"-lectura.txt")).write_text(result.stdout,encoding="utf-8")
    statuses=subprocess.check_output(["docker","compose","-p",report["project"],"ps","--format","json"],text=True)
    health=[json.loads(line) for line in statuses.splitlines() if line.strip()]
    if len(health)!=6 or not all(n["Health"]=="healthy" for n in health):
        raise RuntimeError("No están saludables los seis servicios")
    report["health"]=[{k:n[k] for k in ("Service","State","Health","Ports")} for n in health]
    (output/"preflight.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Captura de lectura completada en los seis nodos")


def allowed(name):
    path=PurePosixPath(name)
    normalized=name.casefold()
    if path.is_absolute() or ".." in path.parts:
        return False
    if re.search(r"(^|/)\.env($|\.)",normalized) and not normalized.endswith(".env.example"):
        return False
    if path.suffix.lower() in {".qgz",".qgs",".qgz~",".qgs~",".dump",".backup",".key",".p12",".db"}:
        return False
    if any(part in {".git",".venv","__pycache__","backups","wal","secrets",".runtime-state"} for part in path.parts):
        return False
    return not path.name.casefold().startswith("qgis-auth.db") and path.name.casefold() not in {".pgpass","pgpass.conf","pg_service.conf"}


def package():
    if git("status","--porcelain").strip():
        raise RuntimeError("Guardar los cambios en Git antes de empaquetar")
    video=OUT/"SIG-TEC-demostracion.mp4"
    manifest=json.loads((OUT/"video-manifest.json").read_text(encoding="utf-8"))
    if not 0<manifest["duration_seconds"]<=600:
        raise RuntimeError("Duración inválida")
    if hashlib.sha256(video.read_bytes()).hexdigest()!=manifest["sha256"]:
        raise RuntimeError("El video cambió después de validarlo")
    qc=json.loads((OUT/"video-qc.json").read_text(encoding="utf-8"))
    if qc["video_sha256"]!=manifest["sha256"] or not qc["full_decode_without_errors"]:
        raise RuntimeError("El control técnico no corresponde al video actual")
    commit=git("rev-parse","HEAD").decode().strip()
    archive=io.BytesIO(git("archive","--format=zip","HEAD"))
    destination=OUT/"SIG-TEC-codigo-documentacion.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(destination,"w",zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if not allowed(item.filename):
                raise RuntimeError("Archivo privado o local en el commit: "+item.filename)
            target.writestr("SIG-TEC/"+item.filename,source.read(item.filename))
        for path in sorted((OUT/"evidencias").glob("*")):
            if path.is_file() and path.suffix in {".json",".png",".txt"}:
                target.write(path,"SIG-TEC/entrega/evidencias/"+path.name)
        for name in ("video-manifest.json","video-qc.json","SIG-TEC-demostracion.srt","narracion.txt"):
            target.write(OUT/name,"SIG-TEC/entrega/"+name)
        target.writestr("SIG-TEC/ENTREGA.txt",f"SIG-TEC - Joseph, Joyce y Armando\nCommit: {commit}\n"
                        f"Video separado: SIG-TEC-demostracion.mp4 ({manifest['duration_seconds']:.2f} segundos)\n"
                        "Inicio: README.md, db/INTEGRACION.md y docs/entrega.md\n"
                        "El ZIP no contiene contraseñas, proyectos locales QGIS ni respaldos.\n"
                        "Evidencia actual: entrega/evidencias. Evidencia histórica: informes JSON de ops/ y db/.\n")
    with zipfile.ZipFile(destination) as archive:
        bad=archive.testzip()
        if bad:
            raise RuntimeError("Entrada ZIP dañada: "+bad)
        if any(not allowed(n.removeprefix("SIG-TEC/")) for n in archive.namelist()):
            raise RuntimeError("El ZIP contiene una ruta excluida")
    output={"created_at_utc":datetime.now(timezone.utc).isoformat(),"source_commit":commit,
            "files":{p.name:{"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in (destination,video,OUT/"SIG-TEC-demostracion.srt")}}
    (OUT/"entrega-manifest.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"SHA256SUMS.txt").write_text("\n".join(v["sha256"]+"  "+k for k,v in output["files"].items())+"\n",encoding="utf-8")
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion",choices=("capturar","empaquetar"))
    options=parser.parse_args()
    capture() if options.accion=="capturar" else package()
