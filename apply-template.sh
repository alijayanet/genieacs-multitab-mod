#!/bin/bash
# ==============================================================================
# SCRIPT PENERAP TAMPILAN & FITUR INFORMATIF GENIEACS (ALIJAYA NET)
# Mengubah GenieACS standar menjadi GenieACS Informatif Multi-Tab:
# WAN (Add WAN/PPPoE), WLAN (Multi-SSID & Client RSSI), LAN (Port LAN & Hosts),
# USER (Web GUI Direct Link), TR-069 (CWMP Config), dan Bebas Fault.
#
# Dibuat oleh: ALIJAYA NET (WhatsApp: 081947215703)
# ==============================================================================

set -e

# Warna output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

clear 2>/dev/null || true
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${BOLD}${GREEN}           🎨 ALIJAYA NET - TEMA & FITUR INFORMATIF GENIEACS          ${NC}${CYAN}║${NC}"
echo -e "${CYAN}║${BOLD}${YELLOW}       Upgrade GenieACS Standar Menjadi Multi-Tab & Informatif        ${NC}${CYAN}║${NC}"
echo -e "${CYAN}║                                                                      ║${NC}"
echo -e "${CYAN}║${NC}  👑 ${BOLD}Pengembang${NC}         : ${GREEN}${BOLD}ALIJAYA NET${NC}                                    ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  📱 ${BOLD}WhatsApp / Kontak${NC}  : ${YELLOW}${BOLD}081947215703${NC}                                   ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Pastikan root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Jalankan script ini sebagai user root! (sudo bash $0)${NC}"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)"
ARCHIVE="${SCRIPT_DIR}/genieacs_template_ui.tar.gz"

if [ ! -f "$ARCHIVE" ]; then
  if [ -f "./genieacs_template_ui.tar.gz" ]; then
    ARCHIVE="./genieacs_template_ui.tar.gz"
  elif [ -f "/root/genieacs_template_ui.tar.gz" ]; then
    ARCHIVE="/root/genieacs_template_ui.tar.gz"
  elif [ -f "${SCRIPT_DIR}/genieacs_db.tar.gz" ]; then
    ARCHIVE="${SCRIPT_DIR}/genieacs_db.tar.gz"
  elif [ -f "./genieacs_db.tar.gz" ]; then
    ARCHIVE="./genieacs_db.tar.gz"
  elif [ -f "/root/genieacs_db.tar.gz" ]; then
    ARCHIVE="/root/genieacs_db.tar.gz"
  else
    echo -e "${RED}[ERROR] File genieacs_template_ui.tar.gz atau genieacs_db.tar.gz tidak ditemukan di folder ini!${NC}"
    echo "Pastikan file template berada dalam satu folder dengan script ini."
    exit 1
  fi
fi

# Pasang dependensi dasar Python jika belum ada
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y python3-requests python3-pymongo 2>/dev/null || true

