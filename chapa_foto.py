import os
import sqlite3
import base64
import io
from datetime import datetime

from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    url_for,
    send_from_directory,
)

from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import imagehash

# ---------------- CONFIG BÁSICA ---------------- #

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "chapas.db")
IMG_DIR = os.path.join(BASE_DIR, "chapas")

os.makedirs(IMG_DIR, exist_ok=True)

app = Flask(__name__)


# ---------------- BANCO DE DADOS ---------------- #

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chapas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL,
            descricao TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            image_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chapa_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapa_id INTEGER NOT NULL,
            image_hash TEXT NOT NULL,
            FOREIGN KEY (chapa_id) REFERENCES chapas(id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ---------------- FUNÇÕES DE IMAGEM ---------------- #

def preprocess_image_for_save(img: Image.Image) -> Image.Image:
    # mantém cor, só reduz tamanho e melhora leve brilho/contraste
    img = img.convert("RGB")

    max_side = 800
    w, h = img.size
    scale = min(max_side / max(w, h), 1.0)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))

    return img


def preprocess_image_for_hash(img: Image.Image) -> Image.Image:
    # foca no miolo da chapa (cor + textura), ignora bordas/sombra
    img = img.convert("RGB")
    w, h = img.size

    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    img = img.resize((400, 400), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.10)

    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img, cutoff=2)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))

    return img


def decode_data_url_to_image(data_url: str) -> Image.Image:
    if "," in data_url:
        _, b64data = data_url.split(",", 1)
    else:
        b64data = data_url
    raw = base64.b64decode(b64data)
    return Image.open(io.BytesIO(raw))


def save_image(pil_img: Image.Image) -> str:
    filename = f"chapa_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    path = os.path.join(IMG_DIR, filename)
    pil_img.save(path, "JPEG", quality=95)
    return filename


# ---------------- HTML (TUDO INLINE) ---------------- #

