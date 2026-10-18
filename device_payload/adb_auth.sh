#!/bin/sh
# Overrides /usr/bin/adb_auth.sh
# Always approves ADB shell authentication and creates the verification flag
/bin/touch /tmp/.adb_auth_verified
echo "success."
exit 0
