#!/usr/bin/env python3
# ==============================================================================
# ALIJAYA NET - GenieACS AI Telegram Agent (Full Multi-Tab & Operations Mod)
# Pengembang: ALIJAYA NET (WhatsApp: 081947215703)
# ==============================================================================

import os
import sys
import shutil
import re
import time
from datetime import datetime, timedelta, timezone
import json
import logging
import subprocess
import socket
import requests
import pymongo
import hmac
import hashlib
import base64
import secrets
import random
from urllib.parse import quote, urlparse, parse_qs
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer as DefaultHTTPServer
except ImportError:
    from http.server import HTTPServer as DefaultHTTPServer
try:
    from http.server import ThreadingHTTPServer as DefaultHTTPServer
except ImportError:
    from http.server import HTTPServer as DefaultHTTPServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("GenieACSAgent")

_CURRENT_MONGO_CLIENT = None
_RESOLVED_MONGO_URI = None

def resolve_mongo_uri():
    global _RESOLVED_MONGO_URI
    if _RESOLVED_MONGO_URI:
        return _RESOLVED_MONGO_URI

    candidates = []
    if os.environ.get("GENIEACS_MONGODB_CONNECTION_URL"):
        candidates.append(os.environ.get("GENIEACS_MONGODB_CONNECTION_URL"))

    for env_path in ["/opt/genieacs/genieacs.env", "/etc/genieacs.env", "/etc/default/genieacs"]:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GENIEACS_MONGODB_CONNECTION_URL="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and val not in candidates:
                                candidates.append(val)
            except Exception:
                pass

    for default_uri in [
        "mongodb://genie:genie@127.0.0.1:27017/genieacs",
        "mongodb://genie:genie@127.0.0.1/genieacs",
        "mongodb://127.0.0.1:27017/genieacs",
        "mongodb://127.0.0.1/genieacs",
        "mongodb://localhost:27017/genieacs"
    ]:
        if default_uri not in candidates:
            candidates.append(default_uri)

    for uri in candidates:
        try:
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=1500)
            db_name = "genieacs"
            try:
                p = client.get_default_database()
                if p is not None:
                    db_name = p.name
            except Exception:
                pass
            client[db_name].command("ping")
            # Verify actual database read access (ping alone does NOT verify MongoDB auth!)
            client[db_name].devices.find_one({}, {"_id": 1})
            _RESOLVED_MONGO_URI = uri
            logger.info(f"MongoDB connected successfully via: {uri.split('@')[-1] if '@' in uri else uri}")
            return uri
        except Exception:
            continue

    _RESOLVED_MONGO_URI = candidates[0] if candidates else "mongodb://genie:genie@127.0.0.1:27017/genieacs"
    return _RESOLVED_MONGO_URI

MONGO_URI = resolve_mongo_uri()
NBI_URL = "http://127.0.0.1:7557"

USER_STATES = {}
SEEN_DEVICES = set()
NOTIFIED_DROPS = {} # device_id -> timestamp

def get_db():
    global _CURRENT_MONGO_CLIENT, _RESOLVED_MONGO_URI
    try:
        if _CURRENT_MONGO_CLIENT is not None:
            try:
                db_name = "genieacs"
                try:
                    p = _CURRENT_MONGO_CLIENT.get_default_database()
                    if p is not None:
                        db_name = p.name
                except Exception:
                    pass
                _CURRENT_MONGO_CLIENT[db_name].command("ping")
                _CURRENT_MONGO_CLIENT[db_name].devices.find_one({}, {"_id": 1})
                return _CURRENT_MONGO_CLIENT[db_name]
            except Exception:
                _CURRENT_MONGO_CLIENT = None

        uri = resolve_mongo_uri()
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        db_name = "genieacs"
        try:
            p = client.get_default_database()
            if p is not None:
                db_name = p.name
        except Exception:
            pass
        client[db_name].command("ping")
        client[db_name].devices.find_one({}, {"_id": 1})
        _CURRENT_MONGO_CLIENT = client
        return client[db_name]
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        _RESOLVED_MONGO_URI = None
        _CURRENT_MONGO_CLIENT = None
        return None