BASE_HTML_HEAD = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            background: #f3f3f3;
            color: #222;
        }
        header {
            background: #0b3d2e;
            color: #fff;
            padding: 10px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        header h1 {
            font-size: 1rem;
            margin: 0;
        }
        nav a {
            color: #fff;
            text-decoration: none;
            margin-left: 12px;
            font-size: 0.9rem;
        }
        nav a:hover { text-decoration: underline; }
        main { padding: 16px; }

        .home-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }
        .card {
            background: #fff;
            border-radius: 10px;
            padding: 14px;
            text-decoration: none;
            color: inherit;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        }
        .card h2 {
            margin: 0 0 6px 0;
            font-size: 1rem;
        }
        .card p {
            margin: 0;
            font-size: 0.85rem;
            color: #555;
        }

        video {
            width: 100%;
            max-width: 420px;
            border-radius: 10px;
            background: #000;
        }
        canvas { display:none; }

        .preview img {
            max-width: 260px;
            border-radius: 10px;
            margin-top: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }

        button, .btn-link {
            padding: 8px 14px;
            border-radius: 6px;
            border: none;
            background: #1e8b4d;
            color: #fff;
            font-size: 0.9rem;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        button:hover, .btn-link:hover { opacity: .9; }
        button:disabled { opacity: .5; cursor: default; }

        .btn-row {
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        form {
            margin-top: 12px;
            max-width: 360px;
            background: #fff;
            padding: 12px;
            border-radius: 10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        }
        form input {
            width: 100%;
            padding: 6px 8px;
            margin-bottom: 8px;
            border-radius: 6px;
            border: 1px solid #ccc;
            font-size: 0.9rem;
        }
        form label {
            font-size: 0.8rem;
        }

        .msg { margin-top: 8px; font-size: 0.85rem; }
        .msg.error { color:#b00020; }
        .msg.success { color:#1e8b4d; }

        table {
            width: 100%;
            border-collapse: collapse;
            background: #fff;
            border-radius: 10px;
            overflow: hidden;
        }
        th, td {
            padding: 8px;
            border-bottom: 1px solid #eee;
            font-size: 0.85rem;
        }
        th {
            background: #0b3d2e;
            color: #fff;
            text-align: left;
        }
        tr:nth-child(even) { background: #fafafa; }

        .resultado {
            margin-top: 12px;
            background:#fff;
            padding: 10px;
            border-radius:10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            font-size: 0.9rem;
        }
        .resultado img {
            max-width:220px;
            border-radius:8px;
            margin-top:6px;
        }
    </style>
</head>
<body>
<header>
    <h1>Projeto Chapa MDF</h1>
    <nav>
        <a href="{{ url_for('index') }}">Home</a>
        <a href="{{ url_for('cadastro_page') }}">Cadastrar</a>
        <a href="{{ url_for('consulta_page') }}">Consultar</a>
        <a href="{{ url_for('cadastrados_page') }}">Cadastrados</a>
    </nav>
</header>
<main>
"""

BASE_HTML_FOOT = """
</main>
</body>
</html>
"""

HOME_HTML = (
    BASE_HTML_HEAD
    + """
<h2>Menu</h2>
<div class="home-cards">
    <a class="card" href="{{ url_for('cadastro_page') }}">
        <h2>Cadastrar Chapa</h2>
        <p>Gravar vídeo de 5s em vários ângulos e salvar com SKU e descrição.</p>
    </a>
    <a class="card" href="{{ url_for('consulta_page') }}">
        <h2>Consultar Chapa</h2>
        <p>Tirar uma foto da chapa e buscar no cadastro.</p>
    </a>
    <a class="card" href="{{ url_for('cadastrados_page') }}">
        <h2>Chapas Cadastradas</h2>
        <p>Ver todas as chapas registradas.</p>
    </a>
</div>
"""
    + BASE_HTML_FOOT
)

CADASTRO_HTML = (
    BASE_HTML_HEAD
    + """
<h2>Cadastrar Chapa MDF (vídeo 5s)</h2>

<video id="videoCadastro" autoplay playsinline></video>
<canvas id="canvasCadastro"></canvas>

<div class="btn-row">
    <button id="btnGravarCadastro">Gravar vídeo 5s</button>
    <button id="btnLuzCadastro" type="button">Luz On/Off</button>
</div>

<div id="previewCadastro" class="preview" style="display:none;">
    <h3>Pré-visualização (frame do vídeo)</h3>
    <img id="imgPreviewCadastro" alt="Frame da chapa">
</div>

<form id="formCadastro" style="display:none;">
    <label for="sku">SKU</label>
    <input id="sku" required>
    <label for="descricao">Descrição</label>
    <input id="descricao" required>
    <div class="btn-row">
        <button type="submit">Salvar</button>
        <button type="button" id="btnCancelarCadastro">Cancelar</button>
    </div>
</form>

<div id="msgCadastro" class="msg"></div>

<script>
let streamCadastro = null;
let framesCadastro = [];
let torchOnCadastro = false;
let torchSuportadaCadastro = true;

async function initCameraCadastro() {
    try {
        streamCadastro = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
            audio: false
        });
        const video = document.getElementById("videoCadastro");
        video.srcObject = streamCadastro;
    } catch (err) {
        const msg = document.getElementById("msgCadastro");
        msg.textContent = "Erro ao acessar câmera: " + err.message;
        msg.className = "msg error";
    }
}

async function toggleTorchCadastro() {
    if (!streamCadastro || !torchSuportadaCadastro) return;
    const tracks = streamCadastro.getVideoTracks();
    if (!tracks || !tracks.length) return;
    const track = tracks[0];

    try {
        const novoEstado = !torchOnCadastro;
        await track.applyConstraints({ advanced: [{ torch: novoEstado }] });
        torchOnCadastro = novoEstado;
    } catch (e) {
        console.log("Erro torch:", e);
        alert("Lanterna não suportada neste dispositivo.");
        torchSuportadaCadastro = false;
    }
}

function gravarVideoCadastro() {
    const video = document.getElementById("videoCadastro");
    const canvas = document.getElementById("canvasCadastro");
    const msg = document.getElementById("msgCadastro");
    const previewDiv = document.getElementById("previewCadastro");
    const imgPreview = document.getElementById("imgPreviewCadastro");
    const form = document.getElementById("formCadastro");

    if (!video.videoWidth) {
        msg.textContent = "Vídeo não está pronto, aguarde um pouco e tente de novo.";
        msg.className = "msg error";
        return;
    }

    framesCadastro = [];
    msg.textContent = "Gravando 5 segundos... mova o celular em volta da chapa.";
    msg.className = "msg";

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");

    const durationMs = 5000;
    const intervalMs = 400; // ~12 frames
    let elapsed = 0;

    function captureFrame() {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        framesCadastro.push(dataUrl);
    }

    captureFrame();

    const intervalId = setInterval(() => {
        elapsed += intervalMs;
        captureFrame();
        if (elapsed >= durationMs) {
            clearInterval(intervalId);
            if (framesCadastro.length > 0) {
                const mid = Math.floor(framesCadastro.length / 2);
                imgPreview.src = framesCadastro[mid];
                previewDiv.style.display = "block";
                form.style.display = "block";
                msg.textContent = "Vídeo capturado. Preencha os dados e salve.";
                msg.className = "msg success";
            } else {
                msg.textContent = "Não foi possível capturar o vídeo.";
                msg.className = "msg error";
            }
        }
    }, intervalMs);
}

document.addEventListener("DOMContentLoaded", () => {
    initCameraCadastro();

    const btnGravar = document.getElementById("btnGravarCadastro");
    const btnCancelar = document.getElementById("btnCancelarCadastro");
    const btnLuz = document.getElementById("btnLuzCadastro");
    const form = document.getElementById("formCadastro");
    const msg = document.getElementById("msgCadastro");

    btnGravar.addEventListener("click", () => {
        gravarVideoCadastro();
        msg.textContent = "";
        msg.className = "msg";
    });

    btnCancelar.addEventListener("click", () => {
        form.reset();
        form.style.display = "none";
        document.getElementById("previewCadastro").style.display = "none";
        framesCadastro = [];
        msg.textContent = "Cadastro cancelado.";
        msg.className = "msg";
    });

    btnLuz.addEventListener("click", () => {
        toggleTorchCadastro();
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!framesCadastro.length) {
            msg.textContent = "Grave o vídeo de 5s antes de salvar.";
            msg.className = "msg error";
            return;
        }
        const sku = document.getElementById("sku").value.trim();
        const descricao = document.getElementById("descricao").value.trim();
        if (!sku || !descricao) {
            msg.textContent = "Preencha SKU e Descrição.";
            msg.className = "msg error";
            return;
        }
        const payload = { frames: framesCadastro, sku, descricao };
        try {
            const resp = await fetch("{{ url_for('api_cadastro') }}", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            if (data.status === "ok") {
                msg.textContent = "Chapa cadastrada com sucesso.";
                msg.className = "msg success";
                form.reset();
                form.style.display = "none";
                document.getElementById("previewCadastro").style.display = "none";
                framesCadastro = [];
            } else {
                msg.textContent = data.message || "Erro ao cadastrar.";
                msg.className = "msg error";
            }
        } catch (err) {
            msg.textContent = "Erro de comunicação com o servidor.";
            msg.className = "msg error";
        }
    });
});
</script>
"""
    + BASE_HTML_FOOT
)

CONSULTA_HTML = (
    BASE_HTML_HEAD
    + """
<h2>Consultar Chapa MDF (foto única)</h2>

<video id="videoConsulta" autoplay playsinline></video>
<canvas id="canvasConsulta"></canvas>

<div class="btn-row">
    <button id="btnCapturarConsulta">Capturar e Buscar</button>
    <button id="btnLuzConsulta" type="button">Luz On/Off</button>
</div>

<div id="resultadoConsulta" class="resultado" style="display:none;"></div>

<div id="acaoCadastrar" class="resultado" style="display:none;">
    <p>Chapa não identificada. Deseja cadastrar?</p>
    <div class="btn-row">
        <a href="{{ url_for('cadastro_page') }}" class="btn-link">Sim, cadastrar</a>
        <button id="btnNaoCadastrar">Não</button>
    </div>
</div>

<script>
let streamConsulta = null;
let torchOnConsulta = false;
let torchSuportadaConsulta = true;

async function initCameraConsulta() {
    try {
        streamConsulta = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
            audio: false
        });
        const video = document.getElementById("videoConsulta");
        video.srcObject = streamConsulta;
    } catch (err) {
        const res = document.getElementById("resultadoConsulta");
        res.style.display = "block";
        res.textContent = "Erro ao acessar câmera: " + err.message;
    }
}

async function toggleTorchConsulta() {
    if (!streamConsulta || !torchSuportadaConsulta) return;
    const tracks = streamConsulta.getVideoTracks();
    if (!tracks || !tracks.length) return;
    const track = tracks[0];

    try {
        const novoEstado = !torchOnConsulta;
        await track.applyConstraints({ advanced: [{ torch: novoEstado }] });
        torchOnConsulta = novoEstado;
    } catch (e) {
        console.log("Erro torch:", e);
        alert("Lanterna não suportada neste dispositivo.");
        torchSuportadaConsulta = false;
    }
}

function capturarDataUrlConsulta() {
    const video = document.getElementById("videoConsulta");
    const canvas = document.getElementById("canvasConsulta");

    if (!video.videoWidth) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    return canvas.toDataURL("image/jpeg", 0.95);
}

document.addEventListener("DOMContentLoaded", () => {
    initCameraConsulta();

    const btnCapturar = document.getElementById("btnCapturarConsulta");
    const resultadoDiv = document.getElementById("resultadoConsulta");
    const acaoCadastrarDiv = document.getElementById("acaoCadastrar");
    const btnNaoCadastrar = document.getElementById("btnNaoCadastrar");
    const btnLuz = document.getElementById("btnLuzConsulta");

    btnCapturar.addEventListener("click", async () => {
        const dataUrl = capturarDataUrlConsulta();
        if (!dataUrl) return;

        resultadoDiv.style.display = "block";
        resultadoDiv.textContent = "Processando imagem...";
        acaoCadastrarDiv.style.display = "none";

        try {
            const resp = await fetch("{{ url_for('api_consulta') }}", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ image: dataUrl })
            });
            const data = await resp.json();

            if (data.status === "ok") {
                resultadoDiv.innerHTML = `
                    <strong>Chapa encontrada:</strong><br>
                    SKU: ${data.sku}<br>
                    Descrição: ${data.descricao}<br>
                    Distância: ${data.distancia}<br>
                    <img src="${data.image_url}" alt="Chapa cadastrada">
                `;
            } else if (data.status === "not_found") {
                resultadoDiv.textContent = "Chapa não identificada.";
                acaoCadastrarDiv.style.display = "block";
            } else {
                resultadoDiv.textContent = data.message || "Erro na consulta.";
            }
        } catch (err) {
            resultadoDiv.textContent = "Erro de comunicação com o servidor.";
        }
    });

    btnNaoCadastrar.addEventListener("click", () => {
        acaoCadastrarDiv.style.display = "none";
    });

    btnLuz.addEventListener("click", () => {
        toggleTorchConsulta();
    });
});
</script>
"""
    + BASE_HTML_FOOT
)

CADASTRADOS_HTML = (
    BASE_HTML_HEAD
    + """
