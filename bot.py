import os
import asyncio
import time
import shutil
import logging
import subprocess
from threading import Thread

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from aria2p import API, Client as Aria2Client

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID", "18979569"))
API_HASH = os.getenv("API_HASH", "45db354387b8122bdf6c1b0beef93743")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8559651884:AAEUeSpqxunq9BE6I7cvw8ced7J0Oh3jk34")


DOWNLOAD_DIR = "downloads"

ARIA2_PORT = 6800
ARIA2_SECRET = "dxml"

STUCK_TIMEOUT = 300  # seconds

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ================= BOT =================
app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

aria2_client = Aria2Client(
    host="http://localhost",
    port=ARIA2_PORT,
    secret=ARIA2_SECRET
)
aria2 = API(aria2_client)

active = {}
last_active = {}

# ================= FLASK =================
flask_app = Flask(__name__)

@flask_app.route("/")
@flask_app.route("/health")
def health():
    return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

# ================= UTIL =================
def clean_startup():
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def ensure_aria2():
    try:
        aria2_client.get_global_stat()
        return
    except:
        pass

    subprocess.Popen([
        "aria2c",
        "--enable-rpc",
        "--rpc-listen-all=true",
        "--rpc-allow-origin-all",
        "--daemon=true",
        f"--rpc-secret={ARIA2_SECRET}",
        f"--rpc-listen-port={ARIA2_PORT}",
        f"--dir={DOWNLOAD_DIR}"
    ])
    time.sleep(3)

def human(n):
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {u}"
        n /= 1024
    return "∞"

def bar(p):
    f = int(p / 5)
    return "█" * f + "░" * (20 - f)

# ================= COMMANDS =================
@app.on_message(filters.command("start"))
async def start(_, m: Message):
    await m.reply_text(
        "📥 **Download Bot**\n\n"
        "`/l <link>` Start\n"
        "`/c <gid>` Cancel"
    )

@app.on_message(filters.command(["l", "leech"]))
async def leech(_, m: Message):
    if len(m.command) < 2 or not m.command[1].strip():
        return await m.reply_text("Usage: `/l <link>`")

    ensure_aria2()
    try:
        gid = aria2_client.add_uri([m.command[1]])
    except Exception as e:
        log.error(f"Failed to add URI: {e}")
        return await m.reply_text("❌ Invalid link or failed to start download")

    msg = await m.reply_text(f"📥 Task started\n🆔 `{gid}`")
    active[gid] = msg
    last_active[gid] = time.time()

    asyncio.create_task(progress_loop(gid))

@app.on_message(filters.command("c"))
async def cancel(_, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: `/c <gid>`")

    force_remove(m.command[1])
    await m.reply_text("❌ Cancelled")

# ================= FORCE REMOVE =================
def force_remove(gid):
    try:
        aria2.remove([gid], force=True)
    except:
        pass

    active.pop(gid, None)
    last_active.pop(gid, None)

    for r, _, f in os.walk(DOWNLOAD_DIR):
        for x in f:
            try:
                os.remove(os.path.join(r, x))
            except:
                pass

# ================= STUCK CLEANER =================
def stuck_cleaner():
    while True:
        now = time.time()
        for gid in list(last_active):
            if now - last_active[gid] > STUCK_TIMEOUT:
                force_remove(gid)
        time.sleep(30)

# ================= PROGRESS =================
async def progress_loop(gid):
    msg = active.get(gid)
    last_text = ""

    while True:
        try:
            d = aria2.get_download(gid)
        except:
            return

        if d.is_complete:
            await upload_file(gid, d.files[0].path)
            return

        if d.status in ["error", "removed"]:
            await msg.edit_text("❌ Failed")
            force_remove(gid)
            return

        last_active[gid] = time.time()

        name = os.path.basename(d.files[0].path) if d.files else "Unknown"
        total = d.total_length
        done = d.completed_length
        percent = d.progress
        speed = d.download_speed
        eta = int((total - done) / speed) if speed else 0

        new_text = (
            f"📥 **Downloading**\n"
            f"📄 `{name}`\n"
            f"📦 {human(total)}\n\n"
            f"`[{bar(percent)}] {percent:.2f}%`\n"
            f"📏 {human(done)} / {human(total)}\n"
            f"⚡ {human(speed)}/s\n"
            f"⏱ {time.strftime('%H:%M:%S', time.gmtime(eta))}"
        )

        if new_text != last_text:
            try:
                await msg.edit_text(new_text)
                last_text = new_text
            except Exception as e:
                log.error(f"Failed to edit message: {e}")

        await asyncio.sleep(3)

# ================= UPLOAD =================
async def upload_file(gid, path):
    msg = active.get(gid)
    if not os.path.exists(path):
        await msg.edit_text("❌ File not found after download")
        force_remove(gid)
        return

    total = os.path.getsize(path)
    start = time.time()
    name = os.path.basename(path)
    last_text = ""

    async def cb(cur, tot):
        speed = cur / (time.time() - start) if time.time() - start > 0 else 0
        percent = cur * 100 / tot if tot > 0 else 0
        eta = int((tot - cur) / speed) if speed > 0 else 0

        new_text = (
            f"📤 **Uploading**\n"
            f"📄 `{name}`\n"
            f"📦 {human(total)}\n\n"
            f"`[{bar(percent)}] {percent:.2f}%`\n"
            f"📏 {human(cur)} / {human(tot)}\n"
            f"⚡ {human(speed)}/s\n"
            f"⏱ {time.strftime('%H:%M:%S', time.gmtime(eta))}"
        )

        if new_text != last_text:
            try:
                await msg.edit_text(new_text)
                nonlocal last_text
                last_text = new_text
            except Exception as e:
                log.error(f"Failed to edit message during upload: {e}")

    try:
        await app.send_document(msg.chat.id, path, progress=cb)
    except Exception as e:
        log.error(f"Failed to upload file: {e}")
        await msg.edit_text("❌ Upload failed")
        force_remove(gid)
        return

    try:
        os.remove(path)
    except:
        pass

    await msg.edit_text("✅ Completed & cleaned")
    force_remove(gid)

# ================= MAIN =================
if __name__ == "__main__":
    clean_startup()
    ensure_aria2()

    Thread(target=run_flask, daemon=True).start()
    Thread(target=stuck_cleaner, daemon=True).start()

    app.run()