def get_config():
    global _CURRENT_MONGO_CLIENT, _RESOLVED_MONGO_URI
    try:
        db = get_db()
        if db is None:
            return {}
        cfgs = db.config.find({"_id": {"$regex": "^agent\\."}})
        res = {}
        for c in cfgs:
            val = str(c.get("value", "")).strip()
            while len(val) >= 2 and ((val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"'))):
                val = val[1:-1].strip()
            res[c["_id"]] = val.strip()
        return res
    except Exception as e:
        logger.error(f"Failed to fetch config from MongoDB: {e}")
        _CURRENT_MONGO_CLIENT = None
        _RESOLVED_MONGO_URI = None
        return {}

BRAND_NAME = "ALIJAYA NET"
BRAND_PHONE = "081947215703"

def update_branding(cfgs):
    global BRAND_NAME, BRAND_PHONE
    b_name = cfgs.get("agent.brand.name", "").strip()
    b_phone = cfgs.get("agent.brand.phone", "").strip()
    BRAND_NAME = b_name if b_name else "ALIJAYA NET"
    BRAND_PHONE = b_phone if b_phone else "081947215703"

def is_valid_token(val):
    if not val:
        return False
    if "MASUKKAN_" in val:
        return False
    return True

def parse_admin_chat_ids(val):
    if not val or not is_valid_token(val):
        return []
    cleaned = val.replace(";", ",").replace("\n", ",")
    return [x.strip() for x in cleaned.split(",") if x.strip()]

def is_authorized(sender_id, admin_ids):
    if not admin_ids:
        return False
    return str(sender_id) in admin_ids

# ==============================================================================
# KEYBOARD MARKUPS
# ==============================================================================

def get_main_menu_keyboard():
    return {
        "keyboard": [
            [{"text": "🔍 Cek Modem"}, {"text": "⚠️ Cek Redaman Kritis"}],
            [{"text": "👥 Daftar Klien WiFi"}, {"text": "🆕 Modem Belum Setting"}],
            [{"text": "🌐 Tambah / Set WAN"}, {"text": "🔄 Reboot Modem"}],
            [{"text": "📶 Ubah WiFi / Sandi"}, {"text": "📊 Status Server STB"}],
            [{"text": "❓ Bantuan / Help"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def get_device_inline_keyboard(pppoe_user, dev_id=None, wifi_enabled=True):
    target = pppoe_user if pppoe_user else dev_id
    wifi_toggle_text = "🚫 Matikan WiFi" if wifi_enabled else "📶 Hidupkan WiFi"
    wifi_toggle_action = f"wifioff:{target}" if wifi_enabled else f"wifion:{target}"
    
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Reboot Modem", "callback_data": f"reboot:{target}"},
                {"text": "⚡ Refresh Data", "callback_data": f"refresh:{target}"}
            ],
            [
                {"text": "👥 Cek Klien HP", "callback_data": f"klien:{target}"},
                {"text": "🌐 Set WAN PPPoE", "callback_data": f"prompt_wan:{target}"}
            ],
            [
                {"text": "📶 Ganti SSID", "callback_data": f"prompt_ssid:{target}"},
                {"text": "🔑 Ganti Sandi", "callback_data": f"prompt_pass:{target}"}
            ],
            [
                {"text": wifi_toggle_text, "callback_data": wifi_toggle_action},
                {"text": "⚠️ Factory Reset", "callback_data": f"prompt_fr:{target}"}
            ]
        ]
    }

# ==============================================================================
# GENIEACS CORE OPERATIONS
# ==============================================================================


def normalize_phone(phone_str):
    if not phone_str:
        return ""
    digits = re.sub(r"\D", "", str(phone_str))
    if digits.startswith("62"):
        return "0" + digits[2:]
    return digits

def get_phone_variations(phone_str):
    if not phone_str:
        return []
    digits = re.sub(r"\D", "", str(phone_str))
    if len(digits) < 8:
        return [str(phone_str).strip()]
    if digits.startswith("62"):
        local = "0" + digits[2:]
        intl = digits
    elif digits.startswith("0"):
        local = digits
        intl = "62" + digits[1:]
    else:
        local = "0" + digits
        intl = "62" + digits
    return list(set([local, intl, f"+{intl}", f"wa:{local}", f"wa:{intl}"]))

def find_device_by_phone(phone_str):
    if not phone_str:
        return None
    db = get_db()
    if db is None:
        return None
    variations = get_phone_variations(phone_str)
    digits = re.sub(r"\D", "", str(phone_str))
    local = "0" + digits[2:] if digits.startswith("62") else digits
    intl = "62" + digits[1:] if digits.startswith("0") else digits
    plain = digits[1:] if digits.startswith("0") else (digits[2:] if digits.startswith("62") else digits)

    # 1. Prioritas Utama: Cek di db.device_locations (Data No. HP Pelanggan dari Peta GenieACS)
    loc_filters = [
        {"phone": {"$in": variations}},
        {"phone": local},
        {"phone": intl},
        {"phone": digits}
    ]
    if len(plain) >= 7:
        loc_filters.append({"phone": {"$regex": re.escape(plain)}})

    try:
        loc = db.device_locations.find_one({"$or": loc_filters})
        if loc and loc.get("_id"):
            dev = find_device(loc.get("_id"))
            if dev:
                if loc.get("name"):
                    dev["_custom_customer_name"] = loc.get("name")
                return dev
    except Exception as e:
        logger.warning(f"Error querying device_locations by phone: {e}")

    # 2. Prioritas Kedua: Cek tags pada db.devices
    dev = db.devices.find_one({
        "$or": [
            {"_tags": {"$in": variations}},
            {"tags": {"$in": variations}},
            {"_tags": {"$regex": local}},
            {"tags": {"$regex": local}}
        ]
    })
    return dev

def add_device_tag(dev_id, tag_str):
    clean_tag = tag_str.strip()
    db = get_db()
    if db is not None:
        try:
            db.devices.update_one({"_id": dev_id}, {"$addToSet": {"_tags": clean_tag}})
        except Exception:
            pass
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tags/{quote(clean_tag)}"
        r = requests.post(url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def remove_device_tag(dev_id, tag_str):
    clean_tag = tag_str.strip()
    db = get_db()
    if db is not None:
        try:
            db.devices.update_one({"_id": dev_id}, {"$pull": {"_tags": clean_tag}})
        except Exception:
            pass
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tags/{quote(clean_tag)}"
        r = requests.delete(url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def get_device_pppoe_username(dev):
    if not dev:
        return "Unknown"
    vp = dev.get("VirtualParameters", {})
    pppoe = vp.get("pppoeUsername", {}).get("_value")
    if pppoe and pppoe not in ["0", "undefined", "null"]:
        return str(pppoe).strip()
    wandev = dev.get("InternetGatewayDevice", {}).get("WANDevice", {})
    for wk in wandev:
        if wk.startswith("_"): continue
        wcds = wandev[wk].get("WANConnectionDevice", {})
        for ck in wcds:
            if ck.startswith("_"): continue
            ppps = wcds[ck].get("WANPPPConnection", {})
            for pk in ppps:
                if pk.startswith("_"): continue
                u = ppps[pk].get("Username", {}).get("_value")
                if u:
                    return str(u).strip()
    return dev.get("_deviceId", {}).get("_SerialNumber") or dev.get("_id", "Unknown")

def get_datetime_diff_seconds(dt):
    if not dt:
        return 999999999
    try:
        from datetime import timezone
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            dt_ts = dt.timestamp()
        else:
            dt_ts = dt.replace(tzinfo=timezone.utc).timestamp()
        return max(0, time.time() - dt_ts)
    except Exception:
        return 999999999

def get_customer_friendly_summary(dev):
    if not dev:
        return "❌ Perangkat Anda tidak ditemukan."
    vp = dev.get("VirtualParameters", {})
    igd = dev.get("InternetGatewayDevice", {})
    
    pppoe = get_device_pppoe_username(dev)
    
    # Redaman
    rx = vp.get("RXPower", {}).get("_value") or "-"
    rx_badge = ""
    if rx != "-":
        try:
            rx_val = float(str(rx).replace("dBm", "").strip())
            if rx_val >= -24.0:
                rx_badge = "(Sinyal Bagus 🟢)"
            elif rx_val >= -27.0:
                rx_badge = "(Normal 🟡)"
            else:
                rx_badge = "(Lemah / Redaman Tinggi 🔴)"
        except Exception:
            pass
        if not str(rx).endswith("dBm"):
            rx = f"{rx} dBm"

    uptime = vp.get("getdeviceuptime", {}).get("_value") or vp.get("uptimeDevice", {}).get("_value") or "-"
    
    wlan1 = igd.get("LANDevice", {}).get("1", {}).get("WLANConfiguration", {}).get("1", {})
    ssid = wlan1.get("SSID", {}).get("_value") or vp.get("WlanSSID", {}).get("_value") or "-"
    wifi_pass = (
        wlan1.get("KeyPassphrase", {}).get("_value") or
        wlan1.get("PreSharedKey", {}).get("1", {}).get("KeyPassphrase", {}).get("_value") or
        vp.get("WlanPassword", {}).get("_value") or
        "(Tersimpan di Modem)"
    )
    
    clients = (
        wlan1.get("TotalAssociations", {}).get("_value") or
        vp.get("activedevices", {}).get("_value") or
        "0"
    )
    
    last_inform = dev.get("_lastInform")
    online_str = "Offline 🔴"
    if last_inform:
        diff_sec = get_datetime_diff_seconds(last_inform)
        if diff_sec < 600:
            online_str = "Online (Normal) 🟢"
        else:
            online_str = f"Offline ({int(diff_sec//60)} mnt lalu) 🔴"

    return (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"  📶 *STATUS LAYANAN WIFI ANDA*\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"• *ID Pelanggan*   : `{pppoe}`\n"
        f"• *Status Koneksi* : {online_str}\n"
        f"• *Nama WiFi (SSID)*: `{ssid}`\n"
        f"• *Kata Sandi*     : `{wifi_pass}`\n"
        f"• *Kualitas Sinyal*: `{rx}` {rx_badge}\n"
        f"• *Perangkat Konek*: `{clients} HP/Laptop`\n"
        f"• *Waktu Aktif*    : `{uptime}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Perintah Mandiri:*\n"
        f"• `wifi <nama_baru> <sandi_baru>` ➔ Ganti nama & sandi\n"
        f"• `pass <sandi_baru>` ➔ Ganti sandi saja (min. 8 huruf/angka)\n"
        f"• `ssid <nama_baru>` ➔ Ganti nama WiFi saja\n"
        f"• `reboot` ➔ Restart modem jika koneksi berat"
    )

def find_device(query_str):
    db = get_db()
    if db is None:
        return None
    q = query_str.strip()
    reg = {"$regex": q, "$options": "i"}

    dev = db.devices.find_one({
        "$or": [
            {"_tags": reg},
            {"tags": reg},
            {"VirtualParameters.pppoeUsername._value": reg},
            {"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username._value": reg},
            {"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANPPPConnection.1.Username._value": reg},
            {"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.3.WANPPPConnection.1.Username._value": reg},
            {"VirtualParameters.WlanSSID._value": reg},
            {"InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID._value": reg},
            {"_id": reg},
            {"_deviceId._SerialNumber": reg},
            {"DeviceID.SerialNumber._value": reg},
            {"VirtualParameters.pppoeIP._value": q},
            {"VirtualParameters.MacAddress._value": reg},
            {"VirtualParameters.PonMac._value": reg},
            {"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress._value": q}
        ]
    })
    return dev

def find_device_by_customer_identifier(ident_str):
    if not ident_str:
        return None
    raw = str(ident_str).strip()
    db = get_db()
    if db is None:
        return None

    # 1. Coba cari berdasarkan nomor HP / WhatsApp
    dev = find_device_by_phone(raw)
    if dev:
        return dev

    # 2. Coba cari di db.device_locations berdasarkan Nama Pelanggan di peta atau _id
    try:
        reg = {"$regex": f"^{re.escape(raw)}$", "$options": "i"}
        loc = db.device_locations.find_one({
            "$or": [
                {"name": raw},
                {"name": reg},
                {"_id": raw}
            ]
        })
        if loc and loc.get("_id"):
            dev = find_device(loc.get("_id"))
            if dev:
                if loc.get("name"):
                    dev["_custom_customer_name"] = loc.get("name")
                return dev
    except Exception as e:
        logger.warning(f"Error querying device_locations by identifier: {e}")

    # 3. Coba cari berdasarkan username PPPoE, Serial Number, dll
    try:
        dev = find_device(raw)
        if dev:
            loc = db.device_locations.find_one({"_id": dev.get("_id")})
            if loc and loc.get("name"):
                dev["_custom_customer_name"] = loc.get("name")
            return dev
    except Exception as e:
        logger.warning(f"Error querying devices by generic find_device: {e}")

    return None

def get_device_summary(dev):
    if not dev:
        return None, "❌ Perangkat modem tidak ditemukan. Pastikan Username PPPoE atau Serial Number benar.", True
    
    dev_id = dev.get("_id", "Unknown")
    vp = dev.get("VirtualParameters", {})
    igd = dev.get("InternetGatewayDevice", {})
    did = dev.get("_deviceId", {})
    
    # 1. Identitas PPPoE / Nama Pelanggan
    pppoe = vp.get("pppoeUsername", {}).get("_value")
    if not pppoe:
        wandev = igd.get("WANDevice", {})
        for wk in wandev:
            if wk.startswith("_"): continue
            wcds = wandev[wk].get("WANConnectionDevice", {})
            for ck in wcds:
                if ck.startswith("_"): continue
                ppps = wcds[ck].get("WANPPPConnection", {})
                for pk in ppps:
                    if pk.startswith("_"): continue
                    u = ppps[pk].get("Username", {}).get("_value")
                    if u:
                        pppoe = u
                        break
    
    has_pppoe = bool(pppoe and pppoe not in ["0", "undefined", "null"])
    display_user = pppoe if has_pppoe else "(Belum Terisi / ONT Baru)"
    
    # 2. Redaman & Sinyal Optik
    rx = vp.get("RXPower", {}).get("_value") or "-"
    rx_badge = ""
    if rx != "-":
        try:
            rx_val = float(str(rx).replace("dBm", "").strip())
            if rx_val >= -23.0:
                rx_badge = "(Sangat Bagus 🟢)"
            elif rx_val >= -26.0:
                rx_badge = "(Normal 🟡)"
            else:
                rx_badge = "(Kritis / Drop 🔴)"
        except Exception:
            pass
        if not str(rx).endswith("dBm"):
            rx = f"{rx} dBm"
        
    temp = vp.get("gettemp", {}).get("_value") or vp.get("temp", {}).get("_value") or "-"
    if temp != "-" and not str(temp).endswith("°C"):
        temp = f"{temp} °C"
        
    uptime = vp.get("getdeviceuptime", {}).get("_value") or vp.get("uptimeDevice", {}).get("_value") or "-"
    
    ip = vp.get("pppoeIP", {}).get("_value") or "-"
    if ip == "-":
        wandev = igd.get("WANDevice", {})
        for wk in wandev:
            if wk.startswith("_"): continue
            wcds = wandev[wk].get("WANConnectionDevice", {})
            for ck in wcds:
                if ck.startswith("_"): continue
                ppps = wcds[ck].get("WANPPPConnection", {})
                for pk in ppps:
                    if pk.startswith("_"): continue
                    ext_ip = ppps[pk].get("ExternalIPAddress", {}).get("_value")
                    if ext_ip and ext_ip != "0.0.0.0":
                        ip = ext_ip
                        break
    
    wlan1 = igd.get("LANDevice", {}).get("1", {}).get("WLANConfiguration", {}).get("1", {})
    ssid = wlan1.get("SSID", {}).get("_value") or vp.get("WlanSSID", {}).get("_value") or "-"
    wifi_pass = (
        wlan1.get("KeyPassphrase", {}).get("_value") or
        wlan1.get("PreSharedKey", {}).get("1", {}).get("KeyPassphrase", {}).get("_value") or
        vp.get("WlanPassword", {}).get("_value") or
        "(Tersimpan Aman di Modem)"
    )
    
    wifi_enable_val = str(wlan1.get("Enable", {}).get("_value", "true")).lower()
    wifi_is_on = wifi_enable_val not in ["false", "0"]
    
    clients = (
        wlan1.get("TotalAssociations", {}).get("_value") or
        vp.get("activedevices", {}).get("_value") or
        "0"
    )
    
    last_inform = dev.get("_lastInform")
    online_str = "Offline 🔴"
    if last_inform:
        diff_sec = get_datetime_diff_seconds(last_inform)
        if diff_sec < 600:
            online_str = "Online (Aktif) 🟢"
        else:
            online_str = f"Offline ({int(diff_sec//60)} mnt lalu) 🔴"
            
    mfr = did.get("_Manufacturer") or dev.get("DeviceID", {}).get("Manufacturer", {}).get("_value") or "-"
    model = did.get("_ProductClass") or dev.get("DeviceID", {}).get("ProductClass", {}).get("_value") or "-"
    sn = did.get("_SerialNumber") or dev.get("DeviceID", {}).get("SerialNumber", {}).get("_value") or dev_id
    mac = vp.get("MacAddress", {}).get("_value") or vp.get("PonMac", {}).get("_value") or "-"
    
    res = (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"  👤 *PELANGGAN : {display_user.upper()}*\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"• *Akun PPPoE*    : `{display_user}`\n"
        f"• *Status ONT*    : {online_str}\n"
        f"• *Redaman (RX)*  : `{rx}` {rx_badge}\n"
        f"• *Suhu Transceiver*: `{temp}`\n"
        f"• *IP WAN PPPoE*  : `{ip}`\n"
        f"• *Uptime Modem*  : `{uptime}`\n"
        f"• *Nama WiFi*     : `{ssid}` ({'Radio ON 🟢' if wifi_is_on else 'Radio OFF 🔴'})\n"
        f"• *Sandi WiFi*    : `{wifi_pass}`\n"
        f"• *User Konek*    : `{clients} perangkat`\n"
        f"• *Model Hardware*: {mfr} {model}\n"
        f"• *Serial Number* : `{sn}`\n"
        f"• *MAC Address*   : `{mac}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 *{BRAND_NAME} TR-069 Management*"
    )
    return display_user, res, wifi_is_on

def get_device_clients(dev):
    if not dev:
        return "❌ Perangkat modem tidak ditemukan."
    
    dev_id = dev.get("_id", "Unknown")
    vp = dev.get("VirtualParameters", {})
    pppoe = vp.get("pppoeUsername", {}).get("_value") or dev_id
    
    igd = dev.get("InternetGatewayDevice", {})
    lan = igd.get("LANDevice", {}).get("1", {})
    hosts = lan.get("Hosts", {}).get("Host", {})
    
    client_list = []
    for k, h in hosts.items():
        if k.startswith("_"): continue
        ip = h.get("IPAddress", {}).get("_value")
        mac = h.get("MACAddress", {}).get("_value")
        name = h.get("HostName", {}).get("_value") or "Perangkat WiFi"
        active = str(h.get("Active", {}).get("_value", "true")).lower()
        if ip or mac:
            is_act = active not in ["false", "0"]
            client_list.append({
                "name": name,
                "ip": ip or "-",
                "mac": mac or "-",
                "active": is_act
            })
            
    if not client_list:
        return (
            f"👥 *DAFTAR PERANGKAT KLIEN TERKONEKSI*\n"
            f"👤 *Pelanggan*: `{pppoe}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Tidak ada data klien yang tersimpan di memori TR-069 saat ini.\n"
            f"Ketik `/refresh {pppoe}` untuk memperbarui data langsung dari modem."
        )
        
    lines = [
        f"👥 *DAFTAR PERANGKAT KLIEN TERKONEKSI*",
        f"👤 *Pelanggan*: `{pppoe.upper()}`",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, c in enumerate(client_list[:15], start=1):
        status_icon = "🟢" if c["active"] else "⚪"
        lines.append(f"{idx}. 📱 *{c['name']}* {status_icon}")
        lines.append(f"   • IP: `{c['ip']}` | MAC: `{c['mac']}`")
        
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Total Terdeteksi: *{len(client_list)} perangkat*")
    return "\n".join(lines)

def get_bad_rx_summary():
    db = get_db()
    if db is None:
        return "❌ Gagal membuka database MongoDB."
        
    bad_list = []
    cursor = db.devices.find({"VirtualParameters.RXPower": {"$exists": True}})
    
    for dev in cursor:
        vp = dev.get("VirtualParameters", {})
        did = dev.get("_deviceId", {})
        dev_id = dev.get("_id", "")
        
        pppoe = vp.get("pppoeUsername", {}).get("_value")
        if not pppoe or pppoe in ["0", "undefined"]:
            pppoe = did.get("_SerialNumber") or dev_id
            
        rx_raw = vp.get("RXPower", {}).get("_value")
        try:
            rx_val = float(str(rx_raw).replace("dBm", "").strip())
            if rx_val < -26.0 or rx_val > -5.0:
                mfr = did.get("_Manufacturer", "")
                model = did.get("_ProductClass", "")
                bad_list.append({
                    "pppoe": pppoe,
                    "rx": rx_val,
                    "model": f"{mfr} {model}".strip()
                })
        except Exception:
            pass
            
    bad_list.sort(key=lambda x: x["rx"])
    
    if not bad_list:
        return "🎉 *SEMUA REDAMAN NORMAL!*\nTidak ditemukan modem dengan redaman kritis (seluruhnya di atas -26 dBm)."
        
    lines = [
        "⚠️ *DAFTAR MODEM REDAMAN KRITIS / DROP (< -26 dBm)*",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, b in enumerate(bad_list[:20], start=1):
        tag = "🔴 Kritis" if b["rx"] < -28.0 else "🟡 Waspada"
        lines.append(f"{idx}. 👤 *{b['pppoe']}* : `{b['rx']} dBm` ({tag})")
        if b["model"]:
            lines.append(f"   • Perangkat: {b['model']}")
            
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total bermasalah: *{len(bad_list)} pelanggan*.")
    lines.append("👉 _Ketik `/cek <username>` untuk melihat rincian pelanggan._")
    return "\n".join(lines)

def get_unconfigured_onts():
    db = get_db()
    if db is None:
        return "❌ Gagal membuka database MongoDB."
        
    cursor = db.devices.find({
        "$or": [
            {"VirtualParameters.pppoeUsername": {"$exists": False}},
            {"VirtualParameters.pppoeUsername._value": {"$in": ["", None, "0", "undefined"]}}
        ]
    })
    
    unconf_list = []
    for d in cursor:
        dev_id = d.get("_id", "")
        if "DISCOVERYSERVICE" in dev_id.upper():
            continue
        did = d.get("_deviceId", {})
        sn = did.get("_SerialNumber") or d.get("DeviceID", {}).get("SerialNumber", {}).get("_value") or dev_id
        mfr = did.get("_Manufacturer") or d.get("DeviceID", {}).get("Manufacturer", {}).get("_value") or "-"
        model = did.get("_ProductClass") or d.get("DeviceID", {}).get("ProductClass", {}).get("_value") or "-"
        
        last_inform = d.get("_lastInform")
        ago_str = "-"
        if last_inform:
            ago_str = f"{int(get_datetime_diff_seconds(last_inform) // 60)} mnt lalu"
            
        unconf_list.append({
            "sn": sn,
            "hw": f"{mfr} {model}".strip(),
            "ago": ago_str
        })
        
    if not unconf_list:
        return "✅ *Tidak ada ONT Baru*: Semua modem yang terhubung sudah memiliki konfigurasi PPPoE."
        
    lines = [
        "🆕 *DAFTAR MODEM BARU BELUM DISETTING PPPoE*",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, u in enumerate(unconf_list[:15], start=1):
        lines.append(f"{idx}. 📡 *SN*: `{u['sn']}` ({u['hw']})")
        lines.append(f"   • Terakhir Kontak: {u['ago']}")
        lines.append(f"   • Format: `/addwan {u['sn']} <user> <pass>`")
        
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total ONT baru: *{len(unconf_list)} perangkat*.")
    return "\n".join(lines)

def set_wifi_credentials(dev, new_ssid=None, new_password=None):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    
    param_values = []
    if new_ssid:
        param_values.append(["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID", new_ssid, "xsd:string"])
    if new_password:
        param_values.append(["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.KeyPassphrase", new_password, "xsd:string"])
        param_values.append(["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.KeyPassphrase", new_password, "xsd:string"])
        param_values.append(["VirtualParameters.WlanPassword", new_password, "xsd:string"])
        
    if not param_values:
        return False, "Tidak ada data SSID atau Sandi yang diubah."
        
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {
            "name": "setParameterValues",
            "parameterValues": param_values
        }
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Berhasil mengirim instruksi ganti WiFi ke modem `{dev_id}`."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except requests.exceptions.Timeout:
        return True, f"Instruksi ganti WiFi telah dikirim ke antrean modem `{dev_id}`."
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def set_wifi_power(dev, enable=True):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    val_str = "true" if enable else "false"
    
    param_values = [
        ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.Enable", val_str, "xsd:boolean"],
        ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.Enable", val_str, "xsd:boolean"]
    ]
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {
            "name": "setParameterValues",
            "parameterValues": param_values
        }
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            action_txt = "diaktifkan kembali 🟢" if enable else "dimatikan 🔴"
            return True, f"Radio pemancar WiFi modem `{dev_id}` berhasil {action_txt}."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except requests.exceptions.Timeout:
        action_txt = "diaktifkan 🟢" if enable else "dimatikan 🔴"
        return True, f"Instruksi radio WiFi {action_txt} telah dikirim ke antrean modem `{dev_id}`."
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def add_or_set_wan_pppoe(dev, pppoe_user, pppoe_pass, vlan_id=None):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    dev_id_info = dev.get("_deviceId", {})
    mfg = str(dev_id_info.get("_Manufacturer", "")).upper()
    oui = str(dev_id_info.get("_OUI", "")).upper()
    prod_class = str(dev_id_info.get("_ProductClass", "")).upper()

    igd = dev.get("InternetGatewayDevice", {})
    wandev = igd.get("WANDevice", {})

    target_path = None
    target_node = None
    best_match_score = -1

    for wk in wandev:
        if wk.startswith("_"): continue
        wcds = wandev[wk].get("WANConnectionDevice", {})
        for ck in wcds:
            if ck.startswith("_"): continue
            ppps = wcds[ck].get("WANPPPConnection", {})
            for pk in ppps:
                if pk.startswith("_"): continue
                p = ppps[pk]
                name = str(p.get("Name", {}).get("_value", "")).upper()
                cur_user = str(p.get("Username", {}).get("_value", ""))
                
                score = 0
                if cur_user == pppoe_user and pppoe_user:
                    score = 100
                elif "INTERNET" in name:
                    score = 80
                elif cur_user != "":
                    score = 50
                elif cur_user == "":
                    score = 30
                
                if score > best_match_score:
                    best_match_score = score
                    target_path = f"InternetGatewayDevice.WANDevice.{wk}.WANConnectionDevice.{ck}.WANPPPConnection.{pk}"
                    target_node = p

    if not target_path:
        base_obj = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection."
        add_url = f"{NBI_URL}/devices/{quote(dev_id, safe='')}/tasks"
        add_body = {
            "name": "addObject",
            "objectName": base_obj
        }
        try:
            requests.post(add_url, json=add_body, timeout=5)
        except Exception:
            pass
        target_path = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1"

    param_values = [
        [f"{target_path}.Enable", "true", "xsd:boolean"],
        [f"{target_path}.Username", pppoe_user, "xsd:string"],
        [f"{target_path}.Password", pppoe_pass, "xsd:string"],
        [f"{target_path}.ConnectionType", "IP_Routed", "xsd:string"],
        [f"{target_path}.NATEnabled", "true", "xsd:boolean"]
    ]

    # Handle VLAN cleanly and accurately per vendor (prevents TR-069 Fault 9005)
    if vlan_id is not None and str(vlan_id).strip() not in ("", "-", "0", "None"):
        v_str = str(vlan_id).strip()
        detected_vlan_param = None
        if target_node:
            for vk in ["X_CT-COM_VlanID", "X_CMCC_VLANIDMark", "X_HW_VLAN", "X_ZTE-COM_VlanID", "VLANID", "X_BROADCOM_COM_VLANID"]:
                if vk in target_node:
                    detected_vlan_param = vk
                    break
        
        if detected_vlan_param:
            param_values.append([f"{target_path}.{detected_vlan_param}", v_str, "xsd:unsignedInt"])
            if detected_vlan_param == "X_CMCC_VLANIDMark":
                param_values.append([f"{target_path}.X_CMCC_VLANMode", "1", "xsd:unsignedInt"])
            elif detected_vlan_param == "X_CT-COM_VlanID":
                param_values.append([f"{target_path}.X_CT-COM_Mode", "1", "xsd:unsignedInt"])
        elif not target_node or len(target_node) == 0:
            # Fallback only when target_node parameters are unknown / newly created
            if "HUAWEI" in mfg or "00259E" in oui:
                param_values.append([f"{target_path}.X_HW_VLAN", v_str, "xsd:unsignedInt"])
            elif "ZTE" in mfg or "ZICG" in mfg:
                param_values.append([f"{target_path}.X_CMCC_VLANIDMark", v_str, "xsd:unsignedInt"])
                param_values.append([f"{target_path}.X_CMCC_VLANMode", "1", "xsd:unsignedInt"])
            elif "CIOT" in mfg or "GM220" in prod_class or "M63X" in prod_class or "RTEG" in mfg:
                param_values.append([f"{target_path}.X_CT-COM_VlanID", v_str, "xsd:unsignedInt"])
                param_values.append([f"{target_path}.X_CT-COM_Mode", "1", "xsd:unsignedInt"])
            else:
                param_values.append([f"{target_path}.VLANID", v_str, "xsd:unsignedInt"])

    url_cr = f"{NBI_URL}/devices/{quote(dev_id, safe='')}/tasks?connection_request"
    url_queue = f"{NBI_URL}/devices/{quote(dev_id, safe='')}/tasks"
    body = {
        "name": "setParameterValues",
        "parameterValues": param_values
    }

    success = False
    try:
        r = requests.post(url_cr, json=body, timeout=4)
        if r.status_code in [200, 202]:
            success = True
    except Exception:
        pass

    if not success:
        try:
            r = requests.post(url_queue, json=body, timeout=5)
            if r.status_code in [200, 202]:
                success = True
        except Exception as e:
            logger.error(f"Failed to send setParameterValues to NBI: {e}")
            return False, f"Gagal menghubungi GenieACS NBI: {e}"

    if success:
        vlan_text = f"\n• *VLAN ID*: `{vlan_id}`" if (vlan_id and str(vlan_id) not in ("", "0", "-")) else "\n• *VLAN*: `Untagged`"
        return True, (
            f"✅ *Berhasil Menerapkan Konfigurasi WAN PPPoE!*\n"
            f"• *Modem*: `{dev_id}`\n"
            f"• *Jalur*: `{target_path}`\n"
            f"• *Username PPPoE*: `{pppoe_user}`\n"
            f"• *Password*: `{'*' * len(pppoe_pass)}`"
            f"{vlan_text}\n"
            f"• *Status*: Tugas TR-069 tersimpan dan akan segera dieksekusi ke modem."
        )
    return False, "Gagal mengirim tugas TR-069 ke GenieACS NBI."

def set_superadmin_password(dev, new_pass):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    
    param_values = [
        ["InternetGatewayDevice.UserInterface.Password", new_pass, "xsd:string"],
        ["InternetGatewayDevice.UserInterface.X_ZTE-COM_AdminAccount.Password", new_pass, "xsd:string"],
        ["InternetGatewayDevice.X_CT-COM_TeleComAccount.Password", new_pass, "xsd:string"],
        ["InternetGatewayDevice.UserInterface.X_HW_AdminAccount.Password", new_pass, "xsd:string"]
    ]
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {
            "name": "setParameterValues",
            "parameterValues": param_values
        }
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Perintah ubah sandi SuperAdmin Web ONT berhasil dikirim ke `{dev_id}`."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def ping_diagnostics_task(dev, host="8.8.8.8"):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    param_values = [
        ["InternetGatewayDevice.IPPingDiagnostics.DiagnosticsState", "Requested", "xsd:string"],
        ["InternetGatewayDevice.IPPingDiagnostics.Host", host, "xsd:string"],
        ["InternetGatewayDevice.IPPingDiagnostics.NumberOfRepetitions", "3", "xsd:unsignedInt"]
    ]
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {
            "name": "setParameterValues",
            "parameterValues": param_values
        }
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Perintah Ping Diagnostics ke `{host}` berhasil dikirim ke modem `{dev_id}` via TR-069."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except requests.exceptions.Timeout:
        return True, f"Perintah Ping Diagnostics ke `{host}` berhasil dikirim ke antrean modem `{dev_id}`."
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def factory_reset_device(dev):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {"name": "factoryReset"}
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Perintah FACTORY RESET berhasil dikirim ke modem `{dev_id}`. Modem akan kembali ke setelan pabrik."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def reboot_device_task(dev):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {"name": "reboot"}
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Perintah Restart berhasil dikirim ke modem `{dev_id}`."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except requests.exceptions.Timeout:
        return True, f"Perintah Restart telah dikirim ke antrean modem `{dev_id}`."
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

def refresh_device_task(dev):
    if not dev:
        return False, "Modem pelanggan tidak ditemukan."
    dev_id = dev.get("_id")
    try:
        url = f"{NBI_URL}/devices/{quote(dev_id)}/tasks?connection_request"
        body = {"name": "refreshObject", "objectName": ""}
        r = requests.post(url, json=body, timeout=10)
        if r.status_code in [200, 202]:
            return True, f"Modem `{dev_id}` berhasil di-summon/refresh."
        else:
            return False, f"GenieACS merespon HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, f"Gagal menghubungi GenieACS NBI: {e}"

# ==============================================================================
# LINUX ARMBIAN & GENIEACS SYSTEM TOOLS (DEVOPS & SELF-HEALING ENGINE)
# ==============================================================================

FORBIDDEN_COMMANDS = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd", "shutdown -h", ":(){ :|:& };:"]

def check_port_listening(host="127.0.0.1", port=3000, timeout=1.0):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None

def diagnose_system():
    cpu_temp = get_cpu_temp()

    ram = {}
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                tot = int(parts[1])
                used = int(parts[2])
                avail = int(parts[6]) if len(parts) > 6 else tot - used
                ram = {
                    "total_mb": tot,
                    "used_mb": used,
                    "available_mb": avail,
                    "pct_used": round((used / tot) * 100, 1) if tot > 0 else 0
                }
    except Exception:
        pass

    disk = {}
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            disk = {"size": parts[1], "used": parts[2], "avail": parts[3], "use_pct": parts[4]}
    except Exception:
        pass

    uptime_str = "N/A"
    try:
        uptime_str = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        pass

    mongo_name = "mongod" if os.path.exists("/lib/systemd/system/mongod.service") or os.path.exists("/etc/systemd/system/mongod.service") else "mongodb"
    svcs = ["genieacs-ui", "genieacs-cwmp", "genieacs-nbi", "genieacs-fs", "genieacs-agent", "genieacs-whatsapp", mongo_name]
    svc_status = {}
    for s in svcs:
        try:
            st = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=3).stdout.strip()
            svc_status[s] = st if st else "unknown"
        except Exception:
            svc_status[s] = "unknown"

    ports = {
        "ui_3000": check_port_listening("127.0.0.1", 3000),
        "cwmp_7547": check_port_listening("127.0.0.1", 7547),
        "nbi_7557": check_port_listening("127.0.0.1", 7557),
        "fs_7567": check_port_listening("127.0.0.1", 7567),
        "agent_7558": check_port_listening("127.0.0.1", 7558),
        "whatsapp_7559": check_port_listening("127.0.0.1", 7559),
        "mongodb_27017": check_port_listening("127.0.0.1", 27017)
    }

    return {
        "cpu_temp_c": cpu_temp,
        "ram": ram,
        "disk": disk,
        "uptime": uptime_str,
        "services": svc_status,
        "ports": ports
    }

def get_server_stats():
    try:
        d = diagnose_system()
        temp_str = f"{d.get('cpu_temp_c')} °C" if d.get('cpu_temp_c') else "N/A"
        ram = d.get("ram", {})
        disk = d.get("disk", {})
        svcs = d.get("services", {})
        ports = d.get("ports", {})

        ui_status = "🟢 Normal" if ports.get("ui_3000") and svcs.get("genieacs-ui") == "active" else "🔴 Down / Bermasalah"
        cwmp_status = "🟢 Normal" if ports.get("cwmp_7547") and svcs.get("genieacs-cwmp") == "active" else "🔴 Down"

        return (
            "📊 *STATUS SERVER STB ARMBIAN*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• *RAM Terpakai*: `{ram.get('used_mb', 0)} MB / {ram.get('total_mb', 0)} MB ({ram.get('pct_used', 0)}%)`\n"
            f"• *Penyimpanan*: `{disk.get('used', '-')} / {disk.get('size', '-')} ({disk.get('use_pct', '-')})`\n"
            f"• *Suhu CPU STB*: `{temp_str}`\n"
            f"• *Uptime Server*: `{d.get('uptime', '-')}`\n"
            f"• *GenieACS Web UI (3000)*: {ui_status}\n"
            f"• *GenieACS CWMP (7547)*: {cwmp_status}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 _Ketik pesan bebas kapan saja (contoh: 'benerin web', 'cek ip', 'ganti ip') untuk kelola server via AI._"
        )
    except Exception as e:
        return f"Gagal membaca status server: {e}"

def fix_genieacs_issues():
    logs = []
    bin_dirs = [
        "/usr/lib/node_modules/genieacs/bin",
        "/usr/local/lib/node_modules/genieacs/bin",
        "/opt/genieacs/bin"
    ]
    for bdir in bin_dirs:
        if os.path.exists(bdir):
            try:
                for f in os.listdir(bdir):
                    fp = os.path.join(bdir, f)
                    if os.path.isfile(fp):
                        st = os.stat(fp)
                        os.chmod(fp, st.st_mode | 0o755)
                logs.append(f"Fixed binary chmod +x in {bdir}")
            except Exception as e:
                logs.append(f"Chmod error {bdir}: {e}")

    for p in ["/usr/bin", "/usr/local/bin"]:
        if os.path.exists(p):
            for fname in os.listdir(p):
                if fname.startswith("genieacs-"):
                    try:
                        fp = os.path.join(p, fname)
                        st = os.stat(fp)
                        os.chmod(fp, st.st_mode | 0o755)
                    except Exception:
                        pass

    try:
        subprocess.run(["systemctl", "restart", "genieacs-ui", "genieacs-cwmp", "genieacs-nbi", "genieacs-fs"], check=False, timeout=30)
        logs.append("Restarted genieacs-* services concurrently")
    except Exception as e:
        logs.append(f"Restart error: {e}")

    ui_ok = False
    for _ in range(25):
        time.sleep(1)
        if check_port_listening("127.0.0.1", 3000, timeout=1.0):
            ui_ok = True
            break
    return {
        "success": ui_ok,
        "ui_listening_port_3000": ui_ok,
        "actions_taken": logs,
        "message": "GenieACS Web UI berhasil dipulihkan dan aktif di port 3000!" if ui_ok else "Izin file diperbaiki dan service direstart, tapi port 3000 belum mendengarkan. Cek log service."
    }

def manage_system_service(service_name, action):
    s_name = str(service_name or "").strip()
    act = str(action or "").strip().lower()
    if act not in ["start", "stop", "restart", "status", "reload"]:
        return {"success": False, "error": f"Aksi '{act}' tidak valid. Gunakan: start, stop, restart, status."}

    if s_name in ["mongodb", "mongo"]:
        s_name = "mongod" if os.path.exists("/lib/systemd/system/mongod.service") or os.path.exists("/etc/systemd/system/mongod.service") else "mongodb"

    try:
        if act == "status":
            r = subprocess.run(["systemctl", "status", s_name], capture_output=True, text=True, timeout=5)
            return {"success": True, "service": s_name, "status_output": (r.stdout or r.stderr)[:1500]}
        else:
            r = subprocess.run(["systemctl", act, s_name], capture_output=True, text=True, timeout=15)
            is_active = subprocess.run(["systemctl", "is-active", s_name], capture_output=True, text=True, timeout=3).stdout.strip()
            return {
                "success": r.returncode == 0,
                "service": s_name,
                "action": act,
                "is_active": is_active,
                "error": r.stderr if r.returncode != 0 else None
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

def read_service_logs(service_name, lines=25):
    s_name = str(service_name or "genieacs-ui").strip()
    cnt = min(max(int(lines or 25), 5), 100)
    try:
        r = subprocess.run(["journalctl", "-u", s_name, "-n", str(cnt), "--no-pager"], capture_output=True, text=True, timeout=8)
        out = (r.stdout or "").strip()
        return {
            "service": s_name,
            "lines": cnt,
            "logs": out if out else "(Log kosong atau service belum mencatat log)"
        }
    except Exception as e:
        return {"error": str(e)}

def get_active_connection_name(iface="eth0"):
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "NAME,DEVICE", "con", "show", "--active"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == iface:
                return parts[0]
    except Exception:
        pass
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "NAME", "con", "show"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        if lines:
            return lines[0]
    except Exception:
        pass
    return "Wired connection 1"

def manage_network(action="show", interface="eth0", ip=None, gateway=None, dns=None):
    if action == "show":
        ip_info = {}
        try:
            r = subprocess.run(["ip", "-4", "a"], capture_output=True, text=True, timeout=5)
            ip_info["interfaces"] = r.stdout.strip()
        except Exception as e:
            ip_info["interfaces"] = str(e)
        try:
            r = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5)
            ip_info["routes"] = r.stdout.strip()
        except Exception:
            pass
        try:
            r = subprocess.run(["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "con", "show", "--active"], capture_output=True, text=True, timeout=5)
            ip_info["nmcli_active"] = r.stdout.strip()
        except Exception:
            pass
        return ip_info

    elif action == "set_static":
        if not ip:
            return {"success": False, "error": "Parameter IP wajib diisi (contoh: 192.168.8.185/24)."}
        if not gateway:
            return {"success": False, "error": "Parameter Gateway wajib diisi (contoh: 192.168.8.1)."}

        con_name = get_active_connection_name(interface)
        dns_val = dns if dns else (gateway + ",8.8.8.8")

        cmd = [
            "nmcli", "con", "mod", con_name,
            "ipv4.addresses", ip,
            "ipv4.gateway", gateway,
            "ipv4.dns", dns_val,
            "ipv4.method", "manual"
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return {"success": False, "error": r.stderr}
            subprocess.run(["nmcli", "con", "up", con_name], capture_output=True, text=True, timeout=15)
            return {
                "success": True,
                "connection": con_name,
                "interface": interface,
                "ip": ip,
                "gateway": gateway,
                "dns": dns_val,
                "message": f"IP Statik berhasil disetel ke {ip} (Gateway: {gateway}, DNS: {dns_val}) pada koneksi '{con_name}'"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "set_dhcp":
        con_name = get_active_connection_name(interface)
        cmd = ["nmcli", "con", "mod", con_name, "ipv4.method", "auto"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return {"success": False, "error": r.stderr}
            subprocess.run(["nmcli", "con", "up", con_name], capture_output=True, text=True, timeout=15)
            return {
                "success": True,
                "connection": con_name,
                "interface": interface,
                "message": f"Koneksi '{con_name}' ({interface}) berhasil diatur ke mode DHCP otomatis."
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

def execute_linux_command(command):
    cmd_str = str(command or "").strip()
    if not cmd_str:
        return {"success": False, "error": "Perintah kosong."}

    for bad in FORBIDDEN_COMMANDS:
        if bad in cmd_str:
            return {"success": False, "error": f"Perintah '{bad}' dilarang demi keamanan sistem."}

    try:
        r = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=15)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if len(out) > 2000:
            out = out[:2000] + "\n... [Output dipotong]"
        if len(err) > 1000:
            err = err[:1000] + "\n... [Error dipotong]"
        return {
            "success": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": out if out else "(tidak ada output)",
            "stderr": err if err else None
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Waktu perintah habis (timeout 15 detik)."}
    except Exception as e:
        return {"success": False, "error": str(e)}

AI_SERVER_TOOLS = [
    {
        "name": "diagnose_system",
        "description": "Periksa status kesehatan lengkap server Linux Armbian (CPU temp, RAM, Disk, Uptime) dan semua layanan GenieACS (UI port 3000, CWMP 7547, NBI 7557, FS 7567, Agent, WhatsApp, MongoDB).",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "fix_genieacs_issues",
        "description": "Perbaiki otomatis masalah GenieACS UI tidak bisa dibuka (error 203/EXEC), perbaiki izin eksekusi chmod +x seluruh binary GenieACS, dan restart semua service GenieACS.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "manage_system_service",
        "description": "Kelola layanan systemd pada Linux Armbian (start, stop, restart, status). Layanan umum: genieacs-ui, genieacs-cwmp, genieacs-nbi, genieacs-fs, genieacs-agent, genieacs-whatsapp, mongodb, networking, ssh.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "service_name": {
                    "type": "STRING",
                    "description": "Nama service systemd (contoh: genieacs-ui, mongodb, ssh)"
                },
                "action": {
                    "type": "STRING",
                    "description": "Aksi: restart, start, stop, atau status"
                }
            },
            "required": ["service_name", "action"]
        }
    },
    {
        "name": "read_service_logs",
        "description": "Membaca baris log journalctl terbaru dari suatu service untuk melihat penyebab crash/error (contoh: genieacs-ui, mongodb, genieacs-agent).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "service_name": {
                    "type": "STRING",
                    "description": "Nama service (contoh: genieacs-ui)"
                },
                "lines": {
                    "type": "INTEGER",
                    "description": "Jumlah baris log terbaru (default 25)"
                }
            },
            "required": ["service_name"]
        }
    },
    {
        "name": "manage_network",
        "description": "Lihat atau atur konfigurasi jaringan Linux Armbian (IP address, Gateway, DNS, DHCP, atau IP Statik) menggunakan NetworkManager / nmcli.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Pilihan aksi: 'show' (tampilkan info IP & interface), 'set_static' (atur IP statis), 'set_dhcp' (atur DHCP otomatis)"
                },
                "interface": {
                    "type": "STRING",
                    "description": "Nama interface jaringan (default: eth0)"
                },
                "ip": {
                    "type": "STRING",
                    "description": "Alamat IP statik dengan CIDR (contoh: 192.168.8.185/24). Wajib jika action='set_static'"
                },
                "gateway": {
                    "type": "STRING",
                    "description": "Alamat IP Gateway router (contoh: 192.168.8.1). Wajib jika action='set_static'"
                },
                "dns": {
                    "type": "STRING",
                    "description": "Alamat DNS server dipisahkan koma (contoh: 192.168.8.1,8.8.8.8)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "execute_linux_command",
        "description": "Jalankan perintah Linux terminal aman untuk melihat informasi sistem, paket, status jaringan, file config, atau diagnosa tingkat lanjut. Perintah berbahaya diblokir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Perintah bash Linux yang ingin dijalankan (contoh: 'ping -c 3 8.8.8.8', 'cat /etc/resolv.conf', 'df -h', 'ps aux | grep node')"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "edit_genieacs_config",
        "description": "Ubah konfigurasi GenieACS Bot di database (contoh: brand_name, brand_phone, wa_enabled, gemini_model).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "Nama konfigurasi"},
                "value": {"type": "STRING", "description": "Nilai baru"}
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "update_system_git",
        "description": "Jalankan pembaruan sistem GenieACS dari repository GitHub resmi (git pull, ekstrak update, set permission, dan restart service).",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "get_bad_rx_modems",
        "description": "Ambil daftar seluruh modem ONT pelanggan yang mengalami redaman kritis / sinyal drop (di bawah -26 dBm) lengkap dengan nama PPPoE, nilai dBm, dan tipe modem.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "get_unconfigured_onts",
        "description": "Ambil daftar modem ONT baru yang terhubung ke jaringan GenieACS tetapi belum tersetting username PPPoE.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "get_devices_stats",
        "description": "Ambil ringkasan statistik total modem terdaftar, jumlah online aktif, dan jumlah offline di database GenieACS.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "get_device_detail",
        "description": "Ambil data lengkap pelanggan modem (IP, Redaman, SSID WiFi, Password, Status Online) berdasarkan username PPPoE atau Serial Number.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {"type": "STRING", "description": "Username PPPoE atau Serial Number modem pelanggan"}
            },
            "required": ["target"]
        }
    }
]

def dispatch_ai_tool(name, args):
    try:
        if name == "diagnose_system":
            return diagnose_system()
        elif name == "fix_genieacs_issues":
            return fix_genieacs_issues()
        elif name == "manage_system_service":
            return manage_system_service(args.get("service_name"), args.get("action"))
        elif name == "read_service_logs":
            return read_service_logs(args.get("service_name"), args.get("lines", 25))
        elif name == "manage_network":
            return manage_network(
                action=args.get("action", "show"),
                interface=args.get("interface", "eth0"),
                ip=args.get("ip"),
                gateway=args.get("gateway"),
                dns=args.get("dns")
            )
        elif name == "execute_linux_command":
            return execute_linux_command(args.get("command"))
        elif name == "edit_genieacs_config":
            db = get_db()
            k = args.get("key")
            v = args.get("value")
            if db is not None and k and v is not None:
                db.config.update_one({"_id": k}, {"$set": {"value": f'"{v}"' if not v.startswith('"') else v}}, upsert=True)
                return {"success": True, "message": f"Config {k} berhasil diupdate ke {v}"}
            return {"success": False, "error": "Database tidak terhubung atau parameter kosong"}
        elif name == "update_system_git":
            return apply_system_update()
        elif name == "get_bad_rx_modems":
            return get_bad_rx_summary()
        elif name == "get_unconfigured_onts":
            return get_unconfigured_onts()
        elif name == "get_devices_stats":
            db = get_db()
            if db is not None:
                t = db.devices.count_documents({})
                five_m = datetime.utcnow() - timedelta(minutes=5)
                on = db.devices.count_documents({"_lastInform": {"$gte": five_m}})
                return {"total_devices": t, "online_devices": on, "offline_devices": max(0, t - on)}
            return {"error": "Database tidak terhubung"}
        elif name == "get_device_detail":
            target = args.get("target")
            d = find_device(target)
            if d:
                _, sum_text, _ = get_device_summary(d)
                return sum_text
            return f"Modem {target} tidak ditemukan di database."
        else:
            return {"error": f"Tool '{name}' tidak ditemukan."}
    except Exception as e:
        return {"error": str(e)}

def fallback_admin_intent(raw):
    text = raw.lower().strip()

    # 1. Fix / Benerin GenieACS Web
    if re.search(r'\b(benerin|perbaiki|fix|rusak|mati|down|203)\b.*\b(genieacs|web|ui|server)\b', text, re.I) or        re.search(r'\b(genieacs|web ui|ui)\b.*\b(mati|down|error|gak bisa|tidak bisa|benerin|perbaiki)\b', text, re.I):
        res = fix_genieacs_issues()
        if res.get("success"):
            return "🛠️ *Perbaikan Otomatis GenieACS Berhasil!*\n\n"                    "• Izin binary (`chmod +x`) berhasil dipulihkan\n"                    "• Layanan GenieACS telah direstart\n"                    "• Port Web UI (3000): 🟢 *Aktif (HTTP OK)*\n\n"                    "Silakan coba buka kembali Web UI GenieACS Anda di browser!"
        else:
            return f"⚠️ *Hasil Perbaikan Otomatis:*\n`{json.dumps(res, indent=2)}`"

    # 2. Diagnosa / Cek Server
    if re.search(r'\b(cek|status|kondisi|kesehatan|suhu|ram|cpu|memory)\b.*\b(server|stb|sistem|os)\b', text, re.I) or        re.search(r'\b(server|stb)\b.*\b(cek|status|kondisi|sehat)\b', text, re.I):
        d = diagnose_system()
        temp_str = f"{d.get('cpu_temp_c')} °C" if d.get('cpu_temp_c') else "N/A"
        ram = d.get("ram", {})
        disk = d.get("disk", {})
        svcs = d.get("services", {})
        ports = d.get("ports", {})

        svc_lines = "\n".join([f"  • {k}: `{'🟢 ' + v if v == 'active' else '🔴 ' + v}`" for k, v in svcs.items()])
        port_lines = "\n".join([f"  • {k}: `{'🟢 Listening' if v else '🔴 Closed'}`" for k, v in ports.items()])

        return (
            f"📊 *Laporan Diagnosa Server Linux Armbian*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🌡️ *Suhu CPU:* `{temp_str}`\n"
            f"🧠 *RAM:* `{ram.get('used_mb', 0)} MB / {ram.get('total_mb', 0)} MB ({ram.get('pct_used', 0)}%)`\n"
            f"💾 *Penyimpanan:* `{disk.get('used', '-')} / {disk.get('size', '-')} ({disk.get('use_pct', '-')})`\n"
            f"⏱️ *Uptime:* `{d.get('uptime', '-')}`\n\n"
            f"⚙️ *Status Layanan:*\n{svc_lines}\n\n"
            f"🔌 *Port Status:*\n{port_lines}"
        )

    # 4. Redaman Kritis / Optik
    if re.search(r'\b(redaman|kritis|los|jelek|drop|rx power|sinyal lemah|optik)\b', text, re.I):
        return get_bad_rx_summary()

    # 5. Rekap Total / Online / Offline Modem
    if re.search(r'\b(berapa|total|jumlah|banyak)\b.*\b(modem|pelanggan|ont|klien)\b', text, re.I) or re.search(r'\b(modem|pelanggan)\b.*\b(online|offline)\b', text, re.I):
        db = get_db()
        if db is not None:
            t = db.devices.count_documents({})
            five_m = datetime.utcnow() - timedelta(minutes=5)
            on = db.devices.count_documents({"_lastInform": {"$gte": five_m}})
            off = max(0, t - on)
            pct = (on / t * 100) if t > 0 else 0
            return (
                f"📊 *REKAP KONEKSI MODEM PELANGGAN*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• *Total Modem Terdaftar:* `{t} unit`\n"
                f"• *Modem Online Aktif:* `{on} unit` ({pct:.1f}%)\n"
                f"• *Modem Offline / Mati:* `{off} unit`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👉 _Ketik `redaman` untuk melihat modem yang redamannya kritis._"
            )

    # 6. ONT Baru / Belum Setting
    if re.search(r'\b(ontbaru|newont|unconf|modem baru|ont baru|belum setting|belum disetting)\b', text, re.I):
        return get_unconfigured_onts()

    # 3. Cek IP & Jaringan
    if re.search(r'\b(cek|lihat|info|status)\b.*\b(ip|jaringan|network|ethernet)\b', text, re.I):
        net = manage_network("show")
        return (
            f"🌐 *Informasi Jaringan Server STB:*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"```\n{net.get('interfaces', '-')}\n```\n\n"
            f"**Koneksi Aktif (NetworkManager):**\n`{net.get('nmcli_active', '-')}`"
        )

    # 4. Ganti IP Statik: misal 'set ip 192.168.8.185/24 gw 192.168.8.1'
    m_ip = re.search(r'(?:set\s+ip|ip\s+statik|ganti\s+ip)\s+([0-9\.\/]+)(?:\s+(?:gw|gateway)\s+([0-9\.]+))?(?:\s+(?:dns)\s+([0-9\.\,]+))?', text, re.I)
    if m_ip:
        ip_val = m_ip.group(1)
        if "/" not in ip_val:
            ip_val += "/24"
        gw_val = m_ip.group(2)
        if not gw_val:
            gw_parts = ip_val.split("/")[0].split(".")
            gw_val = f"{gw_parts[0]}.{gw_parts[1]}.{gw_parts[2]}.1"
        dns_val = m_ip.group(3) or f"{gw_val},8.8.8.8"
        res = manage_network(action="set_static", ip=ip_val, gateway=gw_val, dns=dns_val)
        if res.get("success"):
            return f"✅ *IP Statik Berhasil Diatur:*\n\n• IP: `{ip_val}`\n• Gateway: `{gw_val}`\n• DNS: `{dns_val}`\n• Koneksi: `{res.get('connection')}`"
        else:
            return f"⚠️ *Gagal mengatur IP Statik:*\n{res.get('error')}"

    # 5. Ganti ke DHCP: misal 'set dhcp' atau 'ip dhcp'
    if re.search(r'\b(set\s+dhcp|ip\s+dhcp|mode\s+dhcp)\b', text, re.I):
        res = manage_network(action="set_dhcp")
        if res.get("success"):
            return f"✅ *Mode Jaringan Diubah ke DHCP:*\n{res.get('message')}"
        else:
            return f"⚠️ *Gagal mengubah ke DHCP:*\n{res.get('error')}"

    # 6. Restart Service: misal 'restart genieacs-ui', 'restart mongodb'
    m_svc = re.search(r'\b(restart|start|stop)\s+(?:service\s+)?([a-zA-Z0-9\-_]+)\b', text, re.I)
    if m_svc and m_svc.group(1).lower() in ["restart", "start", "stop"]:
        act = m_svc.group(1).lower()
        svc_name = m_svc.group(2).lower()
        if svc_name not in ["modem", "ont"]:
            res = manage_system_service(svc_name, act)
            if res.get("success"):
                return f"⚙️ *Layanan `{svc_name}` berhasil di-{act}!*\n• Status saat ini: `{res.get('is_active')}`"
            else:
                return f"⚠️ *Gagal me-{act} layanan `{svc_name}`:*\n{res.get('error')}"

    # 7. Eksekusi Command Terminal: misal 'cmd ping -c 3 8.8.8.8' atau 'sh uptime'
    m_cmd = re.search(r'^(?:cmd|sh|bash|exec)\s+(.+)$', raw.strip(), re.I)
    if m_cmd:
        c_str = m_cmd.group(1).strip()
        res = execute_linux_command(c_str)
        return (
            f"🖥️ *Eksekusi Terminal:* `{c_str}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**Exit Code:** `{res.get('returncode')}`\n"
            f"```\n{res.get('stdout')}\n```"
            + (f"\n**Error:**\n```\n{res.get('stderr')}\n```" if res.get('stderr') else "")
        )

    # 8. Update Sistem / Git Pull
    if re.search(r'\b(update|pull)\b.*\b(sistem|server|bot|git)\b', text, re.I):
        res = apply_system_update()
        return f"🚀 *Update Sistem Selesai:*\n\n• Pesan: {res.get('message')}\n• Restart: {res.get('restarted')}"

    return None

# ==============================================================================
# GEMINI AI ASSISTANT (CONVERSATIONAL DEVOPS & TR-069 AGENT)
# ==============================================================================

def ask_gemini_ai(gemini_key, model_name, user_prompt, sender_id="admin", is_admin=False):
    if not is_valid_token(gemini_key):
        if is_admin:
            return fallback_admin_intent(user_prompt)
        return None

    # Fallback model pintar (mengutamakan model cepat dengan kuota aktif)
    candidate_models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]
    if model_name and model_name not in candidate_models and "1.5" not in model_name:
        candidate_models.insert(0, model_name)
    headers = {"Content-Type": "application/json"}
    
    if is_admin:
        system_instruction = (
            f"Anda adalah Asisten AI Senior DevOps Linux Armbian & TR-069 GenieACS Resmi dari {BRAND_NAME}.\n"
            f"Kontak CS/WhatsApp: {BRAND_PHONE}.\n"
            "Anda memiliki hak akses root penuh untuk mengelola server STB Armbian ini.\n"
            "Anda dapat menggunakan tools untuk mendiagnosa server, memperbaiki izin file (chmod +x) GenieACS, "
            "me-restart service, mengatur IP statik / DHCP melalui NetworkManager (nmcli), membaca log, dan menjalankan perintah Linux.\n"
            "Gunakan tools secara proaktif ketika admin meminta bantuan teknis seputar server atau jaringan.\n"
            "Selalu berikan penjelasan hasil kerja Anda secara ramah, sopan, ringkas, dan jelas dalam bahasa Indonesia."
        )
    else:
        system_instruction = (
            f"Anda adalah Asisten Layanan Pelanggan (Customer Care) dari {BRAND_NAME} (Layanan Internet WiFi & RT/RW Net).\n"
            f"Nomor Kontak WhatsApp / CS: {BRAND_PHONE}.\n"
            "Tugas Anda adalah menjawab pertanyaan calon pelanggan atau masyarakat seputar layanan WiFi secara ramah, santun, ringkas, dan membantu dalam bahasa Indonesia.\n"
            "PENTING: Gunakan gaya bahasa percakapan WhatsApp yang alami dan santai (seperti chat orang biasa). "
            "JANGAN PERNAH menambahkan kop surat, header perusahaan (seperti nama kantor di baris atas), garis pembatas, atau footer berulang agar pesan terlihat seperti chat WhatsApp normal.\n"
            "Jika mereka menanyakan pasang baru atau promo, sampaikan dengan santai dan sarankan untuk menghubungi nomor kontak CS di atas jika butuh dibantu lebih lanjut."
        )

    contents = [
        {
            "role": "user",
            "parts": [{"text": user_prompt}]
        }
    ]

    for turn in range(4):
        payload = {
            "contents": contents,
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            }
        }
        if is_admin:
            payload["tools"] = [{"function_declarations": AI_SERVER_TOOLS}]

        try:
            r = None
            for cm in candidate_models:
                m_c = cm if cm.startswith("models/") else f"models/{cm}"
                u = f"https://generativelanguage.googleapis.com/v1beta/{m_c}:generateContent?key={gemini_key}"
                try:
                    res = requests.post(u, headers=headers, json=payload, timeout=20)
                    if res.status_code == 200:
                        r = res
                        break
                    else:
                        logger.warning(f"Gemini model {cm} status {res.status_code}: {res.text[:100]}")
                except Exception as e_req:
                    logger.warning(f"Gemini model {cm} request error: {e_req}")

            if not r or r.status_code != 200:
                break

            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                break

            content_obj = candidates[0].get("content", {})
            parts = content_obj.get("parts", [])
            if not parts:
                break

            func_call = None
            text_reply = ""
            for p in parts:
                if "functionCall" in p:
                    func_call = p["functionCall"]
                if "text" in p:
                    text_reply += p["text"]

            if not func_call:
                return text_reply.strip()

            fn_name = func_call.get("name")
            fn_args = func_call.get("args", {})
            logger.info(f"AI Tool Call: {fn_name}({fn_args})")

            tool_result = dispatch_ai_tool(fn_name, fn_args)

            contents.append({
                "role": "model",
                "parts": [{"functionCall": func_call}]
            })
            contents.append({
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": fn_name,
                            "response": {"name": fn_name, "content": tool_result}
                        }
                    }
                ]
            })
        except Exception as e:
            logger.warning(f"Gemini Tool Execution error: {e}")
            break

    if is_admin:
        return fallback_admin_intent(user_prompt)
    return None

