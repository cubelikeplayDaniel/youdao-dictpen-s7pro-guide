/**
 * NetEase Youdao Dictionary Pen S7 Pro - Native C Touch Injector
 * Architecture: ARMv7-A (32-bit Little-Endian)
 * Device Node: /dev/input/event3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <linux/input.h>

#define DEV_PATH "/dev/input/event3"

#define CANVAS_WIDTH  1020
#define CANVAS_HEIGHT 240
#define RAW_MAX_X     239
#define RAW_MAX_Y     1019

/* Coordinate mapping matching greenui::winInputLoop (0x227bcc) */
static void logical_to_raw(int log_x, int log_y, int *raw_x, int *raw_y) {
    if (log_x < 0) log_x = 0;
    if (log_x > 1019) log_x = 1019;
    if (log_y < 0) log_y = 0;
    if (log_y > 239) log_y = 239;

    *raw_x = log_y;
    *raw_y = 1019 - log_x;
}

static void emit_event(int fd, uint16_t type, uint16_t code, int32_t value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ev.time.tv_sec = ts.tv_sec;
    ev.time.tv_usec = ts.tv_nsec / 1000;
    ev.type = type;
    ev.code = code;
    ev.value = value;

    if (write(fd, &ev, sizeof(ev)) < (ssize_t)sizeof(ev)) {
        perror("write input_event error");
    }
}

static void send_tap(int fd, int log_x, int log_y, int duration_ms) {
    int raw_x, raw_y;
    logical_to_raw(log_x, log_y, &raw_x, &raw_y);
    printf("[s7pro_touch] TAP at logical (%d, %d) -> raw (%d, %d), hold %d ms\n",
           log_x, log_y, raw_x, raw_y, duration_ms);

    // ACTION_DOWN
    emit_event(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, 1001);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_X, raw_x);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, raw_y);
    emit_event(fd, EV_ABS, ABS_MT_PRESSURE, 100);
    emit_event(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 12);
    emit_event(fd, EV_ABS, ABS_X, raw_x);
    emit_event(fd, EV_ABS, ABS_Y, raw_y);
    emit_event(fd, EV_KEY, BTN_TOUCH, 1);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 1);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);

    usleep(duration_ms * 1000);

    // ACTION_UP
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit_event(fd, EV_KEY, BTN_TOUCH, 0);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 0);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void send_swipe(int fd, int sx, int sy, int ex, int ey, int duration_ms, int steps) {
    int s_raw_x, s_raw_y, e_raw_x, e_raw_y;
    logical_to_raw(sx, sy, &s_raw_x, &s_raw_y);
    logical_to_raw(ex, ey, &e_raw_x, &e_raw_y);

    int step_delay_us = (duration_ms * 1000) / steps;
    printf("[s7pro_touch] SWIPE logical (%d,%d)->(%d,%d) | raw (%d,%d)->(%d,%d), steps=%d\n",
           sx, sy, ex, ey, s_raw_x, s_raw_y, e_raw_x, e_raw_y, steps);

    // Down
    emit_event(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, 1002);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_X, s_raw_x);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, s_raw_y);
    emit_event(fd, EV_ABS, ABS_MT_PRESSURE, 120);
    emit_event(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 15);
    emit_event(fd, EV_ABS, ABS_X, s_raw_x);
    emit_event(fd, EV_ABS, ABS_Y, s_raw_y);
    emit_event(fd, EV_KEY, BTN_TOUCH, 1);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 1);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
    usleep(step_delay_us);

    // Steps
    for (int i = 1; i <= steps; i++) {
        float r = (float)i / (float)steps;
        int cur_x = s_raw_x + (int)((e_raw_x - s_raw_x) * r);
        int cur_y = s_raw_y + (int)((e_raw_y - s_raw_y) * r);

        emit_event(fd, EV_ABS, ABS_MT_POSITION_X, cur_x);
        emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, cur_y);
        emit_event(fd, EV_ABS, ABS_X, cur_x);
        emit_event(fd, EV_ABS, ABS_Y, cur_y);
        emit_event(fd, EV_SYN, SYN_REPORT, 0);
        usleep(step_delay_us);
    }

    // Up
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit_event(fd, EV_KEY, BTN_TOUCH, 0);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 0);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s tap <log_x> <log_y> [duration_ms]\n", argv[0]);
        fprintf(stderr, "  %s swipe <sx> <sy> <ex> <ey> [duration_ms] [steps]\n", argv[0]);
        return 1;
    }

    int fd = open(DEV_PATH, O_WRONLY);
    if (fd < 0) {
        perror("Failed to open " DEV_PATH);
        return 1;
    }

    if (strcmp(argv[1], "tap") == 0 && argc >= 4) {
        int x = atoi(argv[2]);
        int y = atoi(argv[3]);
        int dur = (argc > 4) ? atoi(argv[4]) : 80;
        send_tap(fd, x, y, dur);
    } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        int sx = atoi(argv[2]);
        int sy = atoi(argv[3]);
        int ex = atoi(argv[4]);
        int ey = atoi(argv[5]);
        int dur = (argc > 6) ? atoi(argv[6]) : 250;
        int steps = (argc > 7) ? atoi(argv[7]) : 20;
        send_swipe(fd, sx, sy, ex, ey, dur, steps);
    } else {
        fprintf(stderr, "Unknown or invalid command arguments.\n");
        close(fd);
        return 1;
    }

    close(fd);
    printf("[+] Event injected successfully.\n");
    return 0;
}
