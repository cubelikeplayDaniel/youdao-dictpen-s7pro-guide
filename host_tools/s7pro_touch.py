#!/usr/bin/env python3
"""
NetEase Youdao Dictionary Pen S7 Pro - Native Evdev Injection Tool
Platform: Sophgo CV1813H ARM Cortex-A7 (Linux 5.10)
Device Input Node: /dev/input/event3 (axs_ts touchscreen)
"""

import sys
import time
import struct
import os
import argparse
import subprocess

# Linux Evdev Constants
EV_SYN = 0x0000
EV_KEY = 0x0001
EV_ABS = 0x0003

SYN_REPORT = 0x0000
BTN_TOUCH = 0x014a        # 330
BTN_TOOL_FINGER = 0x0145  # 325

ABS_X = 0x0000
ABS_Y = 0x0001
ABS_MT_SLOT = 0x002f        # 47
ABS_MT_TOUCH_MAJOR = 0x0030 # 48
ABS_MT_POSITION_X = 0x0035  # 53
ABS_MT_POSITION_Y = 0x0036  # 54
ABS_MT_TRACKING_ID = 0x0039 # 57
ABS_MT_PRESSURE = 0x003a    # 58

# Canvas Dimensions
CANVAS_WIDTH = 1020
CANVAS_HEIGHT = 240
RAW_MAX_X = 239
RAW_MAX_Y = 1019

def pack_event(ev_type: int, ev_code: int, ev_value: int) -> bytes:
    """Pack Linux input_event (strictly 16 bytes on 32-bit ARM Linux)."""
    now = time.time()
    tv_sec = int(now)
    tv_usec = int((now - tv_sec) * 1_000_000)
    return struct.pack("IIHHi", tv_sec, tv_usec, ev_type, ev_code, ev_value)

def logical_to_raw(log_x: int, log_y: int) -> tuple:
    """
    Apply inverse 270-degree rotation matching greenui::winInputLoop (0x227bcc):
      log_x = clamp(1019 - raw_y, 0, 1019)  ==> raw_y = 1019 - log_x
      log_y = clamp(raw_x, 0, 239)          ==> raw_x = log_y
    """
    raw_x = max(0, min(RAW_MAX_X, int(log_y)))
    raw_y = max(0, min(RAW_MAX_Y, int(1019 - log_x)))
    return raw_x, raw_y