# ==============================================================================
# TELEGRAM API HELPERS
# ==============================================================================


# ==============================================================================
# ALIJAYA NET - VOICE COMMAND & VOICE REPLY (STT via Gemini & TTS via gTTS)
# ==============================================================================

VOICE_PERSISTENT_USERS = set()
VOICE_SESSION_USERS = set()

def is_voice_reply_active(chat_id):
    cid = str(chat_id)
    return (cid in VOICE_PERSISTENT_USERS) or (cid in VOICE_SESSION_USERS)

def clean_text_for_speech(text):
    if not text:
        return ""
    # Hapus format markdown
    t = re.sub(r'[*_`~#\[\]\(\)\>\+=\|{}.!-]', ' ', str(text))
    # Hapus tautan URL
    t = re.sub(r'https?://\S+|www\.\S+', '', t)
    # Hapus garis pemisah dan bullets
    t = re.sub(r'[━─═\-_]{2,}', ' ', t)
    t = re.sub(r'[•►✔️✅❌⚠️🔔💡📌🔍🚀📶🌐📊👥🔄🆕❓💳💸🏢📞🏠👤📱🤖🌓]', ' ', t)
    # Hapus label teknis TR-069 yang berulang
    t = re.sub(r'InternetGatewayDevice\.[^\s]+', 'parameter modem', t)
    # Normalisasi spasi
    t = re.sub(r'\s+', ' ', t).strip()
    # Batasi agar TTS tidak berbicara kepanjangan (maksimal 45 kata, sisanya rujukan ke layar)
    words = t.split()
    if len(words) > 45:
        t = " ".join(words[:45]) + "... Rincian lengkapnya sudah saya tampilkan di layar."
    return t

TTS_MEMORY_CACHE = {}

def fetch_google_tts_chunk(chunk_text, lang='id'):
    try:
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={urllib.parse.quote(chunk_text)}&tl={lang}&client=tw-ob"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        logger.warning(f"Google TTS chunk fetch error: {e}")
    return None

def generate_google_speech(text):
    clean = clean_text_for_speech(text)
    if not clean:
        return None
    cache_key = clean.lower()
    if cache_key in TTS_MEMORY_CACHE:
        return TTS_MEMORY_CACHE[cache_key]

    words = clean.split()
    chunks = []
    curr = ""
    for w in words:
        if len((curr + " " + w).strip()) > 170:
            if curr.strip():
                chunks.append(curr.strip())
            curr = w
        else:
            curr = (curr + " " + w).strip()
    if curr.strip():
        chunks.append(curr.strip())

    buffers = []
    for ch in chunks:
        b = fetch_google_tts_chunk(ch, 'id')
        if b:
            buffers.append(b)

    if not buffers:
        return None

    combined = b"".join(buffers)
    if len(TTS_MEMORY_CACHE) > 80:
        TTS_MEMORY_CACHE.pop(next(iter(TTS_MEMORY_CACHE)), None)
    TTS_MEMORY_CACHE[cache_key] = combined
    return combined

def text_to_speech_ogg(text, lang='id'):
    try:
        clean = clean_text_for_speech(text)
        if not clean or len(clean) < 2:
            return None
        tmp_id = f"{int(time.time())}_{secrets.token_hex(4)}"
        mp3_path = f"/tmp/reply_{tmp_id}.mp3"
        ogg_path = f"/tmp/reply_{tmp_id}.ogg"
        
        from gtts import gTTS
        tts = gTTS(text=clean, lang=lang)
        tts.save(mp3_path)
        
        cmd = [
            "ffmpeg", "-y", "-i", mp3_path,
            "-c:a", "libopus", "-b:a", "32k", "-vbr", "on",
            ogg_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            return ogg_path
        return None
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        return None

def send_telegram_voice(token, chat_id, ogg_path, caption=None):
    if not ogg_path or not os.path.exists(ogg_path):
        return False
    url = f"https://api.telegram.org/bot{token}/sendVoice"
    try:
        with open(ogg_path, "rb") as f:
            files = {"voice": ("voice.ogg", f, "audio/ogg")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            r = requests.post(url, data=data, files=files, timeout=20)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram voice to {chat_id}: {e}")
        return False

def download_telegram_file(token, file_id):
    try:
        url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        r = requests.get(url_info, timeout=10)
        if r.status_code != 200:
            return None
        info = r.json()
        file_path = info.get("result", {}).get("file_path")
        if not file_path:
            return None
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r_down = requests.get(download_url, timeout=25)
        if r_down.status_code == 200:
            return r_down.content
        return None
    except Exception as e:
        logger.error(f"Failed to download Telegram file {file_id}: {e}")
        return None

def transcribe_audio_with_gemini(gemini_key, model_name, audio_bytes, mime_type="audio/ogg"):
    if not is_valid_token(gemini_key) or not audio_bytes:
        return None
    try:
        # Kandidat model yang valid untuk multimodal audio
        candidate_models = []
        if model_name and "1.5" not in model_name:
            m_clean = model_name if model_name.startswith("models/") else f"models/{model_name}"
            candidate_models.append(m_clean)
        # Default model terbaru yang terbukti aktif
        for m in ["models/gemini-3.5-flash", "models/gemini-3.8-flash", "models/gemini-2.5-flash"]:
            if m not in candidate_models:
                candidate_models.append(m)

        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        headers = {"Content-Type": "application/json"}
        prompt = (
            "Dengarkan rekaman suara bahasa Indonesia ini dengan cermat. "
            "Transkripsikan isi ucapannya menjadi kalimat perintah teks yang bersih, akurat, dan ringkas. "
            "Contoh jika mendengar ucapan 'cek status modem': tuliskan hanya 'cek status modem'. "
            "JANGAN tambahkan tanda kutip, jangan ada awalan seperti 'Teks transkripsi:', atau kata pengantar apapun. "
            "Hanya teks hasil transkripsinya saja."
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_audio
                            }
                        },
                        {"text": prompt}
                    ]
                }
            ]
        }

        for cm in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/{cm}:generateContent?key={gemini_key}"
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=25)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
                            raw_text = raw_text.strip('"\'\`').strip()
                            if raw_text:
                                logger.info(f"Gemini STT success with model {cm}: '{raw_text}'")
                                return raw_text
                else:
                    logger.warning(f"Gemini Speech-to-Text ({cm}) error HTTP {r.status_code}: {r.text[:150]}")
            except Exception as req_err:
                logger.warning(f"Gemini STT request failed for {cm}: {req_err}")
                continue
    except Exception as e:
        logger.error(f"Transcribe audio exception: {e}")
    return None


def send_telegram(token, chat_id, text, parse_mode="Markdown", reply_markup=None, send_voice_also=False):
    if not text or not str(text).strip():
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
        
    # Kirim balasan suara jika diminta atau user aktif mode suara
    if send_voice_also or is_voice_reply_active(chat_id):
        try:
            ogg_path = text_to_speech_ogg(text)
            if ogg_path and os.path.exists(ogg_path):
                try:
                    send_telegram_voice(token, chat_id, ogg_path)
                finally:
                    if os.path.exists(ogg_path):
                        os.remove(ogg_path)
        except Exception as err_v:
            logger.error(f"Voice reply delivery error: {err_v}")

def answer_callback(token, callback_id, text, show_alert=False):
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text, "show_alert": show_alert}, timeout=8)
    except Exception as e:
        logger.error(f"Failed to answer callback: {e}")

def register_bot_commands(token):
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "menu", "description": "Tampilkan Menu Tombol Cepat"},
        {"command": "cek", "description": "Cek redaman & status: /cek <user_atau_sn>"},
        {"command": "redaman", "description": "Audit modem redaman kritis / drop"},
        {"command": "ontbaru", "description": "Cek modem baru belum disetting PPPoE"},
        {"command": "klien", "description": "Cek HP/laptop terhubung: /klien <user>"},
        {"command": "addwan", "description": "Tambah/Set WAN: /addwan <sn> <user> <pass> [vlan]"},
        {"command": "wifioff", "description": "Matikan pemancar WiFi: /wifioff <user>"},
        {"command": "wifion", "description": "Hidupkan pemancar WiFi: /wifion <user>"},
        {"command": "ssid", "description": "Ganti nama WiFi saja: /ssid <user> <nama>"},
        {"command": "pass", "description": "Ganti sandi WiFi saja: /pass <user> <sandi>"},
        {"command": "wifi", "description": "Ganti SSID & Sandi: /wifi <user> <ssid> <sandi>"},
        {"command": "ping", "description": "Diagnostik Ping TR-069: /ping <user> [host]"},
        {"command": "superadmin", "description": "Ganti sandi admin web ONT: /superadmin <user> <pass>"},
        {"command": "reboot", "description": "Restart modem pelanggan: /reboot <user>"},
        {"command": "factoryreset", "description": "Reset modem ke setelan pabrik: /factoryreset <user>"},
        {"command": "server", "description": "Cek status CPU, RAM & Suhu STB"},
        {"command": "help", "description": "Panduan lengkap penggunaan bot"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=8)
        logger.info("Bot commands registered successfully with Telegram.")
    except Exception as e:
        logger.warning(f"Could not register bot commands: {e}")

# ==============================================================================
# MESSAGE & CALLBACK HANDLERS
# ==============================================================================

def handle_callback_query(token, sender_id, cb_data, callback_id):
    logger.info(f"Handling callback: {cb_data} from {sender_id}")
    parts = cb_data.split(":", 1)
    act = parts[0]
    target = parts[1] if len(parts) > 1 else ""

    if act == "reboot" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        ok, msg = reboot_device_task(dev)
        answer_callback(token, callback_id, "Perintah Reboot terkirim!", show_alert=False)
        send_telegram(token, sender_id, f"{'✅' if ok else '❌'} {msg}")
        return

    if act == "refresh" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        refresh_device_task(dev)
        answer_callback(token, callback_id, "Memperbarui data dari modem...", show_alert=False)
        time.sleep(1.5)
        fresh_dev = find_device(target)
        pppoe, summary, wifi_on = get_device_summary(fresh_dev)
        kb = get_device_inline_keyboard(pppoe, fresh_dev.get("_id"), wifi_on)
        send_telegram(token, sender_id, summary, reply_markup=kb)
        return

    if act == "klien" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        answer_callback(token, callback_id, "Mengambil daftar klien...", show_alert=False)
        msg = get_device_clients(dev)
        send_telegram(token, sender_id, msg)
        return

    if act == "wifioff" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        ok, msg = set_wifi_power(dev, enable=False)
        answer_callback(token, callback_id, "WiFi dinonaktifkan!", show_alert=False)
        send_telegram(token, sender_id, f"{'✅' if ok else '❌'} {msg}")
        return

    if act == "wifion" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        ok, msg = set_wifi_power(dev, enable=True)
        answer_callback(token, callback_id, "WiFi diaktifkan!", show_alert=False)
        send_telegram(token, sender_id, f"{'✅' if ok else '❌'} {msg}")
        return

    if act == "prompt_fr" and target:
        answer_callback(token, callback_id, "Peringatan Reset Pabrik", show_alert=False)
        confirm_kb = {
            "inline_keyboard": [
                [
                    {"text": "⚠️ Ya, Reset Pabrik", "callback_data": f"do_fr:{target}"},
                    {"text": "❌ Batal", "callback_data": "cancel_fr"}
                ]
            ]
        }
        send_telegram(token, sender_id, (
            f"⚠️ *KONFIRMASI FACTORY RESET*\n"
            f"Apakah Anda yakin ingin mereset modem pelanggan `{target}` ke setelan pabrik?\n"
            f"_Seluruh konfigurasi WAN, WiFi, dan sandi akan kembali ke standar bawaan pabrik._"
        ), reply_markup=confirm_kb)
        return

    if act == "do_fr" and target:
        dev = find_device(target)
        if not dev:
            answer_callback(token, callback_id, f"Modem {target} tidak ditemukan!", show_alert=True)
            return
        ok, msg = factory_reset_device(dev)
        answer_callback(token, callback_id, "Sinyal Reset Terkirim", show_alert=False)
        send_telegram(token, sender_id, f"{'✅' if ok else '❌'} {msg}")
        return

    if act == "cancel_fr":
        answer_callback(token, callback_id, "Dibatalkan", show_alert=False)
        send_telegram(token, sender_id, "✅ Operasi Factory Reset dibatalkan.")
        return

    if act == "prompt_ssid" and target:
        answer_callback(token, callback_id, "Ganti Nama WiFi", show_alert=False)
        USER_STATES[sender_id] = {"action": "wait_ssid", "target": target}
        send_telegram(token, sender_id, (
            f"📶 *Ganti Nama WiFi untuk Pelanggan: `{target}`*\n"
            f"Silakan ketik nama WiFi baru yang Anda inginkan:\n"
            f"_(Bisa langsung ketik namanya saja atau gunakan `/ssid {target} <nama_baru>`)_"
        ))
        return

    if act == "prompt_pass" and target:
        answer_callback(token, callback_id, "Ganti Sandi WiFi", show_alert=False)
        USER_STATES[sender_id] = {"action": "wait_pass", "target": target}
        send_telegram(token, sender_id, (
            f"🔑 *Ganti Sandi WiFi untuk Pelanggan: `{target}`*\n"
            f"Silakan ketik sandi WiFi baru (minimal 8 karakter):\n"
            f"_(Bisa langsung ketik sandinya saja atau gunakan `/pass {target} <sandi_baru>`)_"
        ))
        return

    if act == "prompt_wan" and target:
        answer_callback(token, callback_id, "Set WAN PPPoE", show_alert=False)
        USER_STATES[sender_id] = {"action": "wait_wan", "target": target}
        send_telegram(token, sender_id, (
            f"🌐 *Set Koneksi WAN PPPoE untuk: `{target}`*\n\n"
            f"Silakan ketik data dengan format:\n"
            f"`<user_pppoe> <password_pppoe> [vlan_id]`\n\n"
            f"_Contoh tanpa VLAN:_ `{target} 12345678`\n"
            f"_Contoh dengan VLAN:_ `{target} 12345678 100`"
        ))
        return

