import base64, hashlib, math, os, re, shutil, subprocess, uuid
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_file

BASE=Path(__file__).resolve().parent
RUNTIME=BASE/"runtime"; RUNTIME.mkdir(exist_ok=True)
app=Flask(__name__)
app.config["MAX_CONTENT_LENGTH"]=100*1024*1024
sessions={}
ALLOWED={".zip",".rar",".7z",".tar",".gz",".bz2",".xz"}
PATTERNS=[("PowerShell",r"\bpowershell(?:\.exe)?\b"),("CMD",r"\bcmd(?:\.exe)?\b"),
("WScript",r"\bwscript(?:\.exe)?\b"),("CScript",r"\bcscript(?:\.exe)?\b"),
("Rundll32",r"\brundll32(?:\.exe)?\b"),("Regsvr32",r"\bregsvr32(?:\.exe)?\b"),
("Scheduled task",r"\bschtasks(?:\.exe)?\b"),("Run key",r"currentversion[\\/]+run"),
("DownloadString",r"\bdownloadstring\b"),("Base64 decode",r"frombase64string"),
("CreateRemoteThread",r"CreateRemoteThread"),("VirtualAlloc",r"VirtualAlloc"),
("WriteProcessMemory",r"WriteProcessMemory")]
TEXT={".txt",".log",".json",".xml",".html",".htm",".css",".js",".ts",".jsx",".tsx",
".py",".ps1",".bat",".cmd",".c",".cc",".cpp",".h",".hpp",".cs",".java",".php",
".rb",".go",".rs",".sql",".yaml",".yml",".ini",".cfg",".md"}

def err(msg,status=400): return jsonify(ok=False,error=str(msg)),status
def sha(b): return hashlib.sha256(b).hexdigest()
def entropy(b):
    if not b:return 0
    c=[0]*256
    for x in b:c[x]+=1
    n=len(b)
    return -sum((v/n)*math.log2(v/n) for v in c if v)
def hits(b):
    s=b[:2000000].decode("utf-8","ignore")
    return [n for n,p in PATTERNS if re.search(p,s,re.I)]
def safe(p):
    p=str(p).replace("\\","/")
    q=Path(p)
    if q.is_absolute() or ".." in q.parts:return None
    return "/".join(x for x in q.parts if x not in ("","."))
def tool():
    return shutil.which("7zz") or shutil.which("7z")
def extract(src, out):
    """Try several archive engines so uncommon compression methods have fallbacks."""
    errors = []

    # 1) 7-Zip / 7zz: best general-purpose archive support.
    for command in ("7zz", "7z"):
        binary = shutil.which(command)
        if not binary:
            continue
        try:
            result = subprocess.run(
                [binary, "x", "-y", "-bd", "-aoa", f"-o{out}", str(src)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
            if result.returncode == 0:
                return
            errors.append(
                f"{command}: " +
                result.stderr.decode("utf-8", "replace")[-1200:]
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{command}: extraction timed out")

    # 2) bsdtar/libarchive fallback.
    bsdtar = shutil.which("bsdtar")
    if bsdtar:
        try:
            result = subprocess.run(
                [bsdtar, "-xf", str(src), "-C", str(out)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
            if result.returncode == 0:
                return
            errors.append(
                "bsdtar: " +
                result.stderr.decode("utf-8", "replace")[-1200:]
            )
        except subprocess.TimeoutExpired:
            errors.append("bsdtar: extraction timed out")

    # 3) Native unzip fallback for ZIP archives.
    if src.suffix.lower() == ".zip":
        unzip = shutil.which("unzip")
        if unzip:
            try:
                result = subprocess.run(
                    [unzip, "-o", "-q", str(src), "-d", str(out)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    check=False,
                )
                if result.returncode == 0:
                    return
                errors.append(
                    "unzip: " +
                    result.stderr.decode("utf-8", "replace")[-1200:]
                )
            except subprocess.TimeoutExpired:
                errors.append("unzip: extraction timed out")

    details = "\n\n".join(errors)
    raise RuntimeError(
        "Mazzi Lab could not extract this archive with the available "
        "archive engines.\n\n" + details
    )

def index(root):
    result=[]; total=0
    for p in root.rglob("*"):
        if not p.is_file():continue
        name=safe(p.relative_to(root).as_posix())
        if not name:continue
        size=p.stat().st_size
        if size>25*1024*1024:continue
        total+=size
        if total>250*1024*1024:raise RuntimeError("Expanded archive exceeds 250 MB.")
        b=p.read_bytes()
        result.append({"id":len(result),"name":name,"size":size,"sha256":sha(b),
                       "entropy":round(entropy(b),3),"hits":hits(b),
                       "text":Path(name).suffix.lower() in TEXT})
        if len(result)>=5000:raise RuntimeError("Archive contains more than 5,000 files.")
    return result

@app.errorhandler(413)
def too_large(e):return err("Archive is too large. Maximum is 100 MB.",413)
@app.errorhandler(404)
def not_found(e):return err("Endpoint not found.",404)
@app.errorhandler(500)
def server_error(e):app.logger.exception(e);return err("Server error. Check Render logs.",500)

@app.get("/")
def home():return send_file(BASE/"index.html")
@app.get("/style.css")
def css():return Response((BASE/"style.css").read_text(),mimetype="text/css")
@app.get("/health")
def health():return jsonify(ok=True,status="healthy")

@app.post("/api/upload")
def upload():
    f=request.files.get("file")
    if not f or not f.filename:return err("No archive selected.")
    ext=Path(f.filename).suffix.lower()
    if ext not in ALLOWED:return err("Supported: ZIP, RAR, 7Z, TAR, GZ, BZ2 and XZ.",415)
    sid=uuid.uuid4().hex; work=RUNTIME/sid; src=work/("sample"+ext); out=work/"files"
    try:
        work.mkdir();out.mkdir();f.save(src)
        if not src.exists() or src.stat().st_size==0:raise RuntimeError("Empty archive.")
        extract(src,out); files=index(out)
        if not files:raise RuntimeError("No readable files found.")
        sessions[sid]={"root":out,"files":files,"name":f.filename}
        src.unlink(missing_ok=True)
        return jsonify(ok=True,session=sid,name=f.filename,files=files)
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        app.logger.exception("Archive analysis failed")
        message = str(e)
        if len(message) > 2000:
            message = message[-2000:]
        return err(message)

@app.get("/api/file/<sid>/<int:i>")
def get_file(sid,i):
    s=sessions.get(sid)
    if not s:return err("Session expired.",404)
    if i<0 or i>=len(s["files"]):return err("File not found.",404)
    m=s["files"][i]; root=s["root"]; p=(root/m["name"]).resolve()
    if root.resolve() not in p.parents or not p.is_file():return err("File not found.",404)
    b=p.read_bytes(); view=b[:10*1024*1024]
    return jsonify(ok=True,name=m["name"],size=len(b),sha256=m["sha256"],
                   entropy=m["entropy"],hits=m["hits"],truncated=len(b)>len(view),
                   data=base64.b64encode(view).decode())

@app.post("/api/cleanup/<sid>")
def cleanup(sid):
    sessions.pop(sid,None);shutil.rmtree(RUNTIME/sid,ignore_errors=True)
    return jsonify(ok=True)

if __name__=="__main__":
    from waitress import serve
    serve(app,host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