# Cek mongorestore
if ! command -v mongorestore >/dev/null 2>&1; then
  echo -e "${YELLOW}[!] Memasang paket mongo-tools (mongorestore)...${NC}"
  apt-get update -y >/dev/null 2>&1 && apt-get install -y mongo-tools >/dev/null 2>&1 || true
  if ! command -v mongorestore >/dev/null 2>&1; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
      TOOLS_URL="https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu2004-arm64-100.9.4.tgz"
    else
      TOOLS_URL="https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu2004-x86_64-100.9.4.tgz"
    fi
    echo -e "${YELLOW}Mengunduh binary mongorestore resmi ($ARCH)...${NC}"
    wget -q "$TOOLS_URL" -O /tmp/tools.tgz && \
    tar -zxvf /tmp/tools.tgz -C /tmp/ && \
    cp -f /tmp/mongodb-database-tools-*/bin/* /usr/bin/ && \
    rm -rf /tmp/tools.tgz /tmp/mongodb-database-tools-* && \
    chmod +x /usr/bin/mongo*
  fi
fi

# Deteksi URI MongoDB secara dinamis (membaca .env & memvalidasi ping koneksi aktif)
MONGO_URI=$(python3 - << 'EOF'
import os, sys, pymongo

candidates = []
# 1. Dari Environment
if os.environ.get("GENIEACS_MONGODB_CONNECTION_URL"):
    candidates.append(os.environ.get("GENIEACS_MONGODB_CONNECTION_URL"))

# 2. Dari File Konfigurasi GenieACS
for path in ["/opt/genieacs/genieacs.env", "/etc/genieacs.env", "/etc/default/genieacs"]:
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GENIEACS_MONGODB_CONNECTION_URL="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and val not in candidates:
                            candidates.append(val)
        except Exception:
            pass

# 3. Default Candidates
for default_uri in [
    "mongodb://genie:genie@127.0.0.1:27017/genieacs",
    "mongodb://genie:genie@127.0.0.1/genieacs",
    "mongodb://127.0.0.1:27017/genieacs",
    "mongodb://127.0.0.1/genieacs",
    "mongodb://localhost:27017/genieacs"
]:
    if default_uri not in candidates:
        candidates.append(default_uri)

working_uri = ""
for uri in candidates:
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000)
        db_name = "genieacs"
        try:
            p = client.get_default_database()
            if p is not None:
                db_name = p.name
        except Exception:
            pass
        client[db_name].command("ping")
        working_uri = uri
        break
    except Exception:
        continue

print(working_uri if working_uri else "mongodb://genie:genie@127.0.0.1:27017/genieacs")
EOF
)

echo -e "${BLUE}[INFO] URI MongoDB terdeteksi:${NC} ${GREEN}${MONGO_URI}${NC}"

echo -e "${BLUE}[1/3] Mengekstrak template tampilan & parameter...${NC}"
TMP_DIR="/tmp/genieacs_template_$$"
mkdir -p "$TMP_DIR"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
# Proteksi data server yang sudah jalan: jangan timpa akun user, permission, atau data perangkat
rm -f "$TMP_DIR/genieacs/users."* "$TMP_DIR/genieacs/permissions."* "$TMP_DIR/genieacs/devices."* "$TMP_DIR/genieacs/faults."* "$TMP_DIR/genieacs/tasks."* 2>/dev/null || true

echo -e "${BLUE}[2/3] Menerapkan konfigurasi UI, Virtual Parameters & Provisions...${NC}"
echo -e "${YELLOW}Catatan: Data perangkat (devices) & akun user server ini 100% AMAN (TIDAK AKAN TERHAPUS).${NC}"

RESTORE_OK=0
if command -v mongorestore >/dev/null 2>&1; then
  if mongorestore --uri="$MONGO_URI" --drop "$TMP_DIR/genieacs" >/dev/null 2>&1; then
    RESTORE_OK=1
  elif mongorestore --drop "$TMP_DIR/genieacs" >/dev/null 2>&1; then
    RESTORE_OK=1
  fi
fi

# Fallback restore dengan PyMongo dan BSON jika mongorestore gagal atau terkendala izin
if [ "$RESTORE_OK" -ne 1 ]; then
  echo -e "${YELLOW}Menjalankan Python PyMongo fallback restore...${NC}"
  if python3 -c '
import os, sys, pymongo, bson
target_dir = sys.argv[1]
uri = sys.argv[2]
try:
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
    db_name = "genieacs"
    try:
        p = client.get_default_database()
        if p is not None:
            db_name = p.name
    except Exception:
        pass
    db = client[db_name]
    for f in os.listdir(target_dir):
        if f.endswith(".bson"):
            col = f[:-5]
            with open(os.path.join(target_dir, f), "rb") as bf:
                docs = bson.decode_all(bf.read())
                if docs:
                    db[col].drop()
                    db[col].insert_many(docs)
    sys.exit(0)
except Exception as e:
    print(f"Fallback restore error: {e}", file=sys.stderr)
    sys.exit(1)
' "$TMP_DIR/genieacs" "$MONGO_URI" 2>/dev/null; then
    RESTORE_OK=1
  fi
fi

if [ "$RESTORE_OK" -eq 1 ]; then
  echo -e "${GREEN}[OK] Template UI, Virtual Parameters, Presets & Provisions berhasil diterapkan!${NC}"
else
  echo -e "${RED}[WARNING] Terjadi kendala saat restore template. Silakan periksa koneksi MongoDB.${NC}"
fi

# Bersihkan cache hash UI lokal agar langsung update tampilan
python3 -c '
import sys, pymongo
uri = sys.argv[1]
try:
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000)
    db_name = "genieacs"
    try:
        p = client.get_default_database()
        if p is not None:
            db_name = p.name
    except Exception:
        pass
    client[db_name].config.delete_one({"_id": "ui-local-cache-hash"})
    tab6_configs = {
        'ui.multiTabs.6.label': "'INFO'",
        'ui.multiTabs.6.route': "'info'",
        'ui.multiTabs.6.components.0.type': "'tags'",
        'ui.multiTabs.6.components.1.type': "'ping'",
        'ui.multiTabs.6.components.2.type': "'customer-info'",
        'ui.multiTabs.6.components.3.type': "'device-actions'"
    }
    for k, v in tab6_configs.items():
        client[db_name].config.replace_one({'_id': k}, {'_id': k, 'value': v}, upsert=True)
except Exception:
    pass
' "$MONGO_URI" 2>/dev/null || true

rm -rf "$TMP_DIR"

# Terapkan UI Frontend Multi-Tab & Modifikasi Binaries (ALIJAYA NET)
MOD_ARCHIVE=""
if [ -f "${SCRIPT_DIR}/genieacs_ui_mod.tar.gz" ]; then
  MOD_ARCHIVE="${SCRIPT_DIR}/genieacs_ui_mod.tar.gz"
elif [ -f "./genieacs_ui_mod.tar.gz" ]; then
  MOD_ARCHIVE="./genieacs_ui_mod.tar.gz"
elif [ -f "/root/genieacs-multitab-mod/genieacs_ui_mod.tar.gz" ]; then
  MOD_ARCHIVE="/root/genieacs-multitab-mod/genieacs_ui_mod.tar.gz"
fi

if [ -n "$MOD_ARCHIVE" ] && [ -f "$MOD_ARCHIVE" ]; then
  echo -e "${YELLOW}Menerapkan tema & modul tampilan Multi-Tab (ALIJAYA NET)...${NC}"
  GENIE_DIR=""
  if [ -d "/usr/lib/node_modules/genieacs" ]; then
    GENIE_DIR="/usr/lib/node_modules/genieacs"
  elif [ -d "/usr/local/lib/node_modules/genieacs" ]; then
    GENIE_DIR="/usr/local/lib/node_modules/genieacs"
  fi
  
  if [ -n "$GENIE_DIR" ]; then
    tar -zxf "$MOD_ARCHIVE" --strip-components=1 -C "$GENIE_DIR/" 2>/dev/null || tar -zxf "$MOD_ARCHIVE" -C "$GENIE_DIR/"
    if [ -d "$GENIE_DIR/genieacs/public" ]; then
      cp -rf "$GENIE_DIR/genieacs/"* "$GENIE_DIR/"
      rm -rf "$GENIE_DIR/genieacs"
    fi
    chmod +x "$GENIE_DIR/bin/"* 2>/dev/null || true
    cp -f "$GENIE_DIR/bin/"* /usr/bin/ 2>/dev/null || true
    cp -f "$GENIE_DIR/bin/"* /usr/local/bin/ 2>/dev/null || true
    chmod +x /usr/bin/genieacs-* /usr/local/bin/genieacs-* 2>/dev/null || true
    echo -e "${GREEN}[OK] File frontend Multi-Tab & Binaries berhasil diterapkan!${NC}"
  fi
fi


# Pasang script agen jika ada di direktori
mkdir -p /opt/genieacs-agent
if [ -f "${SCRIPT_DIR}/agent.py" ]; then
  cp "${SCRIPT_DIR}/agent.py" /opt/genieacs-agent/agent.py
elif [ -f "./agent.py" ]; then
  cp "./agent.py" /opt/genieacs-agent/agent.py
fi
chmod +x /opt/genieacs-agent/agent.py 2>/dev/null || true

# Salin aset frontend public (mywifi.html, peta.html, dsb)
if [ -d "${SCRIPT_DIR}/public" ]; then
  mkdir -p /opt/genieacs-agent/public
  cp -rf "${SCRIPT_DIR}/public"/* /opt/genieacs-agent/public/ 2>/dev/null || true
  if [ -n "$GENIE_DIR" ] && [ -d "$GENIE_DIR/public" ]; then
    cp -rf "${SCRIPT_DIR}/public"/* "$GENIE_DIR/public/" 2>/dev/null || true
  fi
fi

# CLI Helper set-bot
if [ -f "${SCRIPT_DIR}/set-bot.py" ]; then
  cp "${SCRIPT_DIR}/set-bot.py" /opt/genieacs-agent/set-bot.py
elif [ -f "./set-bot.py" ]; then
  cp "./set-bot.py" /opt/genieacs-agent/set-bot.py
fi
if [ -f /opt/genieacs-agent/set-bot.py ]; then
  chmod +x /opt/genieacs-agent/set-bot.py
  ln -sf /opt/genieacs-agent/set-bot.py /usr/local/bin/set-bot
fi

# Pasang WhatsApp Baileys Gateway Agent
if [ -d "${SCRIPT_DIR}/whatsapp" ]; then
  cp -r "${SCRIPT_DIR}/whatsapp"/* /opt/genieacs-agent/
elif [ -d "./whatsapp" ]; then
  cp -r ./whatsapp/* /opt/genieacs-agent/
fi

if command -v npm >/dev/null 2>&1; then
  echo -e "${BLUE}Menginstall dependensi WhatsApp Baileys di /opt/genieacs-agent...${NC}"
  (cd /opt/genieacs-agent && npm install @whiskeysockets/baileys@7.0.0-rc11 pino@^9.6.0 qrcode@^1.5.4 qrcode-terminal@^0.12.0 --ignore-scripts --no-audit --no-fund 2>/dev/null || true)
fi

cat << 'EOF' > /etc/systemd/system/genieacs-agent.service
[Unit]
Description=GenieACS AI Telegram Agent (ALIJAYA NET)
After=network.target mongod.service genieacs-nbi.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/genieacs-agent
EnvironmentFile=-/opt/genieacs/genieacs.env
EnvironmentFile=-/etc/default/genieacs
EnvironmentFile=-/etc/genieacs.env
ExecStart=/usr/bin/python3 /opt/genieacs-agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat << 'EOF' > /etc/systemd/system/genieacs-whatsapp.service
[Unit]
Description=GenieACS WhatsApp AI Agent (Baileys Gateway - ALIJAYA NET)
After=network.target mongod.service genieacs-nbi.service genieacs-agent.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/genieacs-agent
ExecStart=/usr/bin/node --experimental-global-webcrypto /opt/genieacs-agent/whatsapp-bot.mjs
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable genieacs-agent.service genieacs-whatsapp.service 2>/dev/null || true
systemctl restart genieacs-agent.service genieacs-whatsapp.service 2>/dev/null || true

# Pastikan symlink binary genieacs-* selalu ada di /usr/bin/ dan /usr/local/bin/
for mod in "cwmp" "nbi" "fs" "ui"; do
  BIN_LOC=""
  if [ -x "/usr/bin/genieacs-${mod}" ]; then
    BIN_LOC="/usr/bin/genieacs-${mod}"
  elif [ -x "/usr/local/bin/genieacs-${mod}" ]; then
    BIN_LOC="/usr/local/bin/genieacs-${mod}"
  else
    BIN_LOC=$(find /usr /root/.nvm /opt -name "genieacs-${mod}" 2>/dev/null | head -n 1)
  fi
  
  if [ -n "$BIN_LOC" ]; then
    [ "$BIN_LOC" != "/usr/bin/genieacs-${mod}" ] && ln -sf "$BIN_LOC" "/usr/bin/genieacs-${mod}"
    [ "$BIN_LOC" != "/usr/local/bin/genieacs-${mod}" ] && ln -sf "$BIN_LOC" "/usr/local/bin/genieacs-${mod}"
  fi
  chmod +x "/usr/bin/genieacs-${mod}" 2>/dev/null || true
done

# Pastikan proteksi reboot / mati listrik (Armbian Ramlog & tmpfs zram)
mkdir -p /etc/tmpfiles.d
cat << 'EOF' > /etc/tmpfiles.d/genieacs-mongodb.conf
d /var/log/mongodb 0755 mongodb mongodb -
d /run/mongodb 0755 mongodb mongodb -
d /var/lib/mongodb 0755 mongodb mongodb -
d /var/log/genieacs 0775 genieacs genieacs -
d /opt/genieacs/ext 0775 genieacs genieacs -
EOF
systemd-tmpfiles --create /etc/tmpfiles.d/genieacs-mongodb.conf 2>/dev/null || true

# Update service mongod dengan ExecStartPre & Restart=always jika file service ada
if [ -f /lib/systemd/system/mongod.service ] || [ -f /etc/systemd/system/mongod.service ]; then
  cat << 'EOF' > /lib/systemd/system/mongod.service
[Unit]
Description=MongoDB Database Server
Documentation=https://docs.mongodb.org/manual
After=network-online.target
Wants=network-online.target

[Service]
User=mongodb
Group=mongodb
EnvironmentFile=-/etc/default/mongod
PermissionsStartOnly=true
ExecStartPre=/usr/bin/install -d -m 0755 -o mongodb -g mongodb /var/log/mongodb /run/mongodb /var/lib/mongodb
ExecStart=/usr/bin/mongod --config /etc/mongod.conf
PIDFile=/run/mongodb/mongod.pid
Restart=always
RestartSec=3
LimitFSIZE=infinity
LimitCPU=infinity
LimitAS=infinity
LimitNOFILE=64000
LimitNPROC=64000
LimitMEMLOCK=infinity
TasksMax=infinity
TasksAccounting=false

[Install]
WantedBy=multi-user.target
EOF
fi

# Update service GenieACS (cwmp, nbi, fs, ui) dengan ExecStartPre & Wants=mongod.service
if [ -f /opt/genieacs/genieacs.env ]; then
  for mod in "cwmp" "nbi" "fs" "ui"; do
    cat << EOF > /etc/systemd/system/genieacs-${mod}.service
[Unit]
Description=GenieACS ${mod^^}
After=network.target mongod.service
Wants=mongod.service

[Service]
User=genieacs
Group=genieacs
EnvironmentFile=/opt/genieacs/genieacs.env
PermissionsStartOnly=true
ExecStartPre=/usr/bin/install -d -m 0775 -o genieacs -g genieacs /var/log/genieacs /opt/genieacs/ext
ExecStart=/usr/bin/genieacs-${mod}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  done
fi

journalctl --vacuum-size=10M 2>/dev/null || true
systemctl daemon-reload
systemctl enable mongod genieacs-cwmp genieacs-nbi genieacs-fs genieacs-ui 2>/dev/null || true

echo -e "${BLUE}[3/3] Merestart layanan GenieACS & Agent...${NC}"
systemctl restart genieacs-ui genieacs-cwmp genieacs-nbi genieacs-fs genieacs-agent genieacs-whatsapp 2>/dev/null || {
  service genieacs-ui restart 2>/dev/null || true
  service genieacs-cwmp restart 2>/dev/null || true
}

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}✔ SUKSES! Tampilan, Fitur Informatif, Telegram & WhatsApp Bot Aktif!${NC}"
echo -e "${CYAN}• Tab Aktif    : LAN, WAN (Add WAN Button), WLAN (Multi-SSID), USER, TR069${NC}"
echo -e "${CYAN}• Fitur Data   : Optical Power Rx/Tx, Host LAN Clients, WiFi Clients RSSI${NC}"
echo -e "${CYAN}• Telegram Bot : AKTIF (Port 7558 / ketik 'set-bot' di terminal)${NC}"
echo -e "${CYAN}• WhatsApp Bot : AKTIF (Baileys Gateway Port 7559 / Scan QR di port 7558)${NC}"
echo -e "${YELLOW}• Web Bot UI   : Buka menu '🤖 Bot AI & WA' di GenieACS atau port 7558${NC}"
echo -e "${CYAN}• Status Sesi  : Provision Bebas Fault & Kompatibel Semua Merk ONT${NC}"
echo -e "${YELLOW}Silakan buka browser dan refresh (Ctrl + F5) pada halaman GenieACS UI.${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}Bantuan & Konsultasi: WhatsApp 081947215703 (ALIJAYA NET)${NC}"
