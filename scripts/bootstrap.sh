#!/bin/bash
set -euo pipefail

# ==========================================
# CREATE DEDICATED APPLICATION USER
# ==========================================

useradd \
  --system \
  --user-group \
  --no-create-home \
  --shell /sbin/nologin \
  cloudsec


# ==========================================
# CREATE APPLICATION DIRECTORY
# ==========================================

mkdir -p /opt/cloudsec-app


# ==========================================
# CREATE DEMONSTRATION WEB PAGE
# ==========================================

cat > /opt/cloudsec-app/index.html <<'HTML'
<!DOCTYPE html>
<html>
<head>
    <title>AWS Secure Infrastructure</title>
</head>
<body>
    <h1>AWS Secure Infrastructure Blueprint</h1>
    <p>Application is running successfully.</p>
    <p>Served from a private EC2 instance.</p>
</body>
</html>
HTML


# ==========================================
# SET RESTRICTIVE FILE PERMISSIONS
# ==========================================

chown -R root:cloudsec /opt/cloudsec-app

chmod 750 /opt/cloudsec-app
chmod 640 /opt/cloudsec-app/index.html


# ==========================================
# CREATE SYSTEMD SERVICE
# ==========================================

cat > /etc/systemd/system/cloudsec-app.service <<'SERVICE'
[Unit]
Description=Cloud Security Demo Application
After=network.target

[Service]
Type=simple

User=cloudsec
Group=cloudsec

ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0 --directory /opt/cloudsec-app

Restart=on-failure
RestartSec=5

# Process restrictions
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true

# Filesystem protection
ProtectSystem=strict
ProtectHome=true

# Kernel and system protection
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectHostname=true
ProtectClock=true

# Privilege restrictions
RestrictSUIDSGID=true
CapabilityBoundingSet=
AmbientCapabilities=

# Execution restrictions
LockPersonality=true
RestrictRealtime=true
RestrictAddressFamilies=AF_INET AF_INET6

UMask=0027

[Install]
WantedBy=multi-user.target
SERVICE


# ==========================================
# ENABLE AND START APPLICATION
# ==========================================

systemctl daemon-reload
systemctl enable --now cloudsec-app.service