<h2>Chapas Cadastradas</h2>

<table>
    <thead>
        <tr>
            <th>ID</th>
            <th>SKU</th>
            <th>Descrição</th>
            <th>Data/Hora</th>
            <th>Imagem</th>
        </tr>
    </thead>
    <tbody>
    {% for c in chapas %}
        <tr>
            <td>{{ c.id }}</td>
            <td>{{ c.sku }}</td>
            <td>{{ c.descricao }}</td>
            <td>{{ c.created_at }}</td>
            <td>
                <a href="{{ url_for('chapa_image', filename=c.image_filename) }}" target="_blank">
                    Ver
                </a>
            </td>
        </tr>
    {% else %}
        <tr><td colspan="5">Nenhuma chapa cadastrada ainda.</td></tr>
    {% endfor %}
    </tbody>
</table>
"""
    + BASE_HTML_FOOT
)


# ---------------- ROTAS PÁGINAS ---------------- #

@app.route("/")
def index():
    return render_template_string(HOME_HTML, title="Home")


@app.route("/cadastro")
def cadastro_page():
    return render_template_string(CADASTRO_HTML, title="Cadastro")


@app.route("/consulta")
def consulta_page():
    return render_template_string(CONSULTA_HTML, title="Consulta")


@app.route("/cadastrados")
def cadastrados_page():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM chapas ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return render_template_string(CADASTRADOS_HTML, title="Cadastrados", chapas=rows)


@app.route("/chapas/<path:filename>")
def chapa_image(filename):
    return send_from_directory(IMG_DIR, filename)


# ---------------- ROTAS API ---------------- #

@app.route("/api/cadastro", methods=["POST"])
def api_cadastro():
    data = request.get_json(force=True)
    frames = data.get("frames")
    sku = data.get("sku", "").strip()
    descricao = data.get("descricao", "").strip()

    if not frames or not isinstance(frames, list) or not sku or not descricao:
        return jsonify({"status": "error", "message": "Dados incompletos."}), 400

    # usa o frame do meio como imagem de referência pra salvar
    mid_index = len(frames) // 2
    frame_preview = frames[mid_index]

    try:
        pil_preview = decode_data_url_to_image(frame_preview)
    except Exception:
        return jsonify({"status": "error", "message": "Erro ao ler frame do vídeo."}), 400

    img_save = preprocess_image_for_save(pil_preview)
    filename = save_image(img_save)

    # gera hash de todos os frames para textura/cor
    hashes = []
    for f in frames:
        try:
            pil = decode_data_url_to_image(f)
            pre = preprocess_image_for_hash(pil)
            h = imagehash.phash(pre)
            hashes.append(str(h))
        except Exception:
            continue

    if not hashes:
        return jsonify({"status": "error", "message": "Não foi possível gerar hashes do vídeo."}), 400

    # também guarda um hash "principal" na tabela chapas (por compatibilidade)
    img_hash_principal = hashes[0]
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chapas (sku, descricao, image_filename, image_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sku, descricao, filename, img_hash_principal, created_at),
    )
    chapa_id = cur.lastrowid

    for h in hashes:
        cur.execute(
            "INSERT INTO chapa_hashes (chapa_id, image_hash) VALUES (?, ?)",
            (chapa_id, h),
        )

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


@app.route("/api/consulta", methods=["POST"])
def api_consulta():
    data = request.get_json(force=True)
    image_data = data.get("image")

    if not image_data:
        return jsonify({"status": "error", "message": "Imagem não recebida."}), 400

    pil_img = decode_data_url_to_image(image_data)
    pre = preprocess_image_for_hash(pil_img)
    query_hash = imagehash.phash(pre)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id AS chapa_id,
               c.sku,
               c.descricao,
               c.image_filename,
               c.created_at,
               h.image_hash AS frame_hash
        FROM chapas c
        JOIN chapa_hashes h ON h.chapa_id = c.id
        """
    )
    rows = cur.fetchall()
    conn.close()

    melhor = None
    melhor_dist = None

    for row in rows:
        try:
            h_db = imagehash.hex_to_hash(row["frame_hash"])
        except Exception:
            continue
        dist = query_hash - h_db
        if melhor is None or dist < melhor_dist:
            melhor = row
            melhor_dist = dist

    # mais tolerante, já que temos vários frames por chapa
    LIMIAR = 24

    if melhor is None or melhor_dist is None or melhor_dist > LIMIAR:
        return jsonify({"status": "not_found"})

    image_url = url_for("chapa_image", filename=melhor["image_filename"])

    return jsonify(
        {
            "status": "ok",
            "sku": melhor["sku"],
            "descricao": melhor["descricao"],
            "image_url": image_url,
            "id": melhor["chapa_id"],
            "distancia": int(melhor_dist),
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