class EvdevInjector:
    def __init__(self, dev_path="/dev/input/event3", ssh_host=None):
        self.dev_path = dev_path
        self.ssh_host = ssh_host
        self.proc = None
        self.fd = None

    def open(self):
        if self.ssh_host:
            cmd = ["ssh", "-i", os.path.expanduser("~/.ssh/id_ed25519"), "-o", "StrictHostKeyChecking=no", f"root@{self.ssh_host}", f"cat > {self.dev_path}"]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        else:
            self.fd = os.open(self.dev_path, os.O_WRONLY)

    def write_events(self, packet_list):
        for packet, delay_sec in packet_list:
            if self.ssh_host:
                self.proc.stdin.write(packet)
                self.proc.stdin.flush()
            else:
                os.write(self.fd, packet)
            if delay_sec > 0:
                time.sleep(delay_sec)

    def close(self):
        if self.ssh_host and self.proc:
            self.proc.stdin.close()
            self.proc.wait()
        elif self.fd is not None:
            os.close(self.fd)

    def send_tap(self, log_x: int, log_y: int, duration_ms: int = 80):
        raw_x, raw_y = logical_to_raw(log_x, log_y)
        print(f"[*] Dispatching Tap: Logical({log_x}, {log_y}) -> Raw({raw_x}, {raw_y}), Hold={duration_ms}ms")

        # Down Sequence (pre-nudge position by 1px so Linux kernel input_handle_abs_event never drops repeated coordinates)
        nudge_x = raw_x - 1 if raw_x > 0 else raw_x + 1
        nudge_y = raw_y - 1 if raw_y > 0 else raw_y + 1
        events_down = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, int(time.time() * 1000) & 0x7fff), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, nudge_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, nudge_y), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, raw_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, raw_y), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 100), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 12), 0),
            (pack_event(EV_ABS, ABS_X, nudge_x), 0),
            (pack_event(EV_ABS, ABS_Y, nudge_y), 0),
            (pack_event(EV_ABS, ABS_X, raw_x), 0),
            (pack_event(EV_ABS, ABS_Y, raw_y), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 1), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), duration_ms / 1000.0)
        ]
        self.write_events(events_down)

        # Up Sequence (must reset ABS_MT_PRESSURE and ABS_MT_TOUCH_MAJOR to 0 so kernel does not filter next touch!)
        events_up = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 0), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), 0.02)
        ]
        self.write_events(events_up)

    def send_swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 250, steps: int = 20):
        s_raw_x, s_raw_y = logical_to_raw(sx, sy)
        e_raw_x, e_raw_y = logical_to_raw(ex, ey)
        step_delay = (duration_ms / 1000.0) / steps
        print(f"[*] Dispatching Swipe: Logical({sx},{sy})->({ex},{ey}) | Raw({s_raw_x},{s_raw_y})->({e_raw_x},{e_raw_y})")

        # Down
        nudge_x = s_raw_x - 1 if s_raw_x > 0 else s_raw_x + 1
        nudge_y = s_raw_y - 1 if s_raw_y > 0 else s_raw_y + 1
        events_down = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, int(time.time() * 1000) & 0x7fff), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, nudge_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, nudge_y), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, s_raw_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, s_raw_y), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 120), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 14), 0),
            (pack_event(EV_ABS, ABS_X, nudge_x), 0),
            (pack_event(EV_ABS, ABS_Y, nudge_y), 0),
            (pack_event(EV_ABS, ABS_X, s_raw_x), 0),
            (pack_event(EV_ABS, ABS_Y, s_raw_y), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 1), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), step_delay)
        ]
        self.write_events(events_down)

        # Move steps
        for i in range(1, steps + 1):
            cur_raw_x = int(s_raw_x + (e_raw_x - s_raw_x) * (i / steps))
            cur_raw_y = int(s_raw_y + (e_raw_y - s_raw_y) * (i / steps))
            events_move = [
                (pack_event(EV_ABS, ABS_MT_POSITION_X, cur_raw_x), 0),
                (pack_event(EV_ABS, ABS_MT_POSITION_Y, cur_raw_y), 0),
                (pack_event(EV_ABS, ABS_X, cur_raw_x), 0),
                (pack_event(EV_ABS, ABS_Y, cur_raw_y), 0),
                (pack_event(EV_SYN, SYN_REPORT, 0), step_delay)
            ]
            self.write_events(events_move)

        # Up
        events_up = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 0), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), 0.02)
        ]
        self.write_events(events_up)

def main():
    parser = argparse.ArgumentParser(description="S7 Pro Evdev Touch Injection Tool")
    parser.add_argument("--ssh", type=str, default="192.168.2.2", help="Pen SSH IP (default: 192.168.2.2)")
    parser.add_argument("--dev", type=str, default="/dev/input/event3", help="Evdev node")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    tap_p = subparsers.add_parser("tap")
    tap_p.add_argument("x", type=int, help="Logical X (0..1019)")
    tap_p.add_argument("y", type=int, help="Logical Y (0..239)")
    tap_p.add_argument("--duration", type=int, default=80, help="Press duration in ms")

    sw_p = subparsers.add_parser("swipe")
    sw_p.add_argument("sx", type=int)
    sw_p.add_argument("sy", type=int)
    sw_p.add_argument("ex", type=int)
    sw_p.add_argument("ey", type=int)
    sw_p.add_argument("--duration", type=int, default=250)
    sw_p.add_argument("--steps", type=int, default=20)

    dt_p = subparsers.add_parser("doubletap")
    dt_p.add_argument("x", type=int, help="Logical X (0..1019)")
    dt_p.add_argument("y", type=int, help="Logical Y (0..239)")
    dt_p.add_argument("--interval", type=int, default=120, help="Interval between taps in ms")

    args = parser.parse_args()
    injector = EvdevInjector(dev_path=args.dev, ssh_host=args.ssh)
    injector.open()

    try:
        if args.cmd == "tap":
            injector.send_tap(args.x, args.y, args.duration)
        elif args.cmd == "swipe":
            injector.send_swipe(args.sx, args.sy, args.ex, args.ey, args.duration, args.steps)
        elif args.cmd == "doubletap":
            injector.send_tap(args.x, args.y, duration_ms=60)
            time.sleep(args.interval / 1000.0)
            injector.send_tap(args.x, args.y, duration_ms=60)
    finally:
        injector.close()

if __name__ == "__main__":
    main()
