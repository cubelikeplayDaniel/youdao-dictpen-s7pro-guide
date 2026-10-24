#!/usr/bin/env python3
import sys
import time
import struct
import subprocess

# Linux input event types
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3

SYN_REPORT = 0
BTN_TOUCH = 330
BTN_TOOL_FINGER = 325

ABS_X = 0
ABS_Y = 1
ABS_MT_SLOT = 47
ABS_MT_TOUCH_MAJOR = 48
ABS_MT_POSITION_X = 53
ABS_MT_POSITION_Y = 54
ABS_MT_TRACKING_ID = 57
ABS_MT_PRESSURE = 58

def pack_event(ev_type, ev_code, ev_val):
    # 32-bit ARM Linux struct input_event:
    # struct timeval { long tv_sec; long tv_usec; } = 4 + 4 = 8 bytes
    # __u16 type; __u16 code; __s32 value; = 2 + 2 + 4 = 8 bytes
    # Total = strictly 16 bytes: 'IIHHi'
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1000000)
    return struct.pack("IIHHi", sec, usec, ev_type, ev_code, ev_val)

def logical_to_raw(log_x, log_y):
    # 270 degree rotation formula in greenui::winInputLoop (0x227bcc)
    # log_x = 1019 - raw_y  ==> raw_y = 1019 - log_x
    # log_y = raw_x         ==> raw_x = log_y
    raw_x = int(log_y)
    raw_y = int(1019 - log_x)
    return raw_x, raw_y

def create_swipe_events(start_log_x, start_log_y, end_log_x, end_log_y, steps=25, duration=0.25):
    events = []
    start_raw_x, start_raw_y = logical_to_raw(start_log_x, start_log_y)
    end_raw_x, end_raw_y = logical_to_raw(end_log_x, end_log_y)

    # Touch down
    # Slot 0, Tracking ID 1
    events.append((pack_event(EV_ABS, ABS_MT_SLOT, 0), 0))
    events.append((pack_event(EV_ABS, ABS_MT_TRACKING_ID, 1), 0))
    events.append((pack_event(EV_ABS, ABS_MT_POSITION_X, start_raw_x), 0))
    events.append((pack_event(EV_ABS, ABS_MT_POSITION_Y, start_raw_y), 0))
    events.append((pack_event(EV_ABS, ABS_MT_PRESSURE, 120), 0))
    events.append((pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 15), 0))
    events.append((pack_event(EV_ABS, ABS_X, start_raw_x), 0))
    events.append((pack_event(EV_ABS, ABS_Y, start_raw_y), 0))
    events.append((pack_event(EV_KEY, BTN_TOUCH, 1), 0))
    events.append((pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0))
    events.append((pack_event(EV_SYN, SYN_REPORT, 0), duration / steps))

    # Move steps
    for i in range(1, steps + 1):
        ratio = i / float(steps)
        cur_raw_x = int(start_raw_x + (end_raw_x - start_raw_x) * ratio)
        cur_raw_y = int(start_raw_y + (end_raw_y - start_raw_y) * ratio)
        events.append((pack_event(EV_ABS, ABS_MT_POSITION_X, cur_raw_x), 0))
        events.append((pack_event(EV_ABS, ABS_MT_POSITION_Y, cur_raw_y), 0))
        events.append((pack_event(EV_ABS, ABS_X, cur_raw_x), 0))
        events.append((pack_event(EV_ABS, ABS_Y, cur_raw_y), 0))
        events.append((pack_event(EV_SYN, SYN_REPORT, 0), duration / steps))

    # Touch up
    events.append((pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0))
    events.append((pack_event(EV_KEY, BTN_TOUCH, 0), 0))
    events.append((pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0))
    events.append((pack_event(EV_SYN, SYN_REPORT, 0), 0.05))

    return events

def run_swipe_on_device(start_log_x, start_log_y, end_log_x, end_log_y, steps=25, duration=0.25):
    events = create_swipe_events(start_log_x, start_log_y, end_log_x, end_log_y, steps, duration)

    # Open SSH connection with stdin piped directly to /dev/input/event3
    cmd = ["ssh", "-i", "/Users/daniel/.ssh/id_ed25519", "-o", "StrictHostKeyChecking=no", "root@192.168.2.2", "cat > /dev/input/event3"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for ev_bytes, delay in events:
        proc.stdin.write(ev_bytes)
        proc.stdin.flush()
        if delay > 0:
            time.sleep(delay)

    proc.stdin.close()
    proc.wait()
    print(f"Swipe finished: ({start_log_x},{start_log_y}) -> ({end_log_x},{end_log_y})")

def create_tap_events(log_x, log_y, duration=0.08):
    events = []
    raw_x, raw_y = logical_to_raw(log_x, log_y)

    # Touch down
    events.append((pack_event(EV_ABS, ABS_MT_SLOT, 0), 0))
    events.append((pack_event(EV_ABS, ABS_MT_TRACKING_ID, 1), 0))
    events.append((pack_event(EV_ABS, ABS_MT_POSITION_X, raw_x), 0))
    events.append((pack_event(EV_ABS, ABS_MT_POSITION_Y, raw_y), 0))
    events.append((pack_event(EV_ABS, ABS_MT_PRESSURE, 100), 0))
    events.append((pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 12), 0))
    events.append((pack_event(EV_ABS, ABS_X, raw_x), 0))
    events.append((pack_event(EV_ABS, ABS_Y, raw_y), 0))
    events.append((pack_event(EV_KEY, BTN_TOUCH, 1), 0))
    events.append((pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0))
    events.append((pack_event(EV_SYN, SYN_REPORT, 0), duration))

    # Touch up
    events.append((pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0))
    events.append((pack_event(EV_KEY, BTN_TOUCH, 0), 0))
    events.append((pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0))
    events.append((pack_event(EV_SYN, SYN_REPORT, 0), 0.02))

    return events

def run_tap_on_device(log_x, log_y, duration=0.08):
    events = create_tap_events(log_x, log_y, duration)
    cmd = ["ssh", "-i", "/Users/daniel/.ssh/id_ed25519", "-o", "StrictHostKeyChecking=no", "root@192.168.2.2", "cat > /dev/input/event3"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for ev_bytes, delay in events:
        proc.stdin.write(ev_bytes)
        proc.stdin.flush()
        if delay > 0:
            time.sleep(delay)
    proc.stdin.close()
    proc.wait()
    print(f"Tap finished at logical ({log_x}, {log_y}) -> raw {logical_to_raw(log_x, log_y)}")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        x, y = int(sys.argv[1]), int(sys.argv[2])
        run_tap_on_device(x, y)
    elif len(sys.argv) == 5:
        sx, sy, ex, ey = [int(a) for a in sys.argv[1:5]]
        run_swipe_on_device(sx, sy, ex, ey)
    else:
        # Default: swipe up to switch launcher from Page 0 to Page 1
        run_swipe_on_device(510, 200, 510, 30, steps=20, duration=0.2)
