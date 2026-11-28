"""Comprueba el MP4 completo y extrae fotogramas para su revisión visual."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"entrega"
video=OUT/"SIG-TEC-demostracion.mp4"
probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(video)],text=True))
duration=float(probe["format"]["duration"])
if not 0<duration<=600:
    raise RuntimeError("El video debe durar como máximo diez minutos")
streams=probe["streams"]
if not any(s.get("width")==1920 and s.get("height")==1080 for s in streams):
    raise RuntimeError("Resolución inesperada")
if not {"video","audio","subtitle"}.issubset({s["codec_type"] for s in streams}):
    raise RuntimeError("Falta una pista")
full=subprocess.run(["ffmpeg","-hide_banner","-v","error","-i",str(video),"-f","null","-"],capture_output=True,text=True)
if full.returncode or full.stderr.strip():
    raise RuntimeError("La decodificación completa informó errores: "+full.stderr)
volume=subprocess.run(["ffmpeg","-hide_banner","-i",str(video),"-vn","-sn","-af","volumedetect","-f","null","-"],capture_output=True,text=True,check=True)
mean=float(re.search(r"mean_volume: ([-.0-9]+)",volume.stderr).group(1))
peak=float(re.search(r"max_volume: ([-.0-9]+)",volume.stderr).group(1))
if mean<=-40:
    raise RuntimeError("Audio ausente o demasiado bajo")
silence=subprocess.run(["ffmpeg","-hide_banner","-i",str(video),"-vn","-sn","-af","silencedetect=n=-45dB:d=8","-f","null","-"],capture_output=True,text=True,check=True)
if "silence_start" in silence.stderr:
    raise RuntimeError("Se detectó un silencio superior a ocho segundos")
manifest=json.loads((OUT/"video-manifest.json").read_text(encoding="utf-8"))
frames=[]
for index,chapter in enumerate(manifest["chapters"],1):
    frame=OUT/"video"/f"qa-capitulo-{index:02}.png"
    time=chapter["start_seconds"]+min(5,chapter["duration_seconds"]/2)
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",str(time),"-i",str(video),"-frames:v","1",str(frame)],check=True)
    frames.append(frame.relative_to(OUT).as_posix())
result={"video_sha256":hashlib.sha256(video.read_bytes()).hexdigest(),"duration_seconds":duration,
        "streams":[{k:s[k] for k in ("codec_type","codec_name","width","height","sample_rate","channels","duration") if k in s} for s in streams],
        "full_decode_without_errors":True,"mean_volume_db":mean,"max_volume_db":peak,
        "silence_over_8_seconds":False,"frames_for_visual_review":frames}
(OUT/"video-qc.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result,indent=2))
