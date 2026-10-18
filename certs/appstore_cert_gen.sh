#!/bin/bash
# ==============================================================================
# Generate Self-Signed Multi-Domain SAN Certificate for Youdao AppStore / CDN
# ==============================================================================

set -e

KEY_FILE="appstore.key"
CRT_FILE="appstore.crt"
CONF_FILE="san.cnf"

cat << 'EOF' > "$CONF_FILE"
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = CN
ST = Zhejiang
L = Hangzhou
O = NetEase
OU = Youdao
CN = dictpen-appstore.youdao.com

[v3_req]
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = dictpen-appstore.youdao.com
DNS.2 = hardware-iot.youdao.com
DNS.3 = hardware-app.youdao.com
DNS.4 = hardware-push-server.youdao.com
DNS.5 = dict.youdao.com
DNS.6 = rlogs.youdao.com
DNS.7 = ydhardwarecommon.nosdn.127.net
DNS.8 = *.nosdn.127.net
DNS.9 = *.youdao.com
IP.1 = 192.168.2.1
EOF

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "$KEY_FILE" \
  -out "$CRT_FILE" \
  -config "$CONF_FILE"

rm -f "$CONF_FILE"
echo "Generated $KEY_FILE and $CRT_FILE with extended SANs successfully."