def process_agent_command(user_text, sender_id="admin", is_admin=True, gemini_key="", gemini_model="gemini-1.5-flash", registered_tag=None):
    raw = str(user_text or "").strip()
    if not raw:
        return (None, None)

    txt = raw
    clean_txt = txt.lstrip("/!#").strip()

    # 0. Resolusi Identitas Pengirim (Admin, Pelanggan Terdaftar, atau Tamu/Orang Asing)
    customer_dev = None
    if not is_admin:
        if registered_tag:
            customer_dev = find_device(registered_tag)
        if not customer_dev and sender_id:
            customer_dev = find_device_by_phone(sender_id)
            if customer_dev:
                registered_tag = customer_dev.get("_id")

    is_customer = bool(customer_dev or registered_tag)

    # Exact check for quick button presses (matches emoji + text variations)
    btn_words = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean_txt).strip().lower().split()
    btn_phrase = " ".join(btn_words)

    if btn_phrase in ("tambah set wan", "set wan"):
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        wan_guide = (
            "🌐 *Tambah / Konfigurasi WAN PPPoE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan gunakan perintah dengan format:\n"
            "`addwan <sn_modem> <user_pppoe> <password_pppoe> [vlan_id]`\n\n"
            "📌 *Contoh Tanpa VLAN:*\n"
            "`addwan ZTEGC1234567 cucimotor 12345678`\n\n"
            "📌 *Contoh Dengan VLAN:*\n"
            "`addwan ZTEGC1234567 cucimotor 12345678 100`"
        )
        return (wan_guide, None)

    if btn_phrase in ("reboot modem", "restart modem"):
        if is_customer and not is_admin:
            target = customer_dev.get("_id") if customer_dev else registered_tag
            dev = find_device(target)
            if dev:
                ok, msg = reboot_device_task(dev)
                p_name = get_device_pppoe_username(dev)
                return (
                    f"🔄 *Perintah Restart Terkirim!*\n"
                    f"Modem Anda (*{p_name}*) sedang memulai ulang (reboot).\n"
                    f"Mohon tunggu sekitar 1-2 menit hingga lampu PON/Internet menyala stabil kembali.",
                    None
                )
        return ("🔄 *Reboot Modem*: Silakan gunakan perintah:\n`reboot <username_pppoe/sn>`\n_Contoh:_ `reboot cucimotor`", None)

    if btn_phrase in ("ubah wifi sandi", "ubah wifi", "wifi sandi"):
        if is_customer and not is_admin:
            return (
                "📶 *Ubah WiFi / Sandi*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Silakan gunakan salah satu perintah berikut:\n\n"
                "• *Ubah Nama & Sandi:* `wifi <nama_baru> <sandi_baru>`\n"
                "• *Ubah Sandi Saja:* `pass <sandi_baru>`\n"
                "• *Ubah Nama Saja:* `ssid <nama_baru>`\n\n"
                "_Contoh:_ `wifi Rumah-Ku SandiRahasia123`",
                None
            )
        wifi_guide = (
            "📶 *Ubah WiFi / Sandi Pelanggan*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan gunakan salah satu format perintah berikut:\n\n"
            "• *Ubah Nama & Sandi:* `wifi <user> <nama_wifi_baru> <sandi_baru>`\n"
            "  _Contoh:_ `wifi cucimotor Alijaya-Net 12345678`\n\n"
            "• *Ubah Nama WiFi Saja:* `ssid <user> <nama_wifi_baru>`\n"
            "  _Contoh:_ `ssid cucimotor Alijaya-Net`\n\n"
            "• *Ubah Sandi WiFi Saja:* `pass <user> <sandi_baru>`\n"
            "  _Contoh:_ `pass cucimotor 12345678`"
        )
        return (wifi_guide, None)

    if btn_phrase in ("status server stb", "status server", "status stb", "server stb"):
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        return (get_server_stats(), get_main_menu_keyboard())

    if btn_phrase in ("daftar klien wifi", "daftar klien", "klien wifi", "cek klien"):
        if is_customer and not is_admin:
            target = customer_dev.get("_id") if customer_dev else registered_tag
            dev = find_device(target)
            if dev:
                return (get_device_clients(dev), None)
        return ("👥 *Daftar Klien Terhubung*: Silakan gunakan perintah:\n`klien <username_pppoe/sn>`\n_Contoh:_ `klien cucimotor`", None)

    if btn_phrase in ("cek modem", "info modem"):
        if is_customer and not is_admin:
            target = customer_dev.get("_id") if customer_dev else registered_tag
            dev = find_device(target)
            if dev:
                return (get_customer_friendly_summary(dev), None)
        return ("🔍 *Cek Modem*: Silakan gunakan perintah:\n`cek <username_pppoe/sn>`\n_Contoh:_ `cek cucimotor`", None)

    if btn_phrase in ("cek redaman kritis", "cek redaman", "redaman kritis"):
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        return (get_bad_rx_summary(), get_main_menu_keyboard())

    if btn_phrase in ("modem belum setting", "modem belum"):
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        return (get_unconfigured_onts(), get_main_menu_keyboard())

    # 0. DEVOPS & SYSTEM MANAGEMENT INTENT (Admin Only)
    if is_admin:
        lower_raw = raw.lower()
        is_devops_intent = (
            any(k in lower_raw for k in ["benerin", "perbaiki", "fix ", "kondisi server", "status server", "cek server", "suhu stb", "suhu cpu", "cek ram", "cek ip", "info ip", "jaringan", "set ip", "ip statik", "ip dhcp"]) or
            lower_raw.startswith(("cmd ", "sh ", "bash ", "exec ", "restart service", "start service", "stop service"))
        )
        if is_devops_intent:
            if gemini_key and is_valid_token(gemini_key):
                ai_rep = ask_gemini_ai(gemini_key, gemini_model, raw, sender_id, is_admin=True)
                if ai_rep:
                    return (ai_rep, None)
            adm_rep = fallback_admin_intent(raw)
            if adm_rep:
                return (adm_rep, None)

    # === DETEKSI INTENT NATURAL PERTANYAAN ADMIN DENGAN DATA REALTIME SERVER ===
    if is_admin:
        lower_txt = clean_txt.lower()
        words_txt = lower_txt.split()

        # A. Audit Redaman Kritis / Drop / LOS massal
        rx_triggers = ["redaman", "kritis", "los", "jelek", "drop", "rx power", "sinyal lemah", "optik"]
        if any(trg in lower_txt for trg in rx_triggers):
            generic_markers = ["yang", "semua", "daftar", "list", "ada", "kritis", "drop", "berapa", "kolektif", "massal", "mana saja", "jelek", "buruk", "lemah", "kritisnya", "redamannya"]
            tokens = [w for w in words_txt if w not in ["cek", "lihat", "status", "info", "kondisi", "modem", "ont", "sinyal", "koneksi", "pelanggan", "di"]]
            target_cand = " ".join([t for t in tokens if t not in rx_triggers and t not in generic_markers]).strip()
            if target_cand:
                dev = find_device(target_cand)
                if dev:
                    _, sum_txt, wifi_on = get_device_summary(dev)
                    return (sum_txt, get_device_inline_keyboard(target_cand, dev.get("_id"), wifi_on))
            return (get_bad_rx_summary(), get_main_menu_keyboard())

        # B. Cek ONT Baru / Belum Setting
        ont_triggers = ["ontbaru", "newont", "unconf", "modem baru", "ont baru", "belum setting", "belum disetting", "belum tersetting"]
        if any(trg in lower_txt for trg in ont_triggers):
            return (get_unconfigured_onts(), get_main_menu_keyboard())

        # C. Rekap Jumlah Total / Online / Offline Modem
        stats_triggers = ["berapa modem", "total modem", "modem online", "modem offline", "jumlah modem", "total pelanggan", "berapa ont", "status modem"]
        if any(trg in lower_txt for trg in stats_triggers):
            db = get_db()
            if db is not None:
                total_devs = db.devices.count_documents({})
                five_min_ago = datetime.utcnow() - timedelta(minutes=5)
                online_devs = db.devices.count_documents({"_lastInform": {"$gte": five_min_ago}})
                offline_devs = max(0, total_devs - online_devs)
                pct_online = (online_devs / total_devs * 100) if total_devs > 0 else 0
                rep = (
                    f"📊 *REKAP KONEKSI MODEM PELANGGAN*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"• *Total Modem Terdaftar:* `{total_devs} unit`\n"
                    f"• *Modem Online Aktif:* `{online_devs} unit` ({pct_online:.1f}%)\n"
                    f"• *Modem Offline / Mati:* `{offline_devs} unit`\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👉 _Ketik `redaman` untuk melihat modem yang redamannya kritis._"
                )
                return (rep, get_main_menu_keyboard())

        # D. Status Server STB Armbian (CPU, RAM, Suhu)
        server_triggers = ["status server", "cek server", "kondisi server", "suhu stb", "suhu cpu", "cek ram", "cek disk", "uptime server", "kondisi stb"]
        if any(trg in lower_txt for trg in server_triggers):
            return (get_server_stats(), get_main_menu_keyboard())

    # Standard command parsing (stripping leading emojis/symbols)
    norm_txt = re.sub(r'^[^\w\s]+', '', clean_txt).strip()
    parts = norm_txt.split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    # Normalization of aliases for typed text
    if cmd in ["bantuan", "help", "menu", "start"] or btn_phrase in ("bantuan help", "bantuan", "help", "menu"):
        cmd = "menu"
        rest = ""
    elif cmd in ["server", "status"] and rest.lower() in ["", "server", "stb", "server stb"]:
        if is_admin:
            cmd = "server"
            rest = ""
        else:
            cmd = "cek"
            rest = ""
    elif cmd in ["restart", "reboot"]:
        cmd = "reboot"
        if rest.lower().startswith("modem"):
            rest = rest[5:].strip()
    elif cmd in ["cek", "status", "info", "sinyal", "koneksi"]:
        if rest.lower() in ["koneksi", "sinyal", "wifi", "modem", "status", "internet", "kuota"]:
            rest = ""
        cmd = "cek"
    elif cmd in ["ganti", "ubah"]:
        sub = rest.split(maxsplit=1)
        sub_type = sub[0].lower() if sub else ""
        sub_val = sub[1] if len(sub) > 1 else ""
        if sub_type in ["sandi", "password", "pass"]:
            cmd = "pass"
            rest = sub_val
        elif sub_type in ["wifi", "ssid", "nama"]:
            if sub_type == "nama" and sub_val.lower().startswith("wifi "):
                sub_val = sub_val[5:].strip()
            tokens = sub_val.split()
            if len(tokens) >= 2 and sub_type == "wifi":
                cmd = "wifi"
                rest = sub_val
            else:
                cmd = "ssid"
                rest = sub_val
    elif cmd == "klien" and rest.lower().startswith("wifi "):
        rest = rest[5:].strip()

    # 1. Menu & Help
    if cmd in ["menu", "start", "bantuan", "help"]:
        if is_admin:
            menu_text = (
                f"🤖 *{BRAND_NAME} - GenieACS TR-069 AI Bot*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📌 *Daftar Perintah Admin:*\n"
                "• `cek <user_pppoe/sn>` ➔ Status lengkap & redaman ONT\n"
                "• `redaman` ➔ Audit massal redaman kritis (< -26 dBm)\n"
                "• `ontbaru` ➔ Cek modem baru belum tersetting\n"
                "• `klien <user>` ➔ Daftar HP/laptop terhubung WiFi\n"
                "• `reboot <user>` ➔ Restart modem pelanggan\n"
                "• `wifion <user>` & `wifioff <user>` ➔ On/Off Radio WiFi\n"
                "• `wifi <user> <ssid> <sandi>` ➔ Ubah WiFi & Sandi\n"
                "• `ssid <user> <nama>` ➔ Ubah nama WiFi\n"
                "• `pass <user> <sandi>` ➔ Ubah sandi WiFi\n"
                "• `addwan <sn> <user> <pass> [vlan]` ➔ Tambah/Set WAN PPPoE\n"
                "• `superadmin <user> <sandi>` ➔ Ubah sandi web ONT\n"
                "• `ping <user> [host]` ➔ Uji ping TR-069 jarak jauh\n"
                "• `factoryreset <user>` ➔ Reset setelan pabrik\n"
                "• `tag <user> <wa>` ➔ Tautkan nomor WA pelanggan ke modem\n• `untag <user> <wa>` ➔ Hapus nomor WA pelanggan dari modem\n• `server` / `status` ➔ Status CPU, RAM, Suhu STB\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 *CS: {BRAND_NAME} ({BRAND_PHONE})*"
            )
            return (menu_text, get_main_menu_keyboard())
        else:
            if customer_dev:
                pppoe_user = get_device_pppoe_username(customer_dev)
                cust_name = customer_dev.get("_custom_customer_name") or ""
                greeting_header = f" Halo Kak *{cust_name}*!" if cust_name else " Halo!"
                cust_menu = (
                    f"👋 *{greeting_header} Layanan Mandiri WiFi {BRAND_NAME}*\n"
                    f"Modem Terdeteksi: *{pppoe_user}*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Fitur yang dapat Anda gunakan:\n"
                    "• `cek` ➔ Cek nama WiFi, kata sandi & status sinyal\n"
                    "• `wifi <nama_baru> <sandi_baru>` ➔ Ganti nama WiFi & sandi sekaligus\n"
                    "• `pass <sandi_baru>` ➔ Ganti sandi WiFi saja (min. 8 karakter)\n"
                    "• `ssid <nama_baru>` ➔ Ganti nama WiFi saja\n"
                    "• `reboot` ➔ Restart modem jika koneksi internet terasa lambat\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"📞 *Butuh Bantuan Teknisi?* Hubungi CS di {BRAND_PHONE}"
                )
            else:
                clean_s = normalize_phone(sender_id)
                cust_menu = (
                    f"👋 *Halo! Selamat Datang di Layanan Otomatis {BRAND_NAME}*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"Nomor WhatsApp Anda (*{clean_s or sender_id}*) belum terdaftar pada modem mana pun.\n\n"
                    "📝 *Cara Menghubungkan:*\n"
                    "Ketik: `daftar <id_pppoe>`\n"
                    "_Contoh:_ `daftar cucimotor`\n\n"
                    f"Atau hubungi Layanan Bantuan / CS di {BRAND_PHONE}."
                )
            return (cust_menu, None)

    # 2. Cek Redaman Kritis
    if cmd in ["redaman", "los"]:
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin / Teknisi.", None)
        return (get_bad_rx_summary(), get_main_menu_keyboard())

    # 3. Modem Belum Setting / ONT Baru
    if cmd in ["ontbaru", "unconf", "newont"]:
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin / Teknisi.", None)
        return (get_unconfigured_onts(), get_main_menu_keyboard())

    # 4. Cek Server Stats
    if cmd in ["server", "status"]:
        if is_admin:
            return (get_server_stats(), get_main_menu_keyboard())

    # 5. Cek Modem / ONT Status
    if cmd in ["cek", "info"]:
        target = rest
        if not target and registered_tag:
            target = registered_tag

        if not is_admin:
            dev_target = customer_dev or (find_device(target) if target else None)
            if not dev_target:
                return ("⚠️ Nomor WhatsApp Anda belum terhubung ke modem. Ketik `daftar <id_pppoe>` terlebih dahulu.", None)
            return (get_customer_friendly_summary(dev_target), None)

        if not target:
            return ("⚠️ Silakan sertakan Username PPPoE atau Serial Number.\n_Contoh:_ `cek cucimotor`", None)

        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan di database GenieACS.", None)

        pppoe_user, summary_text, wifi_on = get_device_summary(dev)
        dev_id = dev.get("_id")
        kb = get_device_inline_keyboard(pppoe_user, dev_id, wifi_on)
        return (summary_text, kb)

    # 6. Klien WiFi Terhubung
    if cmd in ["klien", "client", "clients"]:
        target = rest or registered_tag
        if not target and not is_admin and customer_dev:
            target = customer_dev.get("_id")
        if not target:
            return ("⚠️ Gunakan: `klien <username_pppoe/sn>`", None)
        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan.", None)
        return (get_device_clients(dev), None)

    # 7. Reboot ONT
    if cmd in ["reboot", "restart"]:
        target = rest or registered_tag
        if not target and not is_admin and customer_dev:
            target = customer_dev.get("_id")
        if not target:
            if not is_admin:
                return ("⚠️ Nomor WhatsApp Anda belum terhubung ke modem mana pun.", None)
            return ("⚠️ Gunakan: `reboot <username_pppoe/sn>`", None)
        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan.", None)
        ok, msg = reboot_device_task(dev)
        if not is_admin and ok:
            p_name = get_device_pppoe_username(dev)
            return (
                f"🔄 *Perintah Restart Terkirim!*\n"
                f"Modem Anda (*{p_name}*) sedang memulai ulang (reboot).\n"
                f"Mohon tunggu sekitar 1-2 menit hingga lampu PON/Internet menyala stabil kembali.",
                None
            )
        return (f"{'✅' if ok else '❌'} {msg}", None)

    # 8. WiFi ON / OFF
    if cmd == "wifioff":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        target = rest
        if not target:
            return ("⚠️ Gunakan: `wifioff <username/sn>`", None)
        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan.", None)
        ok, msg = set_wifi_power(dev, enable=False)
        return (f"{'✅' if ok else '❌'} {msg}", None)

    if cmd == "wifion":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        target = rest
        if not target:
            return ("⚠️ Gunakan: `wifion <username/sn>`", None)
        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan.", None)
        ok, msg = set_wifi_power(dev, enable=True)
        return (f"{'✅' if ok else '❌'} {msg}", None)

    # 9. Ubah WiFi (SSID & Password)
    if cmd == "wifi":
        sub_parts = rest.split()
        if is_admin and len(sub_parts) >= 3:
            target, new_ssid, new_pass = sub_parts[0], sub_parts[1], sub_parts[2]
            dev = find_device(target)
            if not dev:
                return (f"❌ Modem `{target}` tidak ditemukan.", None)
            ok, msg = set_wifi_credentials(dev, new_ssid=new_ssid, new_password=new_pass)
            if ok:
                return (f"✅ *Berhasil Mengubah Pengaturan WiFi!*\n• Pelanggan: `{target}`\n• SSID: `{new_ssid}`\n• Sandi: `{new_pass}`\nStatus: Terkirim via TR-069.", None)
            return (f"❌ Gagal: {msg}", None)
        elif not is_admin:
            dev_target = customer_dev or (find_device(registered_tag) if registered_tag else None)
            if not dev_target:
                return ("⚠️ Nomor Anda belum terhubung ke modem mana pun. Ketik `daftar <id_pppoe>` terlebih dahulu.", None)
            if len(sub_parts) < 2:
                return ("⚠️ Format salah. Gunakan:\n`wifi <nama_wifi_baru> <sandi_baru>`\n_Contoh:_ `wifi MyHome SandiRahasia123`", None)
            new_ssid, new_pass = sub_parts[0], sub_parts[1]
            if len(new_pass) < 8:
                return ("⚠️ Kata sandi WiFi minimal harus 8 karakter demi keamanan WPA2-PSK.\n_Contoh:_ `wifi MyHome SandiRahasia123`", None)
            ok, msg = set_wifi_credentials(dev_target, new_ssid=new_ssid, new_password=new_pass)
            if ok:
                return (
                    f"✅ *WiFi Anda Berhasil Diperbarui!*\n"
                    f"• Nama WiFi Baru : *{new_ssid}*\n"
                    f"• Sandi Baru : *{new_pass}*\n\n"
                    f"Pengaturan telah dikirim ke modem. Silakan sambungkan kembali perangkat HP/Laptop Anda dengan kata sandi baru.",
                    None
                )
            return (f"❌ Gagal memperbarui WiFi: {msg}", None)
        else:
            if is_admin:
                return ("⚠️ Format salah. Gunakan:\n`wifi <user> <nama_wifi_baru> <sandi_baru>`\n_Contoh:_ `wifi cucimotor Alijaya-Net 12345678`", None)
            else:
                return ("⚠️ Format salah. Gunakan:\n`wifi <nama_wifi_baru> <sandi_baru>`\n_Contoh:_ `wifi WiFi-Saya SandiRahasia123`", None)

    # 10. Ubah SSID saja
    if cmd == "ssid":
        if is_admin:
            sub_parts = rest.split(maxsplit=1)
            if len(sub_parts) >= 2:
                target, new_ssid = sub_parts[0], sub_parts[1]
                dev = find_device(target)
                if not dev:
                    return (f"❌ Modem `{target}` tidak ditemukan.", None)
                ok, msg = set_wifi_credentials(dev, new_ssid=new_ssid)
                if ok:
                    return (f"✅ *Berhasil Mengubah SSID!*\n• Pelanggan: `{target}`\n• SSID Baru: `{new_ssid}`", None)
                return (f"❌ Gagal: {msg}", None)
            return ("⚠️ Gunakan: `ssid <username_pppoe> <nama_baru>`", None)
        else:
            dev_target = customer_dev or (find_device(registered_tag) if registered_tag else None)
            if not dev_target:
                return ("⚠️ Nomor Anda belum terhubung ke modem mana pun. Ketik `daftar <id_pppoe>` terlebih dahulu.", None)
            if not rest:
                return ("⚠️ Format salah. Gunakan:\n`ssid <nama_wifi_baru>`\n_Contoh:_ `ssid MyHome-WiFi`", None)
            new_ssid = rest.strip()
            ok, msg = set_wifi_credentials(dev_target, new_ssid=new_ssid)
            if ok:
                return (
                    f"✅ *Nama WiFi Berhasil Diubah!*\n"
                    f"• Nama WiFi Baru : *{new_ssid}*\n\n"
                    f"Pengaturan telah dikirim ke modem. Silakan sambungkan kembali perangkat HP Anda.",
                    None
                )
            return (f"❌ Gagal mengubah nama WiFi: {msg}", None)

    # 11. Ubah Password saja
    if cmd in ["pass", "password", "sandi"]:
        if is_admin:
            sub_parts = rest.split(maxsplit=1)
            if len(sub_parts) >= 2:
                target, new_pass = sub_parts[0], sub_parts[1]
                if len(new_pass) < 8:
                    return ("⚠️ Kata sandi minimal 8 karakter.", None)
                dev = find_device(target)
                if not dev:
                    return (f"❌ Modem `{target}` tidak ditemukan.", None)
                ok, msg = set_wifi_credentials(dev, new_password=new_pass)
                if ok:
                    return (f"✅ *Berhasil Mengubah Sandi WiFi!*\n• Pelanggan: `{target}`\n• Sandi Baru: `{new_pass}`", None)
                return (f"❌ Gagal: {msg}", None)
            return ("⚠️ Gunakan: `pass <username_pppoe> <sandi_baru>`", None)
        else:
            dev_target = customer_dev or (find_device(registered_tag) if registered_tag else None)
            if not dev_target:
                return ("⚠️ Nomor Anda belum terhubung ke modem mana pun. Ketik `daftar <id_pppoe>` terlebih dahulu.", None)
            if not rest:
                return ("⚠️ Format salah. Gunakan:\n`pass <sandi_baru>`\n_Contoh:_ `pass SandiRahasia123`", None)
            new_pass = rest.split()[0].strip()
            if len(new_pass) < 8:
                return ("⚠️ Kata sandi minimal harus 8 karakter demi keamanan WPA2-PSK.\n_Contoh:_ `pass SandiRahasia123`", None)
            ok, msg = set_wifi_credentials(dev_target, new_password=new_pass)
            if ok:
                return (
                    f"✅ *Kata Sandi WiFi Berhasil Diubah!*\n"
                    f"• Kata Sandi Baru : *{new_pass}*\n\n"
                    f"Pengaturan telah dikirim ke modem. Silakan sambungkan kembali perangkat HP/Laptop Anda dengan kata sandi baru.",
                    None
                )
            return (f"❌ Gagal mengubah kata sandi: {msg}", None)

    # 12. Add/Set WAN PPPoE
    if cmd == "addwan":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        sub_parts = rest.split()
        if len(sub_parts) >= 3:
            target = sub_parts[0]
            pppoe_user = sub_parts[1]
            pppoe_pass = sub_parts[2]
            vlan_id = sub_parts[3] if len(sub_parts) > 3 else None
            dev = find_device(target)
            if not dev:
                return (f"❌ Modem `{target}` tidak ditemukan.", None)
            ok, msg = add_or_set_wan_pppoe(dev, pppoe_user, pppoe_pass, vlan_id)
            return (f"{'✅' if ok else '❌'} {msg}", None)
        return ("⚠️ Format salah. Gunakan:\n`addwan <sn/user> <user_pppoe> <pass_pppoe> [vlan_id]`", None)

    # 13. Superadmin Password
    if cmd == "superadmin":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        sub_parts = rest.split(maxsplit=1)
        if len(sub_parts) >= 2:
            target, new_pass = sub_parts[0], sub_parts[1]
            dev = find_device(target)
            if not dev:
                return (f"❌ Modem `{target}` tidak ditemukan.", None)
            ok, msg = set_superadmin_password(dev, new_pass)
            return (f"{'✅' if ok else '❌'} {msg}", None)
        return ("⚠️ Gunakan: `superadmin <username/sn> <password_baru>`", None)

    # 14. Factory Reset
    if cmd == "factoryreset":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        target = rest
        if not target:
            return ("⚠️ Gunakan: `factoryreset <username/sn>`", None)
        dev = find_device(target)
        if not dev:
            return (f"❌ Modem `{target}` tidak ditemukan.", None)
        ok, msg = factory_reset_device(dev)
        return (f"{'✅' if ok else '❌'} {msg}", None)

    # 15. Ping Diagnostics
    if cmd == "ping":
        sub_parts = rest.split()
        if sub_parts:
            target = sub_parts[0]
            host = sub_parts[1] if len(sub_parts) > 1 else "8.8.8.8"
            dev = find_device(target)
            if not dev:
                return (f"❌ Modem `{target}` tidak ditemukan.", None)
            ok, msg = ping_diagnostics_task(dev, host)
            return (f"{'✅' if ok else '❌'} {msg}", None)
        return ("⚠️ Gunakan: `ping <username/sn> [host]`", None)

    # 15.5. Tagging Nomor WhatsApp Pelanggan (Admin)
    if cmd == "tag":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        sub_parts = rest.split()
        if len(sub_parts) < 2:
            return ("⚠️ Format salah. Gunakan:\n`tag <username_pppoe/sn> <nomor_wa>`\n_Contoh:_ `tag cucimotor 081234567890`", None)
        target_user, raw_phone = sub_parts[0], sub_parts[1]
        dev = find_device(target_user)
        if not dev:
            return (f"❌ Modem `{target_user}` tidak ditemukan.", None)
        clean_phone = normalize_phone(raw_phone)
        if len(clean_phone) < 8:
            return (f"⚠️ Nomor WhatsApp `{raw_phone}` tidak valid.", None)
        add_device_tag(dev["_id"], clean_phone)
        pppoe_name = get_device_pppoe_username(dev)
        return (
            f"✅ *Tag WhatsApp Berhasil Ditambahkan!*\n"
            f"• Pelanggan : `{pppoe_name}`\n"
            f"• Device ID : `{dev.get('_id')}`\n"
            f"• Nomor Tag : `{clean_phone}`\n\n"
            f"Pelanggan kini dapat langsung chat bot untuk cek status & ubah WiFi secara mandiri!",
            None
        )

    if cmd == "untag":
        if not is_admin:
            return ("⛔ Perintah ini khusus untuk Admin.", None)
        sub_parts = rest.split()
        if len(sub_parts) < 2:
            return ("⚠️ Format salah. Gunakan:\n`untag <username_pppoe/sn> <nomor_wa>`\n_Contoh:_ `untag cucimotor 081234567890`", None)
        target_user, raw_phone = sub_parts[0], sub_parts[1]
        dev = find_device(target_user)
        if not dev:
            return (f"❌ Modem `{target_user}` tidak ditemukan.", None)
        clean_phone = normalize_phone(raw_phone)
        remove_device_tag(dev["_id"], clean_phone)
        return (f"🗑️ Tag `{clean_phone}` berhasil dihapus dari modem `{target_user}`.", None)

    # 15.6. Pendaftaran Mandiri Pelanggan (Customer Self-Registration)
    if cmd == "daftar":
        if not rest:
            return ("⚠️ Format salah. Gunakan:\n`daftar <id_pppoe>`\n_Contoh:_ `daftar cucimotor`", None)
        target_user = rest.split()[0]
        dev = find_device(target_user)
        if not dev:
            return (f"❌ Pelanggan `{target_user}` tidak ditemukan di sistem GenieACS. Pastikan ID PPPoE Anda benar.", None)
        clean_phone = normalize_phone(sender_id)
        if clean_phone and len(clean_phone) >= 8:
            add_device_tag(dev["_id"], clean_phone)
        pppoe_name = get_device_pppoe_username(dev)
        return (
            f"✅ *Pendaftaran Layanan Mandiri Berhasil!*\n"
            f"Nomor WhatsApp Anda (*{clean_phone or sender_id}*) kini telah terhubung ke modem: *{pppoe_name}*.\n\n"
            f"Silakan gunakan perintah mandiri berikut kapan saja:\n"
            f"• `cek` ➔ Cek nama WiFi, kata sandi & status sinyal\n"
            f"• `wifi <nama_baru> <sandi_baru>` ➔ Ganti nama & sandi WiFi\n"
            f"• `pass <sandi_baru>` ➔ Ganti sandi WiFi saja (min. 8 karakter)\n"
            f"• `ssid <nama_baru>` ➔ Ganti nama WiFi saja\n"
            f"• `reboot` ➔ Restart modem jika koneksi lambat",
            None
        )

    # 16. Fallback Respon Cerdas Sesuai Hak Akses Pengirim
    if is_admin:
        # ADMIN: Selalu dijawab AI / DevOps (tidak butuh tanda tanya)
        if gemini_key and is_valid_token(gemini_key):
            ai_reply = ask_gemini_ai(gemini_key, gemini_model, raw, sender_id, is_admin=True)
            if ai_reply:
                return (ai_reply, None)
        # Fallback heuristic jika tanpa API key atau AI selesai tanpa teks
        fallback_rep = fallback_admin_intent(raw)
        if fallback_rep:
            return (fallback_rep, None)
        return (f"⚠️ Perintah `{raw}` tidak dikenali. Ketik `menu` untuk melihat daftar perintah.", get_main_menu_keyboard())

    elif is_customer:
        # PELANGGAN TERDAFTAR: Harus sesuai perintah saja!
        # Jika chat biasa (halo, lagi dimana, makasih, p, stiker, dsb), BOT DIAM (TIDAK MENJAWAB)
        # agar admin / pemilik WA dapat membalas secara langsung tanpa terinterupsi bot.
        return (None, None)

    else:
        # BUKAN ADMIN & BUKAN PELANGGAN (Nomor Luar / Calon Pelanggan / Nomor Asing):
        # HANYA dijawab AI jika terdapat tanda tanya (?) dalam pesan.
        has_question = ("?" in raw) or ("？" in raw)
        if has_question:
            if gemini_key and is_valid_token(gemini_key):
                ai_reply = ask_gemini_ai(gemini_key, gemini_model, raw, sender_id, is_admin=False)
                if ai_reply:
                    return (ai_reply, None)
            # Pesan standar Customer Service jika tanpa API key atau AI kosong
            cs_reply = (
                f"Halo! Untuk info seputar pemasangan baru, paket internet WiFi, atau bantuan layanan, "
                f"bisa langsung hubungi CS kami di nomor {BRAND_PHONE} ya kak."
            )
            return (cs_reply, None)
        else:
            # Tidak ada tanda tanya '?' (chat biasa, sapaan 'P', pesan pribadi, broadcast) -> BOT DIAM (TIDAK MENJAWAB)
            return (None, None)


