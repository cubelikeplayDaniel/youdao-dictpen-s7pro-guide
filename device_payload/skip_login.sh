#!/bin/sh
# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# Boot Hook & Persistence Script - /userdisk/skip_re/skip_login.sh
# Automatically triggered by /etc/init.d/S99_run_test_scripts on boot (UID 0 root)
# ==============================================================================

# 1. 永久开放 ADB 免密调试鉴权
/bin/touch /tmp/.adb_auth_verified
/bin/chmod 777 /tmp/.adb_auth_verified
echo "verified" > /tmp/.adb_auth_verified

# 2. 覆盖鉴权脚本与密码表 (实现 root 密码永久为 root，ADB 鉴权永久直通)
[ -f /userdata/bin/adb_auth.sh ] && mount --bind /userdata/bin/adb_auth.sh /usr/bin/adb_auth.sh
[ -f /userdata/etc/shadow ] && mount --bind /userdata/etc/shadow /etc/shadow

# 3. 记录开机执行信息
LOGFILE=/userdisk/skip_re/run.log
{
    echo "=== S7 Pro Boot Hook Started at $(date) ==="
    id
    uname -a
    ifconfig wlan0 2>/dev/null | grep 'inet '
} > "$LOGFILE" 2>&1

# 4. 自动启动 OpenSSH 服务 (监听 0.0.0.0:22)
if [ -x /usr/bin/sshd_service ]; then
    mkdir -p /var/lock /var/empty
    /usr/bin/sshd_service start >> "$LOGFILE" 2>&1
elif [ -x /usr/bin/dropbear_service ]; then
    /usr/bin/dropbear_service start >> "$LOGFILE" 2>&1
fi

# 5. 后台守护线程：持续维护免密标志文件
while true; do
    /bin/touch /tmp/.adb_auth_verified
    sleep 3
done &