def handle_incoming_message(token, chat_id, user_text, gemini_key, model_name, is_voice=False):
    txt = user_text.strip()
    state = USER_STATES.get(chat_id)
    cid_str = str(chat_id)

    # Toggle Mode Suara Permanen
    if txt.lower() in ["/voice on", "/suara on", "voice on", "suara on"]:
        VOICE_PERSISTENT_USERS.add(cid_str)
        send_telegram(token, chat_id, "🎙️ *Mode Suara Aktif!*\nSemua balasan bot akan dikirim dalam bentuk Teks + Pesan Suara (Voice Note).", reply_markup=get_main_menu_keyboard(), send_voice_also=True)
        return

    if txt.lower() in ["/voice off", "/suara off", "voice off", "suara off"]:
        VOICE_PERSISTENT_USERS.discard(cid_str)
        VOICE_SESSION_USERS.discard(cid_str)
        send_telegram(token, chat_id, "🔇 *Mode Suara Dinonaktifkan.*\nBalasan bot kembali ke format Teks standar.", reply_markup=get_main_menu_keyboard())
        return

    # Aktifkan session suara jika request berasal dari pesan suara
    if is_voice:
        VOICE_SESSION_USERS.add(cid_str)

    # Cancel command
    if txt.lower() in ["/batal", "/cancel", "batal", "cancel"]:
        USER_STATES.pop(chat_id, None)
        send_telegram(token, chat_id, "✅ Operasi dibatalkan.", reply_markup=get_main_menu_keyboard())
        return

    # Menu Buttons Handlers khusus Telegram
    if txt in ["🔍 Cek Modem"]:
        USER_STATES[chat_id] = {"action": "wait_cek"}
        send_telegram(token, chat_id, "🔍 *Cek Modem*: Silakan ketik Username PPPoE atau Serial Number (contoh: `cucimotor`):", reply_markup=get_main_menu_keyboard())
        return

    if txt in ["⚠️ Cek Redaman Kritis", "/redaman", "/los"]:
        USER_STATES.pop(chat_id, None)
        send_telegram(token, chat_id, get_bad_rx_summary(), reply_markup=get_main_menu_keyboard())
        return

    if txt in ["🆕 Modem Belum Setting", "/ontbaru", "/unconf"]:
        USER_STATES.pop(chat_id, None)
        send_telegram(token, chat_id, get_unconfigured_onts(), reply_markup=get_main_menu_keyboard())
        return

    if txt in ["📊 Status Server STB", "📊 Status Server", "/server", "/status", "status", "server"]:
        USER_STATES.pop(chat_id, None)
        send_telegram(token, chat_id, get_server_stats(), reply_markup=get_main_menu_keyboard())
        return

    if txt in ["❓ Bantuan / Help", "/help", "/menu", "/start", "menu", "help", "bantuan"]:
        USER_STATES.pop(chat_id, None)
        reply_text, markup = process_agent_command("menu", sender_id=chat_id, is_admin=True)
        send_telegram(token, chat_id, reply_text, reply_markup=markup or get_main_menu_keyboard())
        return

    if txt in ["👥 Daftar Klien WiFi", "👥 Cek Klien", "/klien"]:
        USER_STATES[chat_id] = {"action": "wait_klien"}
        send_telegram(token, chat_id, "👥 *Daftar Klien Terhubung*: Silakan ketik Username PPPoE atau Serial Number (contoh: `cucimotor`):", reply_markup=get_main_menu_keyboard())
        return

    if txt in ["🔄 Reboot Modem", "/reboot"]:
        USER_STATES[chat_id] = {"action": "wait_reboot"}
        send_telegram(token, chat_id, "🔄 *Reboot Modem*: Silakan ketik Username PPPoE atau Serial Number modem yang ingin di-restart (contoh: `cucimotor`):", reply_markup=get_main_menu_keyboard())
        return

    if txt in ["🌐 Tambah / Set WAN", "/addwan"]:
        USER_STATES[chat_id] = {"action": "wait_wan_add"}
        wan_guide = (
            "🌐 *Tambah / Konfigurasi WAN PPPoE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan ketik data dengan format:\n"
            "`<sn_modem> <user_pppoe> <password_pppoe> [vlan_id]`\n\n"
            "📌 *Contoh Tanpa VLAN:*\n"
            "`ZTEGC1234567 cucimotor 12345678`\n\n"
            "📌 *Contoh Dengan VLAN:*\n"
            "`ZTEGC1234567 cucimotor 12345678 100`\n\n"
            "_(Ketik langsung format di atas untuk mengeksekusi)_"
        )
        send_telegram(token, chat_id, wan_guide, reply_markup=get_main_menu_keyboard())
        return

    if txt in ["📶 Ubah WiFi / Sandi", "/wifi"]:
        USER_STATES.pop(chat_id, None)
        wifi_guide = (
            "📶 *Ubah Pengaturan WiFi Pelanggan*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan gunakan salah satu format perintah berikut:\n\n"
            "1️⃣ *Ubah Nama & Sandi WiFi Sekaligus:*\n"
            "`wifi <user_pppoe> <nama_wifi_baru> <sandi_baru>`\n"
            "_Contoh:_ `wifi cucimotor Alijaya-Net 12345678`\n\n"
            "2️⃣ *Ubah Nama WiFi (SSID) Saja:*\n"
            "`ssid <user_pppoe> <nama_wifi_baru>`\n"
            "_Contoh:_ `ssid cucimotor Alijaya-Net`\n\n"
            "3️⃣ *Ubah Sandi WiFi Saja (min. 8 Karakter):*\n"
            "`pass <user_pppoe> <sandi_baru>`\n"
            "_Contoh:_ `pass cucimotor 12345678`\n\n"
            "_(Atau ketik `/cek <user>` untuk mengubah tombol interaktif per perangkat)_"
        )
        send_telegram(token, chat_id, wifi_guide, reply_markup=get_main_menu_keyboard())
        return

    # Check conversation states jika ada aksi interaktif sebelumnya
    if state and state.get("action") == "wait_cek":
        USER_STATES.pop(chat_id, None)
        dev = find_device(txt)
        if not dev:
            send_telegram(token, chat_id, f"❌ Modem `{txt}` tidak ditemukan di database GenieACS.", reply_markup=get_main_menu_keyboard())
            return
        pppoe_user, summary_text, wifi_on = get_device_summary(dev)
        dev_id = dev.get("_id")
        send_telegram(token, chat_id, summary_text, reply_markup=get_device_inline_keyboard(pppoe_user, dev_id, wifi_on))
        return

    if state and state.get("action") == "wait_klien":
        USER_STATES.pop(chat_id, None)
        dev = find_device(txt)
        if not dev:
            send_telegram(token, chat_id, f"❌ Modem `{txt}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
            return
        send_telegram(token, chat_id, get_device_clients(dev), reply_markup=get_main_menu_keyboard())
        return

    if state and state.get("action") == "wait_reboot":
        USER_STATES.pop(chat_id, None)
        dev = find_device(txt)
        if not dev:
            send_telegram(token, chat_id, f"❌ Modem `{txt}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
            return
        ok, msg = reboot_device_task(dev)
        send_telegram(token, chat_id, f"{'✅' if ok else '❌'} {msg}", reply_markup=get_main_menu_keyboard())
        return

    if state and state.get("action") == "wait_wan_add":
        USER_STATES.pop(chat_id, None)
        parts = txt.split()
        if len(parts) >= 3:
            target = parts[0]
            pppoe_user = parts[1]
            pppoe_pass = parts[2]
            vlan_id = parts[3] if len(parts) > 3 else None
            dev = find_device(target)
            if not dev:
                send_telegram(token, chat_id, f"❌ Modem `{target}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
                return
            ok, msg = add_or_set_wan_pppoe(dev, pppoe_user, pppoe_pass, vlan_id)
            send_telegram(token, chat_id, f"{'✅' if ok else '❌'} {msg}", reply_markup=get_main_menu_keyboard())
            return
        else:
            send_telegram(token, chat_id, "⚠️ Format salah. Harap ketik: `<sn_modem> <user_pppoe> <password_pppoe> [vlan_id]`", reply_markup=get_main_menu_keyboard())
            return

    if state and state.get("action") == "wait_ssid":
        target = state.get("target")
        USER_STATES.pop(chat_id, None)
        dev = find_device(target)
        if not dev:
            send_telegram(token, chat_id, f"❌ Modem `{target}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
            return
        ok, msg = set_wifi_credentials(dev, new_ssid=txt)
        if ok:
            send_telegram(token, chat_id, f"✅ *Berhasil Mengubah SSID!*\n• Pelanggan: `{target}`\n• SSID Baru: `{txt}`", reply_markup=get_main_menu_keyboard())
        else:
            send_telegram(token, chat_id, f"❌ Gagal: {msg}", reply_markup=get_main_menu_keyboard())
        return

    if state and state.get("action") == "wait_pass":
        target = state.get("target")
        USER_STATES.pop(chat_id, None)
        if len(txt) < 8:
            send_telegram(token, chat_id, "⚠️ Sandi WiFi minimal harus 8 karakter.", reply_markup=get_main_menu_keyboard())
            return
        dev = find_device(target)
        if not dev:
            send_telegram(token, chat_id, f"❌ Modem `{target}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
            return
        ok, msg = set_wifi_credentials(dev, new_password=txt)
        if ok:
            send_telegram(token, chat_id, f"✅ *Berhasil Mengubah Sandi WiFi!*\n• Pelanggan: `{target}`\n• Sandi Baru: `{txt}`", reply_markup=get_main_menu_keyboard())
        else:
            send_telegram(token, chat_id, f"❌ Gagal: {msg}", reply_markup=get_main_menu_keyboard())
        return

    if state and state.get("action") == "wait_wan":
        target = state.get("target")
        USER_STATES.pop(chat_id, None)
        parts = txt.split()
        if len(parts) >= 2:
            p_user = parts[0]
            p_pass = parts[1]
            p_vlan = parts[2] if len(parts) > 2 else None
            dev = find_device(target)
            if not dev:
                send_telegram(token, chat_id, f"❌ Modem `{target}` tidak ditemukan.", reply_markup=get_main_menu_keyboard())
                return
            ok, msg = add_or_set_wan_pppoe(dev, p_user, p_pass, p_vlan)
            send_telegram(token, chat_id, f"{'✅' if ok else '❌'} {msg}", reply_markup=get_main_menu_keyboard())
            return
        else:
            send_telegram(token, chat_id, "⚠️ Format salah. Harap ketik: `<user_pppoe> <password_pppoe> [vlan_id]`", reply_markup=get_main_menu_keyboard())
            return

    # Jalankan perintah melalui unified command processor
    reply_text, markup = process_agent_command(
        user_text=txt,
        sender_id=chat_id,
        is_admin=True,
        gemini_key=gemini_key,
        gemini_model=model_name
    )
    if reply_text:
        send_telegram(token, chat_id, reply_text, reply_markup=markup or get_main_menu_keyboard())


def check_proactive_alerts(token, admin_ids):
    try:
        db = get_db()
        if db is None:
            return
            
        cursor = db.devices.find({"VirtualParameters.RXPower": {"$exists": True}})
        for d in cursor:
            vp = d.get("VirtualParameters", {})
            rx_dict = vp.get("RXPower", {})
            rx_val = rx_dict.get("_value") if isinstance(rx_dict, dict) else None
            
            if rx_val is None:
                continue
                
            try:
                rx_float = float(rx_val)
                dev_id = d.get("_id", "Unknown")
                pppoe = vp.get("pppoeUsername", {}).get("_value") if isinstance(vp.get("pppoeUsername"), dict) else dev_id
                
                if rx_float < -27.0 or rx_float > -8.0:
                    alert_key = f"{dev_id}_bad_rx"
                    last_alert = ALERT_HISTORY.get(alert_key, 0)
                    now = time.time()
                    
                    if (now - last_alert) > 3600:
                        ALERT_HISTORY[alert_key] = now
                        drop_msg = (
                            f"🚨 *[ALERT REDAMAN DROP KRITIS]*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"• *Pelanggan*: `{pppoe.upper()}`\n"
                            f"• *Redaman Saat Ini*: `{rx_val} dBm` 🔴\n"
                            f"• *Penyebab*: Kemungkinan kabel optik terjepit, kotor, atau patchcord bermasalah.\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"👉 _Segera lakukan pengecekan fisik di lapangan._"
                        )
                        for aid in admin_ids:
                            send_telegram(token, aid, drop_msg)

                        # Kirim notifikasi ke WhatsApp Admin jika aktif
                        try:
                            cfgs = get_config()
                            wa_enabled = cfgs.get("agent.whatsapp.enabled", "true").lower() == "true"
                            wa_admins = cfgs.get("agent.whatsapp.admin_numbers", BRAND_PHONE)
                            if wa_enabled and wa_admins:
                                wa_list = [w.strip() for w in wa_admins.replace(";", ",").split(",") if w.strip()]
                                for wa_no in wa_list:
                                    requests.post("http://127.0.0.1:7559/send", json={"to": wa_no, "text": drop_msg}, timeout=2.0)
                        except Exception:
                            pass
            except Exception:
                pass
                
    except Exception as e:
        logger.error(f"Error in watchdog: {e}")


HTML_CONFIG_PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pengaturan Bot AI & WhatsApp - ALIJAYA NET</title>
  <style>
    :root {
      --bg: #050833;
      --card: #080d22;
      --card-inner: #040714;
      --border: #1c274c;
      --primary: #00e5ff;
      --primary-btn: #046380;
      --primary-hover: #00b4d8;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif; }
    html { min-height: 100vh; background-color: var(--bg); }
    body { background-color: transparent; color: var(--text); padding: 14px; display: flex; justify-content: center; }
    .container { width: 100%; max-width: 860px; background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 22px; box-shadow: 0 4px 25px rgba(0,0,0,0.45); }
    
    .header { text-align: center; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 14px; position: relative; }
    .header h2 { font-size: 1.35rem; color: var(--primary); display: flex; align-items: center; justify-content: center; gap: 8px; font-weight: 700; letter-spacing: 0.3px; }
    .header p { color: var(--text-muted); font-size: 0.84rem; margin-top: 4px; }
    .btn-header-logout {
      position: absolute; right: 0; top: 0;
      background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35);
      color: #fca5a5; padding: 5px 12px; border-radius: 6px; cursor: pointer;
      font-size: 0.78rem; font-weight: 600; transition: all 0.2s;
    }
    .btn-header-logout:hover { background: #ef4444; color: #fff; }

    /* Tabs Navigation */
    .tabs { display: flex; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
    .tab-btn { flex: 1; padding: 10px 14px; background: var(--card-inner); border: 1px solid var(--border); border-radius: 6px; color: var(--text-muted); font-weight: 600; font-size: 0.88rem; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
    .tab-btn:hover { background: #0f1c3f; color: #fff; }
    .tab-btn.active { background: var(--primary-btn); color: #fff; border-color: var(--primary); font-weight: 700; box-shadow: 0 0 10px rgba(0,229,255,0.25); }
    
    .tab-pane { display: none; }
    .tab-pane.active { display: block; animation: fadeIn 0.2s ease-in-out; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

    .form-group { margin-bottom: 16px; }
    label { display: block; font-size: 0.86rem; font-weight: 600; margin-bottom: 6px; color: var(--text); }
    .hint { font-size: 0.78rem; color: var(--text-muted); margin-top: 4px; line-height: 1.4; }
    input[type="text"], input[type="password"], select, textarea {
      width: 100%; padding: 10px 14px; background: var(--card-inner); border: 1px solid var(--border); border-radius: 6px; color: #fff; font-size: 0.92rem; outline: none; transition: border-color 0.2s, box-shadow 0.2s;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--primary); box-shadow: 0 0 8px rgba(0, 229, 255, 0.35); }
    textarea { resize: vertical; min-height: 60px; }

    /* WhatsApp Status Card */
    .status-card { background: var(--card-inner); border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-bottom: 18px; text-align: center; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; margin-bottom: 10px; }
    .badge-open { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid var(--success); }
    .badge-qr { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid var(--warning); }
    .badge-connecting { background: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid var(--primary); }
    .badge-disconnected { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid var(--danger); }

    .qr-box { margin-top: 12px; }
    .qr-box img { width: 230px; height: 230px; background: #fff; padding: 8px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.6); }

    .btn-row { display: flex; gap: 12px; margin-top: 22px; }
    button { flex: 1; padding: 11px 16px; border: none; border-radius: 6px; font-weight: 600; font-size: 0.92rem; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; }
    .btn-save { background: linear-gradient(135deg, #046380 0%, #0891b2 100%); color: #fff; font-weight: 700; border: 1px solid #00e5ff; box-shadow: 0 2px 8px rgba(4,99,128,0.4); }
    .btn-save:hover { background: #00e5ff; color: #000; box-shadow: 0 0 14px rgba(0,229,255,0.6); }
    .btn-test { background: #131e3d; border: 1px solid #23355e; color: #e2e8f0; }
    .btn-test:hover { background: #1c2b54; color: #fff; }
    .btn-logout { background: #450a0a; color: #fca5a5; border: 1px solid #ef4444; padding: 6px 14px; font-size: 0.85rem; border-radius: 6px; margin-top: 10px; display: inline-flex; }
    .btn-logout:hover { background: #7f1d1d; color: #fff; }
    .btn-reset-wa {
      background: #450a0a;
      color: #fca5a5;
      border: 1px solid #dc2626;
      padding: 9px 18px;
      font-size: 0.88rem;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .btn-reset-wa:hover {
      background: #7f1d1d;
      color: #fff;
      box-shadow: 0 0 10px rgba(220,38,38,0.4);
    }

    .alert { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9rem; display: none; }
    .alert-success { background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success); color: #34d399; }
    .alert-error { background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger); color: #f87171; }
    .back-link { display: inline-block; margin-top: 18px; text-decoration: none; color: var(--primary); font-size: 0.85rem; font-weight: 500; }
    .back-link:hover { text-decoration: underline; }

    .version-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 18px; }
    @media (max-width: 600px) {
      .version-grid { grid-template-columns: 1fr; }
    }

    /* In-Iframe styling: seamlessly blend with GenieACS SPA */
    body.in-iframe { padding: 8px 12px; }
    body.in-iframe .container { max-width: 100%; border: 1px solid var(--border); box-shadow: none; background: rgba(8, 13, 34, 0.85); }
    body.in-iframe #backToAcs { display: none !important; }
  </style></head>
<body>
  <div class="container">
    <div class="header">
      <div style="display: flex; align-items: center; justify-content: space-between; position: relative;">
        <h2 style="margin: 0 auto; display: flex; align-items: center; gap: 8px;">🤖 Pengaturan Bot AI & WhatsApp</h2>
        <button type="button" onclick="handleAdminLogout()" class="btn-header-logout">🚪 Logout</button>
      </div>
      <p>Panel Kontrol TR-069 GenieACS, Bot Telegram & Gateway WhatsApp Baileys</p>
    </div>

    <div id="alertBox" class="alert"></div>

    <div class="tabs">
      <button type="button" class="tab-btn active" onclick="switchTab('tab-wa')">📱 WhatsApp (Baileys)</button>
      <button type="button" class="tab-btn" onclick="switchTab('tab-tg')">✈️ Telegram Bot</button>
      <button type="button" class="tab-btn" onclick="switchTab('tab-brand')">🏢 Brand & AI</button>
      <button type="button" class="tab-btn" onclick="switchTab('tab-update')">🔄 Sistem & Update</button>
    </div>

    <form id="botForm">
      <!-- TAB 1: WHATSAPP (BAILEYS) -->
      <div id="tab-wa" class="tab-pane active">
        <div class="status-card">
          <span id="waBadge" class="badge badge-connecting">MEMUAT STATUS...</span>
          
          <div id="waConnectedBox" style="display: none;">
            <p style="color: #34d399; font-weight: 600; font-size: 1.05rem;">✅ Bot WhatsApp Siap Digunakan</p>
            <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">Akun: <b id="waUser" style="color: #fff;">-</b></p>
            <button type="button" class="btn-logout" onclick="logoutWA()">🔴 Putus Koneksi / Logout</button>
          </div>

          <div id="waQrBox" class="qr-box" style="display: none;">
            <p style="font-size: 0.88rem; color: #fbbf24; font-weight: 600; margin-bottom: 6px;">📷 Pindai Kode QR WhatsApp</p>
            <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px;">Buka WhatsApp di HP ➔ <b>Perangkat Tertaut</b> ➔ <b>Tautkan Perangkat</b></p>
            <img id="waQrImg" src="" alt="WhatsApp QR Code" />
            <p style="font-size: 0.75rem; color: var(--primary); margin-top: 8px;">Auto-refresh aktif setiap 3 detik 🔄</p>
          </div>

          <div id="waOfflineBox" style="display: none;">
            <p style="color: #f87171; font-size: 0.88rem;">⚠️ Service WhatsApp belum aktif di port 7559.<br>Pastikan daemon <code>genieacs-whatsapp.service</code> sedang berjalan.</p>
          </div>

          <div class="session-actions" style="margin-top: 18px; border-top: 1px solid var(--border); padding-top: 14px; text-align: center;">
            <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 8px;">
              Ingin mengganti nomor bot WhatsApp baru atau membuat ulang QR Code?
            </p>
            <button type="button" class="btn-reset-wa" onclick="resetWA()">
              🗑️ Hapus Sesi WhatsApp (Ganti Nomor Bot / Buat QR Baru)
            </button>
          </div>
        </div>

        <div class="form-group">
          <label>Status Layanan Bot WhatsApp:</label>
          <select id="wa_enabled" name="wa_enabled">
            <option value="true">Aktif (Enabled) 🟢</option>
            <option value="false">Nonaktif (Disabled) 🔴</option>
          </select>
        </div>

        <div class="form-group">
          <label>Nomor WhatsApp Admin / Teknisi:</label>
          <textarea id="wa_admin_numbers" name="wa_admin_numbers" placeholder="Contoh: 081947215703, 081234567890"></textarea>
          <div class="hint">Nomor yang memiliki hak akses perintah administratif (cek, redaman, reboot, wifion/off, ssid, dll). Pisahkan koma jika lebih dari satu.</div>
        </div>

        <div style="background: var(--card-inner); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 14px; margin-bottom: 6px;">
          <h4 style="font-size: 0.92rem; color: #38bdf8; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
            📶 Layanan OTP WhatsApp (Portal Mandiri WiFi Pelanggan)
          </h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px; line-height: 1.4;">
            Pelanggan login ke web mandiri (ubah nama WiFi / password / cek redaman) menggunakan kode OTP 4 digit yang dikirimkan otomatis via WhatsApp.
          </p>

          <div class="form-group" style="margin-bottom: 14px;">
            <label>Metode Verifikasi Login Pelanggan:</label>
            <select id="otp_enabled" name="otp_enabled" onchange="toggleOtpExpiryVisibility()">
              <option value="true">Gunakan Kode OTP WhatsApp (Wajib OTP 4 Digit) 🟢</option>
              <option value="false">Tanpa OTP (Cukup Masukkan Nomor Pelanggan / HP) 🟡</option>
            </select>
            <div class="hint">
              • <b>Gunakan Kode OTP WhatsApp</b>: Pelanggan wajib verifikasi kode OTP 4 digit yang dikirim via WhatsApp.<br>
              • <b>Tanpa OTP</b>: Pelanggan bisa langsung login ke dashboard WiFi hanya dengan mengetik nomor pelanggan / WhatsApp tanpa perlu kode OTP.
            </div>
          </div>

          <div class="form-group" id="otpExpiryGroup" style="margin-bottom: 0;">
            <label>Waktu Expired Kode OTP (Menit):</label>
            <input type="number" id="otp_expiry_minutes" name="otp_expiry_minutes" min="1" max="60" value="5" placeholder="Contoh: 5">
            <div class="hint">Berapa menit kode OTP 4 digit berlaku sebelum kedaluwarsa (default: 5 menit). Berlaku saat mode OTP WhatsApp aktif.</div>
          </div>
        </div>
      </div>

      <!-- TAB 2: TELEGRAM BOT -->
      <div id="tab-tg" class="tab-pane">
        <div class="form-group">
          <label>Status Layanan Bot Telegram:</label>
          <select id="bot_enabled" name="enabled">
            <option value="true">Aktif (Enabled) 🟢</option>
            <option value="false">Nonaktif (Disabled) 🔴</option>
          </select>
        </div>

        <div class="form-group">
          <label>Token Bot Telegram:</label>
          <input type="text" id="bot_token" name="token" placeholder="Contoh: 123456789:AAFMD7X_xxxxxxxxxxxxxx">
          <div class="hint">Dapatkan dari @BotFather di Telegram.</div>
        </div>

        <div class="form-group">
          <label>Admin Chat ID / ID Grup Telegram:</label>
          <input type="text" id="admin_id" name="admin_id" placeholder="Contoh: 567858628 atau 567858628, -100987654321">
          <div class="hint">Dapatkan ID Anda dari @userinfobot. Bisa isi beberapa ID dipisah koma.</div>
        </div>

        <div style="margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap;">
          <button type="button" id="btnTest" class="btn-test">🧪 Tes Kirim Pesan Telegram</button>
          <button type="submit" class="btn-save" style="flex: 1; padding: 11px 16px;">💾 Simpan Pengaturan Telegram</button>
        </div>
      </div>

      <!-- TAB 3: BRANDING & AI -->
      <div id="tab-brand" class="tab-pane">
        <div class="form-group">
          <label>Nama Brand / ISP / RT-RW Net:</label>
          <input type="text" id="brand_name" name="brand_name" placeholder="ALIJAYA NET">
          <div class="hint">Nama usaha yang akan tampil pada header pesan Telegram & WhatsApp.</div>
        </div>

        <div class="form-group">
          <label>Nomor Telepon / WhatsApp Customer Service:</label>
          <input type="text" id="brand_phone" name="brand_phone" placeholder="081947215703">
          <div class="hint">Nomor kontak layanan bantuan pada footer pesan.</div>
        </div>

        <div class="form-group">
          <label>Google Gemini API Key (Opsional):</label>
          <input type="password" id="gemini_key" name="gemini_key" placeholder="AIzaSyDxxxxxxxxxxxxxxxxxxxx">
          <div class="hint">Untuk asisten AI percakapan cerdas. Kosongkan jika tidak memakai.</div>
        </div>
      </div>

      <!-- TAB 4: SISTEM & UPDATE -->
      <div id="tab-update" class="tab-pane">
        <div class="status-card" style="text-align: left; padding: 20px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
            <div>
              <span id="updateBadge" class="badge badge-open">MEMERIKSA VERSI...</span>
              <p style="color: var(--text-muted); font-size: 0.84rem; margin-top: 4px;">Repositori: <b style="color: #00e5ff;">github.com/alijayanet/genieacs-multitab-mod</b></p>
            </div>
            <button type="button" id="btnCheckUpdate" class="btn-test" style="flex: 0 0 auto; padding: 8px 16px; border-radius: 6px;" onclick="checkSystemUpdate()">🔍 Cek Pembaruan</button>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 18px;" class="version-grid">
            <div style="background: var(--card-inner); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
              <span style="font-size: 0.78rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Versi Server Ini (Lokal)</span>
              <div style="font-size: 1.15rem; font-weight: 700; color: #fff; margin-top: 4px; font-family: monospace;" id="localCommit">-</div>
              <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 6px;" id="localDate">-</div>
            </div>
            <div style="background: var(--card-inner); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
              <span style="font-size: 0.78rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Versi Terbaru (GitHub)</span>
              <div style="font-size: 1.15rem; font-weight: 700; color: #00e5ff; margin-top: 4px; font-family: monospace;" id="remoteCommit">-</div>
              <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 6px;" id="remoteDate">-</div>
            </div>
          </div>

          <div id="updateNoticeBox" style="background: rgba(4, 99, 128, 0.2); border: 1px solid #00e5ff; border-radius: 8px; padding: 14px; margin-bottom: 18px; display: none;">
            <div style="display: flex; align-items: center; gap: 8px; font-weight: 700; color: #00e5ff; font-size: 0.95rem;">
              ⚡ Pembaruan Baru Tersedia!
            </div>
            <p style="font-size: 0.85rem; color: #e2e8f0; margin-top: 6px;" id="updateNoticeMsg">-</p>
            <p style="font-size: 0.78rem; color: var(--text-muted); margin-top: 4px;" id="updateNoticeBehind"></p>
          </div>

          <div style="margin-top: 10px;">
            <button type="button" id="btnApplyUpdate" class="btn-save" style="display: none; width: 100%; border-radius: 6px;" onclick="applySystemUpdate()">
              🚀 Perbarui Sistem Sekarang (1-Click Update)
            </button>
          </div>

          <!-- Terminal Log Box -->
          <div id="updateLogWrapper" style="display: none; margin-top: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">📋 Log Proses Update:</span>
              <span id="updateProgressText" style="font-size: 0.78rem; color: var(--primary);">Menjalankan proses...</span>
            </div>
            <div id="updateLogBox" style="background: #02040a; border: 1px solid var(--border); border-radius: 6px; padding: 12px; font-family: Consolas, 'Courier New', monospace; font-size: 0.8rem; color: #38bdf8; max-height: 200px; overflow-y: auto; white-space: pre-wrap; line-height: 1.5;"></div>
          </div>
        </div>

        <div style="background: var(--card-inner); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 14px;">
          <h4 style="font-size: 0.88rem; color: #f8fafc; margin-bottom: 6px;">ℹ️ Informasi Pembaruan</h4>
          <p style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.5;">
            Fitur pembaruan ini akan secara otomatis menarik commit kode terbaru dari repositori GitHub, memperbarui modul backend & frontend GenieACS, dan me-restart service tanpa mengubah konfigurasi database MongoDB, token bot Telegram, maupun sesi WhatsApp yang sedang terhubung.
          </p>
        </div>
      </div>

      <div class="btn-row" id="saveBtnRow">
        <button type="submit" class="btn-save">💾 Simpan Semua Pengaturan</button>
      </div>
    </form>

    <div style="text-align: center;">
      <a href="/" class="back-link" id="backToAcs">⬅️ Kembali ke Dashboard GenieACS</a>
    </div>
  </div>

  <script>
    if (window.self !== window.top) {
      document.body.classList.add('in-iframe');
    }
    function botFetch(url, options) {
      const prefix = window.location.pathname.startsWith('/bot-proxy') ? '/bot-proxy' : '';
      const fullUrl = url.startsWith('/') ? prefix + url : prefix + '/' + url;
      return fetch(fullUrl, options);
    }
    window.botFetch = botFetch;
    document.getElementById('backToAcs').href = window.location.protocol + '//' + window.location.hostname + ':3000';

    function switchTab(tabId) {
      document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      
      const targetPane = document.getElementById(tabId);
      if (targetPane) targetPane.classList.add('active');

      if (typeof event !== 'undefined' && event && event.currentTarget && event.currentTarget.classList) {
        event.currentTarget.classList.add('active');
      } else {
        const clickedBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick') && b.getAttribute('onclick').indexOf(tabId) !== -1);
        if (clickedBtn) clickedBtn.classList.add('active');
      }

      const saveRow = document.getElementById('saveBtnRow');
      if (saveRow) {
        saveRow.style.display = (tabId === 'tab-update') ? 'none' : 'flex';
      }

      if (tabId === 'tab-update') {
        checkSystemUpdate(true);
      }
    }
    window.switchTab = switchTab;

    async function checkSystemUpdate(silenceSuccess) {
      const btn = document.getElementById('btnCheckUpdate');
      const badge = document.getElementById('updateBadge');
      if (btn) {
        btn.textContent = '⏳ Memeriksa...';
        btn.disabled = true;
      }
      try {
        const res = await botFetch('/api/system/update_status');
        const data = await res.json();
        if (!data.success) {
          showAlert('❌ ' + (data.error || 'Gagal memeriksa update'), false);
          return;
        }

        document.getElementById('localCommit').textContent = data.local_commit || '-';
        document.getElementById('localDate').textContent = 'Pembaruan: ' + (data.local_date || '-');
        document.getElementById('remoteCommit').textContent = data.remote_commit || '-';
        document.getElementById('remoteDate').textContent = 'Rilis: ' + (data.remote_date || '-');

        const btnApply = document.getElementById('btnApplyUpdate');
        const noticeBox = document.getElementById('updateNoticeBox');

        if (data.has_update) {
          badge.className = 'badge badge-qr';
          badge.textContent = '⚡ UPDATE TERSEDIA (' + (data.commits_behind || 1) + ' COMMIT)';
          noticeBox.style.display = 'block';
          document.getElementById('updateNoticeMsg').textContent = 'Pesan Rilis: ' + (data.remote_msg || '-');
          document.getElementById('updateNoticeBehind').textContent = 'Server ini tertinggal ' + (data.commits_behind || 1) + ' pembaruan dari GitHub.';
          btnApply.style.display = 'flex';
        } else {
          badge.className = 'badge badge-open';
          badge.textContent = '✅ SUDAH VERSI TERBARU';
          noticeBox.style.display = 'none';
          btnApply.style.display = 'none';
          if (!silenceSuccess) {
            showAlert('✅ Sistem Anda sudah menggunakan versi terbaru (' + data.local_commit + ').', true);
          }
        }
      } catch (err) {
        showAlert('❌ Gagal menghubungi server: ' + err.message, false);
      } finally {
        if (btn) {
          btn.textContent = '🔍 Cek Pembaruan';
          btn.disabled = false;
        }
      }
    }
    window.checkSystemUpdate = checkSystemUpdate;

    async function applySystemUpdate() {
      const confirmText = 'Apakah Anda yakin ingin memperbarui sistem ke versi terbaru dari GitHub?' + String.fromCharCode(10) + String.fromCharCode(10) + 'Service GenieACS akan direstart secara otomatis.';
      if (!confirm(confirmText)) {
        return;
      }

      const btnApply = document.getElementById('btnApplyUpdate');
      const logWrapper = document.getElementById('updateLogWrapper');
      const logBox = document.getElementById('updateLogBox');
      const progressText = document.getElementById('updateProgressText');

      btnApply.disabled = true;
      btnApply.textContent = '🚀 Sedang Memperbarui...';
      logWrapper.style.display = 'block';
      logBox.textContent = 'Memulai proses update...' + String.fromCharCode(10);
      progressText.textContent = 'Mengunduh dari GitHub...';

      try {
        const res = await botFetch('/api/system/update_apply', { method: 'POST' });
        const data = await res.json();
        if (data.logs) {
          logBox.textContent = data.logs;
        }
        if (data.success) {
          progressText.textContent = '✅ Berhasil!';
          progressText.style.color = '#34d399';
          showAlert('🎉 ' + data.message, true);
          
          let countdown = 6;
          const interval = setInterval(() => {
            countdown--;
            progressText.textContent = 'Memuat ulang halaman dalam ' + countdown + ' detik...';
            if (countdown <= 0) {
              clearInterval(interval);
              window.location.reload();
            }
          }, 1000);
        } else {
          progressText.textContent = '❌ Gagal';
          progressText.style.color = '#f87171';
          showAlert('❌ Gagal update: ' + (data.error || 'Terjadi kesalahan'), false);
          btnApply.disabled = false;
          btnApply.textContent = '🚀 Coba Perbarui Lagi';
        }
      } catch (err) {
        logBox.textContent += String.fromCharCode(10) + 'Error: ' + err.message;
        progressText.textContent = '⚠️ Service sedang restart...';
        let countdown = 6;
        const interval = setInterval(() => {
          countdown--;
          progressText.textContent = 'Service sedang restart. Memuat ulang dalam ' + countdown + ' detik...';
          if (countdown <= 0) {
            clearInterval(interval);
            window.location.reload();
          }
        }, 1000);
      }
    }
    window.applySystemUpdate = applySystemUpdate;

    function showAlert(msg, isSuccess) {
      const box = document.getElementById('alertBox');
      box.textContent = msg;
      box.className = 'alert ' + (isSuccess ? 'alert-success' : 'alert-error');
      box.style.display = 'block';
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setTimeout(() => { box.style.display = 'none'; }, 6000);
    }

    // Load initial config
    botFetch('/api/config')
      .then(res => {
        if (!res.ok) throw new Error('Status: ' + res.status);
        return res.json();
      })
      .then(data => {
        document.getElementById('bot_enabled').value = data.enabled || 'true';
        document.getElementById('bot_token').value = data.token || '';
        document.getElementById('admin_id').value = data.admin_id || '';
        document.getElementById('brand_name').value = data.brand_name || '';
        document.getElementById('brand_phone').value = data.brand_phone || '';
        document.getElementById('gemini_key').value = data.gemini_key || '';
        document.getElementById('wa_enabled').value = data.wa_enabled !== undefined ? String(data.wa_enabled) : 'true';
        document.getElementById('wa_admin_numbers').value = data.wa_admin_numbers || '';
        document.getElementById('otp_enabled').value = data.otp_enabled !== undefined ? String(data.otp_enabled) : 'true';
        document.getElementById('otp_expiry_minutes').value = data.otp_expiry_minutes || '5';
        toggleOtpExpiryVisibility();
      })
      .catch(err => showAlert('❌ Gagal memuat konfigurasi: ' + err.message, false));

    function toggleOtpExpiryVisibility() {
      const sel = document.getElementById('otp_enabled');
      const grp = document.getElementById('otpExpiryGroup');
      if (sel && grp) {
        grp.style.display = (sel.value === 'false') ? 'none' : 'block';
      }
    }
    window.toggleOtpExpiryVisibility = toggleOtpExpiryVisibility;

    // WhatsApp Live Status Polling
    let pollInterval = null;
    function updateWaStatus() {
      botFetch('/api/whatsapp/status')
        .then(res => res.json())
        .then(data => {
          const badge = document.getElementById('waBadge');
          const connBox = document.getElementById('waConnectedBox');
          const qrBox = document.getElementById('waQrBox');
          const offBox = document.getElementById('waOfflineBox');

          connBox.style.display = 'none';
          qrBox.style.display = 'none';
          offBox.style.display = 'none';

          if (data.connection === 'open') {
            badge.className = 'badge badge-open';
            badge.textContent = '🟢 TERHUBUNG (ONLINE)';
            connBox.style.display = 'block';
            document.getElementById('waUser').textContent = data.user ? (data.user.name || data.user.id) : '-';
          } else if (data.connection === 'qr') {
            badge.className = 'badge badge-qr';
            badge.textContent = '📷 MENUNGGU SCAN QR CODE';
            qrBox.style.display = 'block';
            if (data.qr) {
              document.getElementById('waQrImg').src = 'https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=' + encodeURIComponent(data.qr);
            }
          } else if (data.connection === 'connecting') {
            badge.className = 'badge badge-connecting';
            badge.textContent = '🔄 MENGHUBUNGKAN...';
          } else {
            badge.className = 'badge badge-disconnected';
            badge.textContent = '🔴 TERPUTUS (OFFLINE)';
            offBox.style.display = 'block';
          }
        })
        .catch(() => {
          const badge = document.getElementById('waBadge');
          badge.className = 'badge badge-disconnected';
          badge.textContent = '🔴 SERVICE OFFLINE';
          document.getElementById('waConnectedBox').style.display = 'none';
          document.getElementById('waQrBox').style.display = 'none';
          document.getElementById('waOfflineBox').style.display = 'block';
        });
    }

    updateWaStatus();
    pollInterval = setInterval(updateWaStatus, 3000);

    function logoutWA() {
      if (confirm('Yakin ingin memutuskan koneksi WhatsApp bot?')) {
        botFetch('/api/whatsapp/logout', { method: 'POST' })
          .then(res => res.json())
          .then(d => {
            showAlert('Sesi WhatsApp berhasil diputus', true);
            updateWaStatus();
          })
          .catch(err => showAlert('❌ Gagal logout WhatsApp: ' + err.message, false));
      }
    }
    window.logoutWA = logoutWA;

    function resetWA() {
      const confirmReset = '⚠️ PERHATIAN:' + String.fromCharCode(10) + String.fromCharCode(10) + 'Tindakan ini akan menghapus sesi WhatsApp bot di server dan membuat ulang QR Code.' + String.fromCharCode(10) + String.fromCharCode(10) + 'Apakah Anda yakin ingin melanjutkan?';
      if (confirm(confirmReset)) {
        const btn = document.querySelector('.btn-reset-wa');
        if (btn) {
          btn.disabled = true;
          btn.textContent = '⏳ Menghapus sesi WhatsApp...';
        }
        botFetch('/api/whatsapp/reset', { method: 'POST' })
          .then(res => res.json())
          .then(d => {
            showAlert('✅ ' + (d.message || 'Sesi WhatsApp berhasil dihapus. Silakan tunggu QR Code baru.'), true);
            setTimeout(updateWaStatus, 2000);
          })
          .catch(err => showAlert('❌ Gagal reset WhatsApp: ' + err.message, false))
          .finally(() => {
            if (btn) {
              btn.disabled = false;
              btn.textContent = '🗑️ Hapus Sesi WhatsApp (Ganti Nomor Bot / Buat QR Baru)';
            }
          });
      }
    }
    window.resetWA = resetWA;

    // Handle Form Submit
    document.getElementById('botForm').addEventListener('submit', function(e) {
      e.preventDefault();
      const payload = {
        enabled: document.getElementById('bot_enabled').value,
        token: document.getElementById('bot_token').value,
        admin_id: document.getElementById('admin_id').value,
        brand_name: document.getElementById('brand_name').value,
        brand_phone: document.getElementById('brand_phone').value,
        gemini_key: document.getElementById('gemini_key').value,
        wa_enabled: document.getElementById('wa_enabled').value,
        wa_admin_numbers: document.getElementById('wa_admin_numbers').value,
        otp_enabled: document.getElementById('otp_enabled').value,
        otp_expiry_minutes: document.getElementById('otp_expiry_minutes').value
      };

      botFetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          showAlert('✅ Konfigurasi Bot berhasil disimpan!', true);
        } else {
          showAlert('❌ ' + (data.message || 'Gagal menyimpan konfigurasi'), false);
        }
      })
      .catch(err => showAlert('❌ Error: ' + err.message, false));
    });

    // Test Telegram message
    document.getElementById('btnTest').addEventListener('click', function() {
      const token = document.getElementById('bot_token').value.trim();
      const adminId = document.getElementById('admin_id').value.trim();

      if (!token || !adminId) {
        showAlert('⚠️ Harap isi Token Bot dan Admin Chat ID terlebih dahulu!', false);
        return;
      }

      this.textContent = '⏳ Mengirim pesan...';
      this.disabled = true;

      const targetId = adminId.split(',')[0].trim();
      const testMsg = '🔔 *TES NOTIFIKASI GENIEACS BOT*' + String.fromCharCode(10) + String.fromCharCode(10) + 'Koneksi bot Telegram ALIJAYA NET berhasil terhubung dengan server!';
      const tgUrl = 'https://api.telegram.org/bot' + token + '/sendMessage?chat_id=' + targetId + '&text=' + encodeURIComponent(testMsg) + '&parse_mode=Markdown';

      fetch(tgUrl)
      .then(res => res.json())
      .then(res => {
        if (res.ok) {
          showAlert('✅ Pesan tes Telegram berhasil terkirim ke ' + targetId + '! Menyimpan pengaturan ke server...', true);
          try {
            const submitEvent = new Event('submit', { cancelable: true });
            document.getElementById('botForm').dispatchEvent(submitEvent);
          } catch (_) {}
        } else {
          showAlert('❌ Gagal kirim Telegram: ' + (res.description || 'Unknown error'), false);
        }
      })
      .catch(err => showAlert('❌ Error: ' + err.message, false))
      .finally(() => {
        this.textContent = '🧪 Tes Kirim Pesan Telegram';
        this.disabled = false;
      });
    });

    async function handleAdminLogout() {
      if (confirm("Apakah Anda yakin ingin logout dari halaman pengaturan Bot?")) {
        try {
          await botFetch('/api/logout', { method: 'POST' });
        } catch (_) {}
        window.location.reload();
      }
    }
    window.handleAdminLogout = handleAdminLogout;
  </script>
</body>
</html>
"""


HTML_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login Administrator - Bot AI & WA GenieACS</title>
  <style>
    :root {
      --bg: #050833;
      --card: #080d22;
      --card-inner: #040714;
      --border: #1c274c;
      --primary: #00e5ff;
      --primary-btn: #046380;
      --primary-hover: #00b4d8;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body {
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 20px;
    }
    .login-box {
      width: 100%;
      max-width: 420px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 32px 28px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
      text-align: center;
    }
    .logo-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: rgba(6, 182, 212, 0.15);
      color: var(--primary);
      font-size: 30px;
      margin-bottom: 16px;
      border: 1px solid rgba(6, 182, 212, 0.3);
    }
    h2 { font-size: 1.4rem; margin-bottom: 6px; color: #fff; font-weight: 700; }
    p.desc { font-size: 0.84rem; color: var(--text-muted); margin-bottom: 24px; line-height: 1.45; }
    .form-group { text-align: left; margin-bottom: 18px; }
    label { display: block; font-size: 0.84rem; font-weight: 600; margin-bottom: 6px; color: var(--text); }
    input {
      width: 100%;
      padding: 11px 14px;
      background: #040714;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: #fff;
      font-size: 0.94rem;
      outline: none;
      transition: border 0.2s;
    }
    input:focus { border-color: var(--primary); }
    .btn-login {
      width: 100%;
      padding: 12px;
      margin-top: 8px;
      background: var(--primary);
      color: #0b1120;
      font-weight: 700;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.96rem;
      transition: background 0.2s;
    }
    .btn-login:hover { background: var(--primary-hover); }
    .btn-login:disabled { opacity: 0.6; cursor: not-allowed; }
    .alert-error {
      display: none;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--danger);
      color: #fca5a5;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.84rem;
      margin-bottom: 18px;
      text-align: left;
    }
    .footer { margin-top: 24px; font-size: 0.76rem; color: #64748b; }
  </style>
</head>
<body>
  <div class="login-box">
    <div class="logo-badge">🔐</div>
    <h2>Admin Login</h2>
    <p class="desc">Portal Pengaturan Bot AI & WhatsApp GenieACS.<br>Silakan masuk menggunakan akun Administrator GenieACS.</p>
    
    <div id="errMsg" class="alert-error"></div>
    
    <form id="loginForm" onsubmit="handleLogin(event)">
      <div class="form-group">
        <label for="username">Username Admin</label>
        <input type="text" id="username" autocomplete="username" placeholder="Masukkan username admin" required autofocus>
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" autocomplete="current-password" placeholder="Masukkan password" required>
      </div>
      <button type="submit" id="btnSubmit" class="btn-login">Masuk ke Pengaturan</button>
    </form>
    
        <div style="text-align: center; margin-top: 18px;">
      <a href="/mywifi" style="color: #38bdf8; text-decoration: none; font-size: 0.85rem; font-weight: 500;">
        📶 Masuk ke Portal Mandiri WiFi Pelanggan &rarr;
      </a>
    </div>
    <div class="footer">ALIJAYA NET TR-069 Management</div>
  </div>

  <script>
    function botFetch(url, options) {
      const prefix = window.location.pathname.startsWith('/bot-proxy') ? '/bot-proxy' : '';
      const fullUrl = url.startsWith('/') ? prefix + url : prefix + '/' + url;
      return fetch(fullUrl, options);
    }

    async function handleLogin(e) {
      e.preventDefault();
      const u = document.getElementById('username').value.trim();
      const p = document.getElementById('password').value;
      const btn = document.getElementById('btnSubmit');
      const err = document.getElementById('errMsg');
      
      err.style.display = 'none';
      btn.disabled = true;
      btn.textContent = 'Memverifikasi...';
      
      try {
        const res = await botFetch('/api/login', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({username: u, password: p})
        });
        const data = await res.json();
        if (data.success) {
          window.location.reload();
        } else {
          err.textContent = data.message || 'Username atau password salah / bukan akun admin.';
          err.style.display = 'block';
        }
      } catch (errEx) {
        err.textContent = 'Gagal terhubung ke server autentikasi: ' + errEx.message;
        err.style.display = 'block';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Masuk ke Pengaturan';
      }
    }
  </script>
</body>
</html>
"""


ACTIVE_ADMIN_SESSIONS = {}
CUSTOMER_OTP_STORE = {}    # clean_phone -> {"otp": "1234", "expires": ts, "attempts": 0, "resend_after": ts, "device_id": dev_id}
CUSTOMER_SESSIONS = {}     # token -> {"phone": clean_phone, "device_id": dev_id, "expires": ts, "created_at": ts}

def send_whatsapp_message_local(to_phone, text):
    try:
        clean_target = normalize_phone(to_phone)
        r = requests.post("http://127.0.0.1:7559/send", json={"to": clean_target or str(to_phone), "text": str(text)}, timeout=6.0)
        if r.status_code == 200:
            return r.json().get("success", False)
        return False
    except Exception as e:
        logger.warning(f"Failed to send local WA message to {to_phone}: {e}")
        return False

def get_authenticated_customer_session(handler):
    token = handler.headers.get("X-Customer-Token")
    if not token:
        cookies = handler.parse_cookies()
        token = cookies.get("customer_token")
    if not token:
        parsed = urlparse(handler.path)
        qs = parse_qs(parsed.query)
        tok_list = qs.get("token", [])
        if tok_list:
            token = tok_list[0]

    if not token or token not in CUSTOMER_SESSIONS:
        return None

    sess = CUSTOMER_SESSIONS[token]
    if sess.get("expires", 0) < time.time():
        CUSTOMER_SESSIONS.pop(token, None)
        return None
    return sess

def get_customer_portal_html():
    cand_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "mywifi.html"),
        "/opt/genieacs-agent/public/mywifi.html",
        "/usr/lib/node_modules/genieacs/public/mywifi.html",
        "/usr/local/lib/node_modules/genieacs/public/mywifi.html",
        "/opt/genieacs/public/mywifi.html"
    ]
    for cp in cand_paths:
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return "<h3>Portal Mandiri WiFi belum terpasang (mywifi.html tidak ditemukan).</h3>"


def get_jwt_secret():
    secret = os.environ.get("GENIEACS_UI_JWT_SECRET") or os.environ.get("UI_JWT_SECRET")
    if not secret and os.path.exists("/opt/genieacs/genieacs.env"):
        try:
            with open("/opt/genieacs/genieacs.env", "r", encoding="utf-8") as f:
                for line in f:
                    if "GENIEACS_UI_JWT_SECRET=" in line:
                        secret = line.split("GENIEACS_UI_JWT_SECRET=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    return secret or ""

def verify_genieacs_jwt(token):
    secret = get_jwt_secret()
    if not secret:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h, p, s = parts
        msg = f"{h}.{p}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
        pad = "=" * ((4 - len(s) % 4) % 4)
        actual = base64.urlsafe_b64decode((s + pad).encode("ascii"))
        if not hmac.compare_digest(expected, actual):
            return None
        pad_p = "=" * ((4 - len(p) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode((p + pad_p).encode("ascii")).decode("utf-8"))
        return payload
    except Exception:
        return None

def verify_admin_login(username, password):
    db = get_db()
    if db is None:
        return False, "Database MongoDB tidak terhubung."
    user = db.users.find_one({"_id": username})
    if not user:
        return False, "Username atau password salah."
    roles = [r.strip() for r in user.get("roles", "").split(",") if r.strip()]
    if "admin" not in roles:
        return False, "Akun ini tidak memiliki hak akses Administrator GenieACS."
    salt = user.get("salt", "")
    expected_hash = user.get("password", "")
    computed_hash = hashlib.pbkdf2_hmac(
        "sha512",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        10000,
        dklen=128
    ).hex()
    if hmac.compare_digest(computed_hash, expected_hash):
        return True, "Login berhasil."
    return False, "Username atau password salah."



def get_system_update_status():
    repo_dirs = [
        "/root/genieacs-multitab-mod",
        "/opt/genieacs-multitab-mod",
        os.path.dirname(os.path.abspath(__file__))
    ]
    repo_dir = None
    for d in repo_dirs:
        if os.path.exists(os.path.join(d, ".git")):
            repo_dir = d
            break

    if not repo_dir:
        target_dir = "/root/genieacs-multitab-mod"
        try:
            subprocess.run(["git", "clone", "https://github.com/alijayanet/genieacs-multitab-mod.git", target_dir], timeout=35, check=True)
            repo_dir = target_dir
        except Exception as e:
            return {"success": False, "error": f"Gagal inisialisasi repositori Git: {e}"}

    try:
        local_hash = subprocess.check_output(["git", "-C", repo_dir, "rev-parse", "HEAD"], timeout=5).decode().strip()
        local_short = local_hash[:7]
        local_msg = subprocess.check_output(["git", "-C", repo_dir, "log", "-1", "--pretty=%s"], timeout=5).decode().strip()
        local_date = subprocess.check_output(["git", "-C", repo_dir, "log", "-1", "--pretty=%cd", "--date=format:%Y-%m-%d %H:%M"], timeout=5).decode().strip()
    except Exception as e:
        return {"success": False, "error": f"Gagal membaca info commit lokal: {e}"}

    remote_msg = ""
    remote_date = ""
    commits_behind = 0
    try:
        subprocess.run(["git", "-C", repo_dir, "fetch", "origin", "main"], timeout=20, check=True)
        remote_hash = subprocess.check_output(["git", "-C", repo_dir, "rev-parse", "origin/main"], timeout=5).decode().strip()
        remote_short = remote_hash[:7]
        remote_msg = subprocess.check_output(["git", "-C", repo_dir, "log", "-1", "--pretty=%s", "origin/main"], timeout=5).decode().strip()
        remote_date = subprocess.check_output(["git", "-C", repo_dir, "log", "-1", "--pretty=%cd", "--date=format:%Y-%m-%d %H:%M", "origin/main"], timeout=5).decode().strip()
        behind_str = subprocess.check_output(["git", "-C", repo_dir, "rev-list", "--count", "HEAD..origin/main"], timeout=5).decode().strip()
        commits_behind = int(behind_str) if behind_str.isdigit() else 0
    except Exception:
        try:
            ls_out = subprocess.check_output(["git", "ls-remote", "https://github.com/alijayanet/genieacs-multitab-mod.git", "refs/heads/main"], timeout=10).decode().strip()
            remote_hash = ls_out.split()[0] if ls_out else ""
            remote_short = remote_hash[:7]
        except Exception as e2:
            return {"success": False, "error": f"Gagal memeriksa GitHub: {e2}", "local_commit": local_short, "local_msg": local_msg, "local_date": local_date}

    has_update = bool(local_hash and remote_hash and local_hash != remote_hash)

    return {
        "success": True,
        "local_commit": local_short,
        "local_hash": local_hash,
        "local_msg": local_msg,
        "local_date": local_date,
        "remote_commit": remote_short,
        "remote_hash": remote_hash,
        "remote_msg": remote_msg or local_msg,
        "remote_date": remote_date or local_date,
        "commits_behind": commits_behind,
        "has_update": has_update
    }


def apply_system_update():
    repo_dirs = [
        "/root/genieacs-multitab-mod",
        "/opt/genieacs-multitab-mod",
        os.path.dirname(os.path.abspath(__file__))
    ]
    repo_dir = None
    for d in repo_dirs:
        if os.path.exists(os.path.join(d, ".git")):
            repo_dir = d
            break

    if not repo_dir:
        repo_dir = "/root/genieacs-multitab-mod"

    logs = []
    def log(msg):
        logs.append(msg)
        logger.info(f"[UPDATER] {msg}")

    try:
        log("🔄 [1/5] Mengambil pembaruan terbaru dari GitHub...")
        if not os.path.exists(os.path.join(repo_dir, ".git")):
            cmd = subprocess.run(["git", "clone", "https://github.com/alijayanet/genieacs-multitab-mod.git", repo_dir], capture_output=True, text=True, timeout=40)
            if cmd.stdout.strip(): log(cmd.stdout.strip())
            if cmd.stderr.strip(): log(cmd.stderr.strip())
        else:
            cmd = subprocess.run(["git", "-C", repo_dir, "fetch", "origin", "main"], capture_output=True, text=True, timeout=25)
            if cmd.stdout.strip(): log(cmd.stdout.strip())
            if cmd.stderr.strip(): log(cmd.stderr.strip())
            cmd = subprocess.run(["git", "-C", repo_dir, "reset", "--hard", "origin/main"], capture_output=True, text=True, timeout=10)
            if cmd.stdout.strip(): log(cmd.stdout.strip())
            if cmd.stderr.strip(): log(cmd.stderr.strip())

        log("📦 [2/5] Memperbarui script Agent (/opt/genieacs-agent/agent.py)...")
        src_agent = os.path.join(repo_dir, "agent.py")
        if os.path.exists(src_agent):
            import shutil
            shutil.copy2(src_agent, "/opt/genieacs-agent/agent.py")
            os.chmod("/opt/genieacs-agent/agent.py", 0o755)
            log("  ✓ agent.py berhasil diperbarui.")

        src_cli = os.path.join(repo_dir, "set-bot.py")
        if os.path.exists(src_cli):
            import shutil
            shutil.copy2(src_cli, "/usr/local/bin/set-bot")
            os.chmod("/usr/local/bin/set-bot", 0o755)
            log("  ✓ set-bot CLI berhasil diperbarui.")

        src_wa = os.path.join(repo_dir, "whatsapp", "whatsapp-bot.mjs")
        if not os.path.exists(src_wa):
            src_wa = os.path.join(repo_dir, "whatsapp-bot.mjs")
        if os.path.exists(src_wa):
            import shutil
            shutil.copy2(src_wa, "/opt/genieacs-agent/whatsapp-bot.mjs")
            os.chmod("/opt/genieacs-agent/whatsapp-bot.mjs", 0o755)
            log("  ✓ whatsapp-bot.mjs berhasil diperbarui.")

        log("🎨 [3/5] Memeriksa & memperbarui antarmuka GenieACS & Peta ODP...")
        tar_file = os.path.join(repo_dir, "genieacs_ui_mod.tar.gz")
        for node_dir in ["/usr/lib/node_modules", "/usr/local/lib/node_modules"]:
            genie_target = os.path.join(node_dir, "genieacs")
            if os.path.exists(genie_target):
                if os.path.exists(tar_file):
                    tar_cmd = subprocess.run(["tar", "-zxf", tar_file, "-C", node_dir + "/"], capture_output=True, text=True, timeout=30)
                    if tar_cmd.returncode == 0:
                        log(f"  ✓ genieacs_ui_mod.tar.gz diekstrak ke {node_dir}/.")
                    bin_dir = os.path.join(genie_target, "bin")
                    if os.path.exists(bin_dir):
                        subprocess.run(["chmod", "+x"] + [os.path.join(bin_dir, f) for f in os.listdir(bin_dir)], check=False)
                    subprocess.run(["chmod", "+x", "/usr/bin/genieacs-ui", "/usr/bin/genieacs-cwmp", "/usr/bin/genieacs-nbi", "/usr/bin/genieacs-fs"], check=False)
                    subprocess.run(["chmod", "+x", "/usr/local/bin/genieacs-ui", "/usr/local/bin/genieacs-cwmp", "/usr/local/bin/genieacs-nbi", "/usr/local/bin/genieacs-fs"], check=False)
                pub = os.path.join(genie_target, "public")
                if os.path.exists(pub):
                    peta_src = os.path.join(repo_dir, "public", "peta.html")
                    app_src = os.path.join(repo_dir, "public", "app.js")
                    if os.path.exists(peta_src):
                        shutil.copy2(peta_src, os.path.join(pub, "peta.html"))
                        log("  ✓ peta.html berhasil diperbarui.")
                    if os.path.exists(app_src):
                        shutil.copy2(app_src, os.path.join(pub, "app.js"))
                        log("  ✓ app.js berhasil diperbarui.")

        # Update VirtualParameters (VlanID, pppoeUsername) & cache di MongoDB
        try:
            db = get_db()
            if db is not None:
                vp_vlan = db.virtualParameters.find_one({"_id": "VlanID"})
                if not vp_vlan:
                    vlan_script = 'let vlan = "-";\nlet p = declare("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.*.WANPPPConnection.*.X_CT-COM_VlanID", {value: 1});\nif (p.value && p.value[0]) vlan = p.value[0];\nelse {\n  p = declare("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.*.WANPPPConnection.*.X_CMCC_VLANIDMark", {value: 1});\n  if (p.value && p.value[0]) vlan = p.value[0];\n  else {\n    p = declare("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.*.WANPPPConnection.*.X_HW_VLAN", {value: 1});\n    if (p.value && p.value[0]) vlan = p.value[0];\n    else {\n      p = declare("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.*.WANPPPConnection.*.VLANID", {value: 1});\n      if (p.value && p.value[0]) vlan = p.value[0];\n    }\n  }\n}\nreturn {writable: true, value: [vlan, "xsd:string"]};'
                    db.virtualParameters.insert_one({"_id": "VlanID", "script": vlan_script})
                    log("  ✓ VirtualParameters.VlanID berhasil dibuat di MongoDB.")
                vp_user = db.virtualParameters.find_one({"_id": "pppoeUsername"})
                if vp_user and "writable: true" not in vp_user.get("script", ""):
                    new_script = vp_user.get("script", "").replace("return {writable: false", "return {writable: true")
                    db.virtualParameters.update_one({"_id": "pppoeUsername"}, {"$set": {"script": new_script}})
                    log("  ✓ VirtualParameters.pppoeUsername disetel writable di MongoDB.")
                db.config.delete_one({"_id": "ui-local-cache-hash"})
        except Exception as e_db:
            log(f"  ⚠️ MongoDB config update: {e_db}")

        log("🔄 [4/5] Me-restart service genieacs-ui...")
        subprocess.run(["systemctl", "restart", "genieacs-ui"], check=True, timeout=15)
        log("  ✓ genieacs-ui aktif.")

        try:
            subprocess.run(["systemctl", "try-restart", "genieacs-whatsapp"], timeout=10)
        except Exception:
            pass

        log("🚀 [5/5] Menjadwalkan restart service genieacs-agent dalam 2 detik...")
        subprocess.Popen(["bash", "-c", "sleep 2 && systemctl restart genieacs-agent"])
        log("  ✓ Selesai! Sistem akan memuat ulang halaman secara otomatis.")

        return {
            "success": True,
            "message": "Pembaruan berhasil diterapkan! Service sedang dimulai ulang.",
            "logs": "\n".join(logs)
        }
    except Exception as e:
        log(f"❌ Error saat update: {e}")
        return {
            "success": False,
            "error": str(e),
            "logs": "\n".join(logs)
        }



# ==============================================================================
# FITUR GEOLOCATION / MAPPING ODP & KLIEN (ALIJAYA NET)
# ==============================================================================

def get_geo_devices_data():
    db = get_db()
    if db is None:
        return {"success": False, "error": "Database tidak terhubung", "mapped": [], "unmapped": []}
    
    try:
        now_ts = time.time()
        loc_cursor = db.device_locations.find({})
        mapped_map = {}
        for doc in loc_cursor:
            dev_id = doc.get("_id")
            if dev_id:
                mapped_map[dev_id] = doc

        dev_cursor = db.devices.find({}, {
            "_id": 1,
            "_deviceId": 1,
            "_lastInform": 1,
            "_ip": 1,
            "VirtualParameters": 1,
            "InternetGatewayDevice.WANDevice": 1
        })

        mapped_list = []
        unmapped_list = []
        all_devices_dict = {}

        for dev in dev_cursor:
            dev_id = dev.get("_id")
            if not dev_id:
                continue
            all_devices_dict[dev_id] = dev

            pppoe = get_device_pppoe_username(dev)
            serial = dev.get("_deviceId", {}).get("_SerialNumber", "-")
            product_class = dev.get("_deviceId", {}).get("_ProductClass", "-")
            vp = dev.get("VirtualParameters", {})
            ip = (
                vp.get("pppoeIP", {}).get("_value") or
                vp.get("pppIP", {}).get("_value") or
                vp.get("IPTR069", {}).get("_value") or
                dev.get("_ip") or
                "-"
            )
            
            vp = dev.get("VirtualParameters", {})
            rx_raw = vp.get("RXPower", {}).get("_value")
            rx_val = None
            rx_str = "-"
            rx_status = "unknown"
            
            if rx_raw is not None and str(rx_raw).strip() not in ("", "-", "undefined", "null"):
                try:
                    cleaned_rx = str(rx_raw).replace("dBm", "").strip()
                    rx_val = round(float(cleaned_rx), 2)
                    rx_str = f"{rx_val} dBm"
                    if rx_val >= -24.0:
                        rx_status = "normal"
                    elif rx_val >= -27.0:
                        rx_status = "warning"
                    else:
                        rx_status = "critical"
                except Exception:
                    rx_str = str(rx_raw)

            last_inform = dev.get("_lastInform")
            is_online = False
            last_inform_str = "-"
            if last_inform:
                try:
                    diff_sec = get_datetime_diff_seconds(last_inform)
                    is_online = (diff_sec < 600)
                    if diff_sec < 60:
                        last_inform_str = "Baru saja"
                    elif diff_sec < 3600:
                        last_inform_str = f"{int(diff_sec // 60)} mnt lalu"
                    elif diff_sec < 86400:
                        last_inform_str = f"{int(diff_sec // 3600)} jam lalu"
                    else:
                        last_inform_str = f"{int(diff_sec // 86400)} hari lalu"
                except Exception:
                    pass

            if not is_online:
                rx_status = "offline"

            vlan_raw = vp.get("VlanID", {}).get("_value") or vp.get("vlan", {}).get("_value") or "-"
            dev_info = {
                "vlan": str(vlan_raw),
                "_id": dev_id,
                "pppoe": pppoe,
                "serial": serial,
                "product_class": product_class,
                "ip": ip,
                "rx": rx_str,
                "rx_val": rx_val,
                "rx_status": rx_status,
                "online": is_online,
                "last_inform": last_inform_str
            }

            if dev_id in mapped_map:
                loc_doc = mapped_map[dev_id]
                item = {
                    **dev_info,
                    "name": loc_doc.get("name") or pppoe,
                    "lat": float(loc_doc.get("lat", 0.0)),
                    "lng": float(loc_doc.get("lng", 0.0)),
                    "odp": loc_doc.get("odp", ""),
                    "phone": loc_doc.get("phone", ""),
                    "address": loc_doc.get("address", ""),
                    "notes": loc_doc.get("notes", ""),
                    "updated_at": loc_doc.get("updated_at", "")
                }
                mapped_list.append(item)
            else:
                unmapped_list.append(dev_info)

        for dev_id, loc_doc in mapped_map.items():
            if dev_id not in all_devices_dict:
                mapped_list.append({
                    "_id": dev_id,
                    "name": loc_doc.get("name", dev_id),
                    "pppoe": loc_doc.get("name", dev_id),
                    "serial": "-",
                    "product_class": "-",
                    "ip": "-",
                    "rx": "-",
                    "rx_val": None,
                    "rx_status": "offline",
                    "online": False,
                    "last_inform": "-",
                    "lat": float(loc_doc.get("lat", 0.0)),
                    "lng": float(loc_doc.get("lng", 0.0)),
                    "odp": loc_doc.get("odp", ""),
                    "phone": loc_doc.get("phone", ""),
                    "address": loc_doc.get("address", ""),
                    "notes": loc_doc.get("notes", ""),
                    "updated_at": loc_doc.get("updated_at", "")
                })

        return {
            "success": True,
            "mapped": mapped_list,
            "unmapped": unmapped_list,
            "total_mapped": len(mapped_list),
            "total_unmapped": len(unmapped_list)
        }
    except Exception as e:
        logger.error(f"Error getting geo devices data: {e}", exc_info=True)
        return {"success": False, "error": str(e), "mapped": [], "unmapped": []}


def save_geo_device_data(data):
    db = get_db()
    if db is None:
        return {"success": False, "message": "Database tidak terhubung"}
    
    dev_id = str(data.get("_id") or "").strip()
    if not dev_id:
        return {"success": False, "message": "ID Perangkat tidak boleh kosong"}
    
    existing = db.device_locations.find_one({"_id": dev_id})
    try:
        raw_lat = data.get("lat")
        raw_lng = data.get("lng")
        if (raw_lat is None or str(raw_lat).strip() in ("", "0", "0.0", "None")) and existing:
            lat = float(existing.get("lat", 0.0))
        else:
            lat = float(raw_lat or 0.0)

        if (raw_lng is None or str(raw_lng).strip() in ("", "0", "0.0", "None")) and existing:
            lng = float(existing.get("lng", 0.0))
        else:
            lng = float(raw_lng or 0.0)
    except (ValueError, TypeError):
        lat = float(existing.get("lat", 0.0)) if existing else 0.0
        lng = float(existing.get("lng", 0.0)) if existing else 0.0

    doc = {
        "_id": dev_id,
        "name": str(data.get("name") or "").strip(),
        "lat": lat,
        "lng": lng,
        "odp": str(data.get("odp") or "").strip(),
        "phone": str(data.get("phone") or "").strip(),
        "address": str(data.get("address") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        db.device_locations.update_one({"_id": dev_id}, {"$set": doc}, upsert=True)
        # Jika ada nomor HP, tambahkan juga tag otomatis ke ONU di GenieACS
        if doc.get("phone"):
            raw_ph = doc.get("phone").strip()
            digits = re.sub(r"\D", "", raw_ph)
            if len(digits) >= 8:
                add_device_tag(dev_id, raw_ph)
                if digits.startswith("0"):
                    add_device_tag(dev_id, "62" + digits[1:])
                elif digits.startswith("62"):
                    add_device_tag(dev_id, "0" + digits[2:])
        return {"success": True, "message": "Titik lokasi pelanggan berhasil disimpan", "data": doc}
    except Exception as e:
        logger.error(f"Error saving geo device {dev_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Gagal menyimpan ke database: {e}"}


def delete_geo_device_data(dev_id):
    db = get_db()
    if db is None:
        return {"success": False, "message": "Database tidak terhubung"}
    
    if not dev_id:
        return {"success": False, "message": "ID Perangkat tidak boleh kosong"}
    
    try:
        res = db.device_locations.delete_one({"_id": dev_id})
        return {"success": True, "message": f"Lokasi pelanggan berhasil dihapus ({res.deleted_count})"}
    except Exception as e:
        return {"success": False, "message": f"Gagal menghapus: {e}"}


def get_geo_odps_data():
    db = get_db()
    if db is None:
        return {"success": False, "error": "Database tidak terhubung", "odps": []}
    
    try:
        odp_cursor = db.odp_locations.find({})
        odp_list = []
        for doc in odp_cursor:
            odp_id = doc.get("_id")
            if not odp_id:
                continue
            
            used = db.device_locations.count_documents({"odp": odp_id})
            cap = int(doc.get("capacity", 8))
            
            odp_list.append({
                "_id": odp_id,
                "name": doc.get("name") or odp_id,
                "lat": float(doc.get("lat", 0.0)),
                "lng": float(doc.get("lng", 0.0)),
                "capacity": cap,
                "color": doc.get("color", "#3b82f6"),
                "notes": doc.get("notes", ""),
                "used_ports": used,
                "available_ports": max(0, cap - used),
                "updated_at": doc.get("updated_at", "")
            })
            
        return {"success": True, "odps": odp_list}
    except Exception as e:
        logger.error(f"Error getting geo ODPs: {e}", exc_info=True)
        return {"success": False, "error": str(e), "odps": []}


def save_geo_odp_data(data):
    db = get_db()
    if db is None:
        return {"success": False, "message": "Database tidak terhubung"}
    
    odp_id = str(data.get("_id") or "").strip().upper()
    if not odp_id:
        count = db.odp_locations.count_documents({}) + 1
        odp_id = f"ODP-ALJ-{count:02d}"
    
    existing = db.odp_locations.find_one({"_id": odp_id})
    try:
        raw_lat = data.get("lat")
        raw_lng = data.get("lng")
        if (raw_lat is None or str(raw_lat).strip() in ("", "0", "0.0", "None")) and existing:
            lat = float(existing.get("lat", 0.0))
        else:
            lat = float(raw_lat or 0.0)

        if (raw_lng is None or str(raw_lng).strip() in ("", "0", "0.0", "None")) and existing:
            lng = float(existing.get("lng", 0.0))
        else:
            lng = float(raw_lng or 0.0)
    except (ValueError, TypeError):
        lat = float(existing.get("lat", 0.0)) if existing else 0.0
        lng = float(existing.get("lng", 0.0)) if existing else 0.0

    doc = {
        "_id": odp_id,
        "name": str(data.get("name") or odp_id).strip(),
        "lat": lat,
        "lng": lng,
        "capacity": int(data.get("capacity", 8)),
        "color": str(data.get("color") or "#3b82f6").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        db.odp_locations.update_one({"_id": odp_id}, {"$set": doc}, upsert=True)
        return {"success": True, "message": f"Data {odp_id} berhasil disimpan", "data": doc}
    except Exception as e:
        logger.error(f"Error saving ODP {odp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Gagal menyimpan ODP: {e}"}


def delete_geo_odp_data(odp_id):
    db = get_db()
    if db is None:
        return {"success": False, "message": "Database tidak terhubung"}
    
    if not odp_id:
        return {"success": False, "message": "ID ODP tidak boleh kosong"}
    
    try:
        res = db.odp_locations.delete_one({"_id": odp_id})
        db.device_locations.update_many({"odp": odp_id}, {"$set": {"odp": ""}})
        return {"success": True, "message": f"ODP {odp_id} berhasil dihapus"}
    except Exception as e:
        return {"success": False, "message": f"Gagal menghapus ODP: {e}"}


class BotConfigHandler(BaseHTTPRequestHandler):
    def parse_cookies(self):
        cookie_header = self.headers.get("Cookie", "")
        cookies = {}
        if cookie_header:
            for c in cookie_header.split(";"):
                if "=" in c:
                    k, v = c.strip().split("=", 1)
                    cookies[k.strip()] = v.strip()
        return cookies

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()

    def is_authenticated_admin(self):
        client_ip = self.client_address[0] if self.client_address else ""
        # Localhost bypass specifically for bot internal webhook
        parsed_path = urlparse(self.path).path
        # Localhost bypass specifically for bot internal service-to-service communication
        if parsed_path in ("/api/voice-assistant/ask", "/api/voice-assistant/tts", "/api/voice/tts", "/bot-proxy/api/voice-assistant/ask", "/bot-proxy/api/voice-assistant/tts") or (client_ip in ("127.0.0.1", "::1", "localhost") and not self.headers.get("X-Forwarded-For") and parsed_path in ("/api/agent_command", "/api/config", "/api/voice-assistant/ask", "/api/voice-assistant/tts", "/api/voice/tts")):
            return True

        cookies = self.parse_cookies()

        # Check 1: SSO via GenieACS UI JWT cookie
        jwt_cookie = cookies.get("genieacs-ui-jwt")
        if jwt_cookie:
            payload = verify_genieacs_jwt(jwt_cookie)
            if payload and payload.get("username"):
                username = payload.get("username")
                db = get_db()
                if db is not None:
                    u = db.users.find_one({"_id": username})
                    if u:
                        roles = [r.strip() for r in u.get("roles", "").split(",") if r.strip()]
                        if "admin" in roles:
                            return True

        # Check 2: Direct session cookie on port 7558
        sess_token = cookies.get("agent_session")
        if sess_token and sess_token in ACTIVE_ADMIN_SESSIONS:
            sess_data = ACTIVE_ADMIN_SESSIONS[sess_token]
            if sess_data.get("expires", 0) > time.time():
                return True
            else:
                ACTIVE_ADMIN_SESSIONS.pop(sess_token, None)

        return False

    def send_html(self, content_str, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "frame-ancestors 'self' http://*:3000 https://*:3000 http://* https://*")
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        self.end_headers()
        self.wfile.write(content_str.encode("utf-8"))

    def send_json(self, data, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Endpoint Streaming Neural TTS (id-ID-GadisNeural / id-ID-ArdiNeural)
        if path in ("/api/voice-assistant/tts", "/bot-proxy/api/voice-assistant/tts", "/api/voice/tts", "/bot-proxy/api/voice/tts", "/tts", "/api/tts"):
            qs = parse_qs(parsed.query)
            raw_text = (qs.get("text", [""])[0]).strip()
            voice = (qs.get("voice", ["id-ID-GadisNeural"])[0]).strip()
            if not raw_text:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing text parameter")
                return

            clean = clean_text_for_speech(raw_text)
            if not clean:
                clean = "Informasi selengkapnya sudah tampil di layar."

            # Opsi 1: Google ID Translate TTS (Super Ringan & Cepat < 300ms)
            if voice in ("google-id", "google", "default") or ("Neural" not in voice and voice not in ("gadis", "ardi")):
                g_buf = generate_google_speech(clean)
                if g_buf:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(g_buf)
                    return

            # Opsi 2: Microsoft Azure Neural TTS (id-ID-GadisNeural / id-ID-ArdiNeural)
            edge_voice = "id-ID-ArdiNeural" if voice in ("ardi", "id-ID-ArdiNeural") else "id-ID-GadisNeural"
            tmp_id = f"{int(time.time())}_{secrets.token_hex(4)}"
            txt_path = f"/tmp/tts_{tmp_id}.txt"
            mp3_path = f"/tmp/tts_{tmp_id}.mp3"
            try:
                with open(txt_path, "w", encoding="utf-8") as f_txt:
                    f_txt.write(clean)
                cmd = ["edge-tts", "--voice", edge_voice, "-f", txt_path, "--write-media", mp3_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.end_headers()
                    with open(mp3_path, "rb") as f_mp3:
                        self.wfile.write(f_mp3.read())
                    try:
                        os.remove(txt_path)
                        os.remove(mp3_path)
                    except Exception:
                        pass
                    return
            except Exception as e_tts:
                logger.error(f"Neural TTS streaming error: {e_tts}")
            finally:
                try:
                    if os.path.exists(txt_path):
                        os.remove(txt_path)
                except Exception:
                    pass

            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"TTS failed")
            return

        # Jalur Akses Peta & API Geolocation (Bebas CORS & Iframe)
        if path in ("/peta", "/peta.html"):
            peta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "peta.html")
            if not os.path.exists(peta_path):
                for cand in [
                    "/usr/lib/node_modules/genieacs/public/peta.html",
                    "/usr/local/lib/node_modules/genieacs/public/peta.html",
                    "/opt/genieacs/public/peta.html"
                ]:
                    if os.path.exists(cand):
                        peta_path = cand
                        break
            if os.path.exists(peta_path):
                try:
                    with open(peta_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    self.send_html(content)
                    return
                except Exception as e:
                    self.send_html(f"<h3>Gagal memuat peta: {e}</h3>", status=500)
                    return
            else:
                self.send_html("<h3>File peta.html belum tersedia</h3>", status=404)
                return

        if path == "/api/geo/devices":
            data = get_geo_devices_data()
            self.send_json(data)
            return

        if path == "/api/geo/device":
            query_params = parse_qs(parsed.query)
            dev_id = (query_params.get("id") or query_params.get("_id") or [""])[0].strip()
            if not dev_id:
                self.send_json({"success": False, "message": "Parameter id tidak boleh kosong"})
                return
            db = get_db()
            if db is None:
                self.send_json({"success": False, "message": "Database tidak terhubung"})
                return
            doc = db.device_locations.find_one({"_id": dev_id})
            data = {}
            if doc:
                data = {
                    "_id": str(doc.get("_id") or dev_id),
                    "name": str(doc.get("name") or ""),
                    "phone": str(doc.get("phone") or ""),
                    "odp": str(doc.get("odp") or ""),
                    "address": str(doc.get("address") or ""),
                    "notes": str(doc.get("notes") or ""),
                    "lat": float(doc.get("lat") or 0.0),
                    "lng": float(doc.get("lng") or 0.0),
                    "updated_at": str(doc.get("updated_at") or "")
                }
            else:
                dev_raw = db.devices.find_one({"_id": dev_id})
                pppoe = ""
                cust_phone = ""
                if dev_raw:
                    vp = dev_raw.get("VirtualParameters", {})
                    if isinstance(vp, dict):
                        pppoe = vp.get("pppoeUsername") or ""
                    for t in (dev_raw.get("_tags") or dev_raw.get("tags") or []):
                        if isinstance(t, str):
                            digits = re.sub(r"\D", "", t)
                            if len(digits) >= 8 and (digits.startswith("08") or digits.startswith("628")):
                                cust_phone = t
                                break
                data = {
                    "_id": dev_id,
                    "name": pppoe,
                    "phone": cust_phone,
                    "odp": "",
                    "address": "",
                    "notes": "",
                    "lat": 0.0,
                    "lng": 0.0,
                    "updated_at": ""
                }
            self.send_json({"success": True, "data": data})
            return

        if path == "/api/geo/odps":
            data = get_geo_odps_data()
            self.send_json(data)
            return
        # Jalur Akses Portal Mandiri Pelanggan (Bebas Domain & Agnostik)
        if path in ("/mywifi", "/mywifi.html", "/portal", "/pelanggan"):
            self.send_html(get_customer_portal_html())
            return

        if path == "/api/customer/auth_config":
            cfgs = get_config()
            otp_enabled = cfgs.get("agent.otp.enabled", "true").lower() in ("true", "1", "yes")
            b_name = cfgs.get("agent.brand.name", BRAND_NAME)
            b_phone = cfgs.get("agent.brand.phone", BRAND_PHONE)
            self.send_json({
                "success": True,
                "otp_enabled": otp_enabled,
                "brand_name": b_name,
                "brand_phone": b_phone
            })
            return

        if path in ("/admin", "/admin/"):
            if self.is_authenticated_admin():
                self.send_html(HTML_CONFIG_PAGE)
            else:
                self.send_html(HTML_LOGIN_PAGE)
            return

        if path == "/api/customer/info":
            sess = get_authenticated_customer_session(self)
            if not sess:
                self.send_json({"success": False, "error": "Sesi Anda telah berakhir. Silakan login kembali."}, status=401)
                return

            dev_id = sess.get("device_id")
            dev = find_device(dev_id)
            if not dev:
                self.send_json({"success": False, "error": "Perangkat modem tidak ditemukan di database."}, status=404)
                return

            vp = dev.get("VirtualParameters", {})
            igd = dev.get("InternetGatewayDevice", {})

            # Customer name & PPPoE
            pppoe = get_device_pppoe_username(dev)
            cust_name = dev.get("_custom_customer_name") or ""
            if not cust_name:
                db = get_db()
                if db is not None:
                    loc = db.device_locations.find_one({"_id": dev.get("_id")})
                    if loc and loc.get("name"):
                        cust_name = loc.get("name")
            if not cust_name:
                cust_name = pppoe or "Pelanggan"

            # Online status
            last_inform = dev.get("_lastInform")
            online = False
            last_inform_str = "-"
            if last_inform:
                diff_sec = get_datetime_diff_seconds(last_inform)
                online = diff_sec < 600
                last_inform_str = f"{int(diff_sec//60)} menit lalu" if diff_sec >= 60 else "Baru saja"

            # Redaman (RX Power)
            rx = vp.get("RXPower", {}).get("_value") or "-"
            rx_badge_text = "Sinyal Normal"
            rx_badge_class = "badge-success"
            if rx != "-":
                try:
                    rx_num = float(str(rx).replace("dBm", "").strip())
                    if rx_num >= -24.0:
                        rx_badge_text = "Sinyal Sangat Bagus 🟢"
                        rx_badge_class = "badge-success"
                    elif rx_num >= -27.0:
                        rx_badge_text = "Sinyal Cukup / Normal 🟡"
                        rx_badge_class = "badge-warning"
                    else:
                        rx_badge_text = "Sinyal Lemah / Redaman Tinggi 🔴"
                        rx_badge_class = "badge-danger"
                except Exception:
                    pass
                if not str(rx).endswith("dBm"):
                    rx = f"{rx} dBm"

            uptime = vp.get("getdeviceuptime", {}).get("_value") or vp.get("uptimeDevice", {}).get("_value") or "-"
            wlan1 = igd.get("LANDevice", {}).get("1", {}).get("WLANConfiguration", {}).get("1", {})
            ssid = wlan1.get("SSID", {}).get("_value") or vp.get("WlanSSID", {}).get("_value") or "-"
            wifi_pass = (
                wlan1.get("KeyPassphrase", {}).get("_value") or
                wlan1.get("PreSharedKey", {}).get("1", {}).get("KeyPassphrase", {}).get("_value") or
                vp.get("WlanPassword", {}).get("_value") or
                ""
            )
            clients = (
                wlan1.get("TotalAssociations", {}).get("_value") or
                vp.get("activedevices", {}).get("_value") or
                "0"
            )

            product_class = dev.get("DeviceID", {}).get("ProductClass", {}).get("_value") or ""
            manufacturer = dev.get("DeviceID", {}).get("Manufacturer", {}).get("_value") or ""
            model_str = f"{manufacturer} {product_class}".strip() or "ONT Router"

            cfgs = get_config()
            b_name = cfgs.get("agent.brand.name", BRAND_NAME)
            b_phone = cfgs.get("agent.brand.phone", BRAND_PHONE)

            data = {
                "success": True,
                "data": {
                    "customer_name": cust_name,
                    "pppoe_user": pppoe,
                    "online": online,
                    "last_inform": last_inform_str,
                    "rx_power": rx,
                    "rx_badge_text": rx_badge_text,
                    "rx_badge_class": rx_badge_class,
                    "uptime": uptime,
                    "clients_count": clients,
                    "ssid": ssid,
                    "wifi_password": wifi_pass,
                    "model": model_str,
                    "brand_name": b_name,
                    "brand_phone": b_phone
                }
            }
            self.send_json(data)
            return

        if not self.is_authenticated_admin():
            if self.path == "/" or self.path.startswith("/?"):
                self.send_html(get_customer_portal_html())
            else:
                self.send_json({"success": False, "error": "Akses ditolak: Harap login sebagai administrator terlebih dahulu."}, status=401)
            return

        if self.path == "/" or self.path.startswith("/?"):
            self.send_html(HTML_CONFIG_PAGE)
        elif self.path == "/api/config":
            cfgs = get_config()
            data = {
                "enabled": cfgs.get("agent.enabled", "true"),
                "token": cfgs.get("agent.telegram.botToken", ""),
                "admin_id": cfgs.get("agent.telegram.adminChatId", ""),
                "brand_name": cfgs.get("agent.brand.name", BRAND_NAME),
                "brand_phone": cfgs.get("agent.brand.phone", BRAND_PHONE),
                "gemini_key": cfgs.get("agent.gemini.apiKey", ""),
                "wa_enabled": cfgs.get("agent.whatsapp.enabled", "true"),
                "wa_admin_numbers": cfgs.get("agent.whatsapp.admin_numbers", cfgs.get("agent.brand.phone", BRAND_PHONE)),
                "otp_enabled": cfgs.get("agent.otp.enabled", "true"),
                "otp_expiry_minutes": cfgs.get("agent.otp.expiry_minutes", "5")
            }
            self.send_json(data)
        elif self.path == "/api/whatsapp/status":
            try:
                r = requests.get("http://127.0.0.1:7559/status", timeout=5.0)
                self.send_json(r.json())
            except Exception as e:
                self.send_json({"connection": "disconnected", "error": str(e)})
        elif self.path == "/api/whatsapp/lid_mappings":
            try:
                r = requests.get("http://127.0.0.1:7559/lid_mappings", timeout=2.5)
                self.send_json(r.json())
            except Exception as e:
                self.send_json({"error": str(e)})
        elif self.path == "/api/system/update_status":
            st = get_system_update_status()
            self.send_json(st)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            req = json.loads(body)
        except Exception:
            req = {}

        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/voice-assistant/ask", "/bot-proxy/api/voice-assistant/ask", "/api/agent_command", "/bot-proxy/api/agent_command"):
            raw_msg = str(req.get("message") or req.get("text") or "").strip()
            sender = str(req.get("sender") or "voice_assistant_user").strip()
            is_admin = bool(req.get("isAdmin", True))

            cfgs = get_config()
            gemini_key = cfgs.get("agent.gemini.apiKey", "")
            gemini_model = cfgs.get("agent.gemini.model", "gemini-3.5-flash-lite")

            try:
                reply_text, _ = process_agent_command(
                    user_text=raw_msg,
                    sender_id=sender,
                    is_admin=is_admin,
                    gemini_key=gemini_key,
                    gemini_model=gemini_model,
                    registered_tag=req.get("registeredTag")
                )
            except Exception as e_cmd:
                logger.error(f"Error handling voice ask: {e_cmd}")
                reply_text = f"Terjadi kesalahan: {e_cmd}"

            speech_text = clean_text_for_speech(reply_text or "")
            self.send_json({
                "ok": True,
                "text": reply_text or "",
                "speechText": speech_text,
                "reply": reply_text or ""
            })
            return

        # Endpoint API Geolocation Pelanggan & ODP
        if path == "/api/wan/set":
            dev_id = req.get("device_id") or req.get("_id") or req.get("id")
            pppoe_user = req.get("pppoe_user") or req.get("username", "")
            pppoe_pass = req.get("pppoe_pass") or req.get("password", "")
            vlan_id = req.get("vlan_id") or req.get("vlan")

            if not dev_id:
                self.send_json({"success": False, "message": "ID Perangkat tidak boleh kosong"})
                return
            if not pppoe_user:
                self.send_json({"success": False, "message": "Username PPPoE tidak boleh kosong"})
                return

            dev = find_device(dev_id)
            if not dev:
                self.send_json({"success": False, "message": f"Modem `{dev_id}` tidak ditemukan di database"})
                return

            ok, msg = add_or_set_wan_pppoe(dev, pppoe_user, pppoe_pass, vlan_id)
            self.send_json({"success": ok, "message": msg})
            return

        if path == "/api/geo/device":
            res = save_geo_device_data(req)
            self.send_json(res)
            return

        if path == "/api/geo/device/delete":
            dev_id = req.get("_id") or req.get("id")
            res = delete_geo_device_data(dev_id)
            self.send_json(res)
            return

        if path == "/api/geo/odp":
            res = save_geo_odp_data(req)
            self.send_json(res)
            return

        if path == "/api/geo/odp/delete":
            odp_id = req.get("_id") or req.get("id")
            res = delete_geo_odp_data(odp_id)
            self.send_json(res)
            return

        # Public authentication endpoints
        if self.path == "/api/login":
            username = req.get("username", "").strip()
            password = req.get("password", "").strip()
            ok, msg = verify_admin_login(username, password)
            if ok:
                token = secrets.token_hex(32)
                ACTIVE_ADMIN_SESSIONS[token] = {
                    "username": username,
                    "expires": time.time() + 86400  # 24 hours
                }
                cookie_val = f"agent_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400"
                self.send_json({"success": True, "message": "Login berhasil"}, extra_headers={"Set-Cookie": cookie_val})
            else:
                self.send_json({"success": False, "message": msg}, status=401)
            return

        elif self.path == "/api/logout":
            cookies = self.parse_cookies()
            tok = cookies.get("agent_session")
            if tok in ACTIVE_ADMIN_SESSIONS:
                ACTIVE_ADMIN_SESSIONS.pop(tok, None)
            cookie_val = "agent_session=deleted; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_json({"success": True, "message": "Logout berhasil"}, extra_headers={"Set-Cookie": cookie_val})
            return

        # Customer Portal Public APIs (Secured by WhatsApp OTP & Sessions)
        if path == "/api/customer/request_otp":
            cfgs = get_config()
            otp_enabled = cfgs.get("agent.otp.enabled", "true").lower() in ("true", "1", "yes")

            phone_raw = str(req.get("phone", "")).strip()
            if not phone_raw:
                self.send_json({"success": False, "error": "Nomor WhatsApp atau Nomor Pelanggan wajib diisi."})
                return

            clean_phone = normalize_phone(phone_raw)
            dev = find_device_by_customer_identifier(clean_phone or phone_raw)
            if not dev:
                b_phone = cfgs.get("agent.brand.phone", BRAND_PHONE)
                self.send_json({
                    "success": False,
                    "error": f"Nomor Pelanggan / WhatsApp ({phone_raw}) belum terdaftar pada sistem jaringan kami. Pastikan nomor sesuai saat pendaftaran atau hubungi CS di {b_phone}."
                })
                return

            now = time.time()

            # JIKA MODE OTP DINONAKTIFKAN: LANGSUNG LOGIN TANPA PERLU KODE OTP
            if not otp_enabled:
                token = secrets.token_hex(24)
                CUSTOMER_SESSIONS[token] = {
                    "phone": clean_phone or phone_raw,
                    "device_id": dev["_id"],
                    "expires": now + 86400,
                    "created_at": now
                }
                cookie_val = f"customer_token={token}; Path=/; SameSite=Lax; Max-Age=86400"
                self.send_json({
                    "success": True,
                    "otp_required": False,
                    "token": token,
                    "message": "Login berhasil! Mengalihkan ke dashboard WiFi..."
                }, extra_headers={"Set-Cookie": cookie_val})
                return

            # JIKA MODE OTP DIAKTIFKAN: BUAT KODE OTP 4 DIGIT & KIRIMKAN KE WHATSAPP
            lookup_key = clean_phone if clean_phone else phone_raw
            if lookup_key in CUSTOMER_OTP_STORE:
                existing = CUSTOMER_OTP_STORE[lookup_key]
                if existing.get("resend_after", 0) > now:
                    remaining = int(existing["resend_after"] - now)
                    self.send_json({"success": False, "error": f"Harap tunggu {remaining} detik sebelum meminta kode OTP baru.", "cooldown": remaining})
                    return

            try:
                exp_min = int(cfgs.get("agent.otp.expiry_minutes", "5"))
                if exp_min < 1:
                    exp_min = 1
            except Exception:
                exp_min = 5
            expiry_seconds = exp_min * 60

            otp = f"{random.randint(1000, 9999)}"
            CUSTOMER_OTP_STORE[lookup_key] = {
                "otp": otp,
                "expires": now + expiry_seconds,
                "resend_after": now + 45,
                "attempts": 0,
                "device_id": dev["_id"]
            }

            b_name = cfgs.get("agent.brand.name", BRAND_NAME)
            wa_text = (
                f"Halo! 👋\n\n"
                f"Kode verifikasi OTP untuk masuk ke Portal Mandiri WiFi {b_name} Anda adalah: *{otp}*\n\n"
                f"Demi keamanan WiFi Anda, jangan berikan kode ini kepada siapapun.\n"
                f"Kode berlaku selama {exp_min} menit."
            )

            # Cari nomor tujuan WhatsApp yang valid
            dest_phone = clean_phone
            if not dest_phone:
                db = get_db()
                if db is not None:
                    loc = db.device_locations.find_one({"_id": dev["_id"]})
                    if loc and loc.get("phone"):
                        dest_phone = normalize_phone(loc.get("phone"))

            if dest_phone:
                send_whatsapp_message_local(dest_phone, wa_text)

            self.send_json({
                "success": True,
                "otp_required": True,
                "message": "Kode OTP 4 digit telah dikirim ke WhatsApp Anda.",
                "cooldown": 45
            })
            return

        if path == "/api/customer/verify_otp":
            phone_raw = str(req.get("phone", "")).strip()
            otp_input = str(req.get("otp", "")).strip()
            clean_phone = normalize_phone(phone_raw)
            lookup_key = clean_phone if (clean_phone and clean_phone in CUSTOMER_OTP_STORE) else phone_raw

            if not lookup_key or not otp_input:
                self.send_json({"success": False, "error": "Nomor dan kode OTP wajib diisi."})
                return

            if lookup_key not in CUSTOMER_OTP_STORE:
                self.send_json({"success": False, "error": "Kode OTP tidak ditemukan atau telah kedaluwarsa. Silakan minta kode baru."})
                return

            stored = CUSTOMER_OTP_STORE[lookup_key]
            now = time.time()
            if stored.get("expires", 0) < now:
                CUSTOMER_OTP_STORE.pop(lookup_key, None)
                self.send_json({"success": False, "error": "Kode OTP telah kedaluwarsa. Silakan minta kode baru."})
                return

            stored["attempts"] = stored.get("attempts", 0) + 1
            if stored["attempts"] > 5:
                CUSTOMER_OTP_STORE.pop(lookup_key, None)
                self.send_json({"success": False, "error": "Terlalu banyak percobaan salah. Silakan minta kode OTP baru."})
                return

            if stored.get("otp") != otp_input:
                self.send_json({"success": False, "error": "Kode OTP salah. Pastikan 4 digit yang Anda masukkan sesuai."})
                return

            dev_id = stored.get("device_id")
            CUSTOMER_OTP_STORE.pop(lookup_key, None)

            token = secrets.token_hex(24)
            CUSTOMER_SESSIONS[token] = {
                "phone": clean_phone or phone_raw,
                "device_id": dev_id,
                "expires": now + 86400,
                "created_at": now
            }
            cookie_val = f"customer_token={token}; Path=/; SameSite=Lax; Max-Age=86400"
            self.send_json({"success": True, "token": token}, extra_headers={"Set-Cookie": cookie_val})
            return

        if path == "/api/customer/update_wifi":
            sess = get_authenticated_customer_session(self)
            if not sess:
                self.send_json({"success": False, "error": "Sesi login Anda telah berakhir. Silakan login kembali."}, status=401)
                return

            new_ssid = str(req.get("ssid", "")).strip() if req.get("ssid") is not None else ""
            new_pass = str(req.get("password", "")).strip() if req.get("password") is not None else ""

            if not new_ssid and not new_pass:
                self.send_json({"success": False, "error": "Harap masukkan Nama WiFi atau Kata Sandi yang ingin diubah."})
                return

            if new_pass and len(new_pass) < 8:
                self.send_json({"success": False, "error": "Kata sandi WiFi minimal harus 8 karakter."})
                return

            dev = find_device(sess.get("device_id"))
            if not dev:
                self.send_json({"success": False, "error": "Perangkat modem tidak ditemukan."}, status=404)
                return

            ok, msg = set_wifi_credentials(
                dev,
                new_ssid=new_ssid if new_ssid else None,
                new_password=new_pass if new_pass else None
            )
            if ok:
                if new_ssid and new_pass:
                    m = "Nama WiFi dan Kata Sandi berhasil diperbarui!"
                elif new_ssid:
                    m = f"Nama WiFi berhasil diubah menjadi '{new_ssid}'!"
                else:
                    m = "Kata Sandi WiFi berhasil diperbarui!"
                self.send_json({"success": True, "message": m})
            else:
                self.send_json({"success": False, "error": f"Gagal memperbarui WiFi: {msg}"})
            return

        if path == "/api/customer/reboot":
            sess = get_authenticated_customer_session(self)
            if not sess:
                self.send_json({"success": False, "error": "Sesi login Anda telah berakhir. Silakan login kembali."}, status=401)
                return

            dev = find_device(sess.get("device_id"))
            if not dev:
                self.send_json({"success": False, "error": "Perangkat modem tidak ditemukan."}, status=404)
                return

            ok, msg = reboot_device_task(dev)
            if ok:
                self.send_json({"success": True, "message": "Perintah restart berhasil dikirim ke modem."})
            else:
                self.send_json({"success": False, "error": f"Gagal restart modem: {msg}"})
            return

        if path == "/api/customer/logout":
            token = self.headers.get("X-Customer-Token")
            if not token:
                cookies = self.parse_cookies()
                token = cookies.get("customer_token")
            if token and token in CUSTOMER_SESSIONS:
                CUSTOMER_SESSIONS.pop(token, None)
            cookie_val = "customer_token=deleted; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_json({"success": True, "message": "Logout berhasil"}, extra_headers={"Set-Cookie": cookie_val})
            return


        # Check authentication for all protected endpoints
        if not self.is_authenticated_admin():
            self.send_json({"success": False, "error": "Akses ditolak: Harap login sebagai administrator terlebih dahulu."}, status=401)
            return

        if self.path == "/api/config":
            db = get_db()
            if db is None:
                self.send_json({"success": False, "message": "Gagal terhubung ke MongoDB"})
                return

            configs_to_save = {
                "agent.enabled": req.get("enabled", "true"),
                "agent.telegram.botToken": f'"{req.get("token", "").strip()}"',
                "agent.telegram.adminChatId": f'"{req.get("admin_id", "").strip()}"',
                "agent.brand.name": f'"{req.get("brand_name", BRAND_NAME).strip()}"',
                "agent.brand.phone": f'"{req.get("brand_phone", BRAND_PHONE).strip()}"',
                "agent.gemini.apiKey": f'"{req.get("gemini_key", "").strip()}"',
                "agent.whatsapp.enabled": f'"{req.get("wa_enabled", "true").strip()}"',
                "agent.whatsapp.admin_numbers": f'"{req.get("wa_admin_numbers", BRAND_PHONE).strip()}"',
                "agent.otp.enabled": f'"{req.get("otp_enabled", "true").strip()}"',
                "agent.otp.expiry_minutes": f'"{req.get("otp_expiry_minutes", "5").strip()}"'
            }

            for k, v in configs_to_save.items():
                db.config.update_one({"_id": k}, {"$set": {"value": v}}, upsert=True)

            # Immediately update in-memory branding variables in agent.py
            update_branding(get_config())
            try:
                wa_payload = {
                    "brand_name": BRAND_NAME,
                    "brand_phone": BRAND_PHONE,
                    "wa_admin_numbers": req.get("wa_admin_numbers", BRAND_PHONE).strip()
                }
                requests.post("http://127.0.0.1:7559/reload_admins", json=wa_payload, timeout=2.0)
            except Exception as e:
                logger.warning(f"Failed to notify WhatsApp service: {e}")

            logger.info("Konfigurasi bot berhasil disimpan melalui Web UI (Port 7558)!")
            self.send_json({"success": True, "message": "Konfigurasi berhasil disimpan"})

        elif self.path == "/api/system/update_apply":
            res = apply_system_update()
            self.send_json(res)
        elif self.path in ["/api/whatsapp/logout", "/api/whatsapp/reset"]:
            try:
                requests.post("http://127.0.0.1:7559/logout", timeout=4.0)
            except Exception:
                pass

            auth_dirs = [
                "/opt/genieacs-agent/auth_info_baileys",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_info_baileys")
            ]
            for ad in auth_dirs:
                if os.path.exists(ad):
                    try:
                        import shutil
                        shutil.rmtree(ad, ignore_errors=True)
                    except Exception:
                        pass

            try:
                import subprocess
                subprocess.run(["systemctl", "restart", "genieacs-whatsapp.service"], check=False)
            except Exception:
                pass

            self.send_json({"success": True, "message": "Sesi WhatsApp berhasil dihapus dan bot direset"})

        elif self.path == "/api/agent_command":
            text = req.get("text", "")
            sender = req.get("sender", "anonymous")
            is_admin = bool(req.get("isAdmin", False))
            push_name = req.get("pushName", "")
            reg_tag = req.get("registeredTag", None)

            cfgs = get_config()
            gemini_key = cfgs.get("agent.gemini.apiKey", "")
            gemini_model = cfgs.get("agent.gemini.model", "gemini-1.5-flash")

            try:
                reply_text, _ = process_agent_command(
                    user_text=text,
                    sender_id=sender,
                    is_admin=is_admin,
                    gemini_key=gemini_key,
                    gemini_model=gemini_model,
                    registered_tag=reg_tag
                )
                self.send_json({"success": True, "reply": reply_text})
            except Exception as e:
                logger.error(f"Error handling agent_command '{text}': {e}", exc_info=True)
                self.send_json({"success": False, "reply": f"⚠️ Terjadi error internal saat memproses perintah `{text}`: {e}"})

        elif self.path == "/api/test":
            token = req.get("token", "").strip()
            admin_id = req.get("admin_id", "").strip()
            if not token or not admin_id:
                self.send_json({"success": False, "message": "Token dan Chat ID tidak boleh kosong!"})
                return

            ids = parse_admin_chat_ids(admin_id)
            test_msg = f"🧪 *Tes Notifikasi Bot GenieACS*\n━━━━━━━━━━━━━━━━━━━━\nKoneksi berhasil! Bot siap digunakan ({BRAND_NAME})."
            success_count = 0
            err_msg = ""
            for aid in ids:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                try:
                    r = requests.post(url, json={"chat_id": aid, "text": test_msg, "parse_mode": "Markdown"}, timeout=8)
                    if r.status_code == 200:
                        success_count += 1
                    else:
                        err_msg = r.text
                except Exception as e:
                    err_msg = str(e)

            if success_count > 0:
                self.send_json({"success": True})
            else:
                self.send_json({"success": False, "message": err_msg})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_web_server(port=7558):
    try:
        server = DefaultHTTPServer(("0.0.0.0", port), BotConfigHandler)
        logger.info(f"Bot Web Config UI berjalan di http://0.0.0.0:{port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Gagal menjalankan Bot Web Config server di port {port}: {e}")

def main():
    logger.info("Starting ALIJAYA NET GenieACS AI Agent Service...")
    web_thread = threading.Thread(target=start_web_server, args=(7558,), daemon=True)
    web_thread.start()
    last_update_id = 0
    notified_online = False
    last_watchdog_time = 0
    
    while True:
        try:
            cfgs = get_config()
            update_branding(cfgs)
            enabled = cfgs.get("agent.enabled", "true").lower() == "true"
            token = cfgs.get("agent.telegram.botToken", "")
            admin_cfg_str = cfgs.get("agent.telegram.adminChatId", "")
            admin_ids = parse_admin_chat_ids(admin_cfg_str)
            gemini_key = cfgs.get("agent.gemini.apiKey", "")
            gemini_model = cfgs.get("agent.gemini.model", "gemini-1.5-flash")
            
            if not enabled:
                logger.info("Agent is disabled in config (agent.enabled=false). Sleeping...")
                time.sleep(30)
                continue
                
            if not is_valid_token(token):
                logger.info("Menunggu konfigurasi token Telegram di GenieACS Web UI (Admin -> Config)...")
                time.sleep(15)
                continue
                
            if not notified_online:
                try:
                    logger.info("Memeriksa dan menonaktifkan webhook Telegram lama (jika ada)...")
                    wh_res = requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=False", timeout=8)
                    if wh_res.status_code == 200:
                        logger.info("Webhook Telegram berhasil dinonaktifkan (mode long polling aktif).")
                except Exception as e:
                    logger.warning(f"Gagal memeriksa/menghapus webhook: {e}")
                register_bot_commands(token)
                greeting = (
                    f"🚀 *{BRAND_NAME} GenieACS Bot Aktif!*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Menu interaktif, audit redaman, deteksi ONT baru & kontrol TR-069 siap melayani.\n"
                    "Ketik `/menu` atau klik tombol di bawah untuk mulai."
                )
                for aid in admin_ids:
                    send_telegram(token, aid, greeting, reply_markup=get_main_menu_keyboard())
                notified_online = True
                logger.info(f"Bot Telegram berhasil terhubung dan siap melayani ({BRAND_NAME})!")

            # Periodic Watchdog (setiap 60 detik)
            now = time.time()
            if (now - last_watchdog_time) >= 60:
                check_proactive_alerts(token, admin_ids)
                last_watchdog_time = now

            # Poll Telegram Updates
            poll_url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=15"
            r = requests.get(poll_url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                for upd in data.get("result", []):
                    last_update_id = upd.get("update_id", last_update_id)
                    
                    cb = upd.get("callback_query")
                    if cb:
                        cb_id = cb.get("id")
                        cb_sender = str(cb.get("from", {}).get("id", ""))
                        cb_data = cb.get("data", "")
                        if admin_ids and not is_authorized(cb_sender, admin_ids):
                            answer_callback(token, cb_id, f"Akses ditolak! Bukan Admin/Teknisi {BRAND_NAME}.", show_alert=True)
                            continue
                        handle_callback_query(token, cb_sender, cb_data, cb_id)
                        continue

                    msg = upd.get("message", {})
                    chat = msg.get("chat", {})
                    sender_id = str(chat.get("id", ""))
                    text = msg.get("text", "")
                    voice = msg.get("voice") or msg.get("audio")
                    
                    if admin_ids and not is_authorized(sender_id, admin_ids):
                        logger.warning(f"Unauthorized chat from {sender_id}: {text}")
                        send_telegram(token, sender_id, f"⛔ Akses Ditolak: ID Anda ({sender_id}) bukan Admin/Teknisi {BRAND_NAME}.")
                        continue
                    
                    # Handler Pesan Suara (Voice Note / Audio Telegram)
                    if voice:
                        file_id = voice.get("file_id")
                        mime = voice.get("mime_type", "audio/ogg")
                        logger.info(f"Received voice note from {sender_id}, transcribing...")
                        audio_data = download_telegram_file(token, file_id)
                        if audio_data:
                            try:
                                requests.post(f"https://api.telegram.org/bot{token}/sendChatAction", json={"chat_id": sender_id, "action": "record_voice"}, timeout=5)
                            except Exception:
                                pass
                            transcribed = transcribe_audio_with_gemini(gemini_key, gemini_model, audio_data, mime_type=mime)
                            if transcribed:
                                logger.info(f"Voice transcribed: '{transcribed}' from {sender_id}")
                                send_telegram(token, sender_id, f"🎙️ *Perintah Suara:*\n_{transcribed}_")
                                try:
                                    handle_incoming_message(token, sender_id, transcribed, gemini_key, gemini_model, is_voice=True)
                                finally:
                                    VOICE_SESSION_USERS.discard(str(sender_id))
                            else:
                                send_telegram(token, sender_id, "⚠️ Maaf, perintah suara tidak dapat dikenali atau Gemini API belum aktif.")
                        else:
                            send_telegram(token, sender_id, "⚠️ Gagal mengunduh file suara dari Telegram.")
                        continue
                        
                    if text:
                        logger.info(f"Received command: '{text}' from {sender_id}")
                        try:
                            handle_incoming_message(token, sender_id, text, gemini_key, gemini_model, is_voice=False)
                        finally:
                            VOICE_SESSION_USERS.discard(str(sender_id))
            elif r.status_code == 409:
                logger.warning("Telegram polling returned HTTP 409 (Conflict/Webhook). Menghapus webhook lama secara otomatis...")
                try:
                    requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=False", timeout=8)
                except Exception:
                    pass
                time.sleep(3)
            else:
                logger.warning(f"Telegram polling returned HTTP {r.status_code}")
                time.sleep(5)
                
        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
