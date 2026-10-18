/*
 * NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
 * Example 01: Hardware Smoke Test & Telemetry Probe
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/utsname.h>

#if defined(__has_include)
#if __has_include(<linux/fb.h>)
#include <linux/fb.h>
#define HAS_LINUX_FB 1
#endif
#endif

#ifndef HAS_LINUX_FB
/* Fallback definitions for host static analysis & indexing on non-Linux platforms */
struct fb_var_screeninfo {
    unsigned int xres;
    unsigned int yres;
    unsigned int xres_virtual;
    unsigned int yres_virtual;
    unsigned int bits_per_pixel;
};
struct fb_fix_screeninfo {
    unsigned int smem_len;
    unsigned int line_length;
};
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602
#endif

void print_banner(void) {
    printf("============================================================\n");
    printf(" NetEase Youdao Dictionary Pen S7 Pro (CV1813) Hardware Probe\n");
    printf("============================================================\n\n");
}

void probe_system(void) {
    struct utsname uts;
    if (uname(&uts) == 0) {
        printf("[+] System Kernel:  %s %s (%s)\n", uts.sysname, uts.release, uts.machine);
        printf("[+] Hostname:       %s\n", uts.nodename);
    }
}

void probe_cpu(void) {
    FILE *fp = fopen("/proc/cpuinfo", "r");
    if (!fp) return;

    char line[256];
    char model[128] = "Unknown";
    char features[256] = "None";

    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "model name", 10) == 0) {
            char *colon = strchr(line, ':');
            if (colon) {
                strncpy(model, colon + 2, sizeof(model) - 1);
                model[strcspn(model, "\r\n")] = '\0';
            }
        } else if (strncmp(line, "Features", 8) == 0) {
            char *colon = strchr(line, ':');
            if (colon) {
                strncpy(features, colon + 2, sizeof(features) - 1);
                features[strcspn(features, "\r\n")] = '\0';
            }
        }
    }
    fclose(fp);

    printf("[+] CPU Model:      %s\n", model);
    printf("[+] CPU Features:   %s\n", features);
}

void probe_battery(void) {
    FILE *fp;
    char status[32] = "Unknown";
    int capacity = -1;
    int voltage = -1;

    fp = fopen("/sys/class/power_supply/battery/status", "r");
    if (fp) {
        if (fgets(status, sizeof(status), fp)) status[strcspn(status, "\r\n")] = '\0';
        fclose(fp);
    }

    fp = fopen("/sys/class/power_supply/battery/capacity", "r");
    if (fp) {
        fscanf(fp, "%d", &capacity);
        fclose(fp);
    }

    fp = fopen("/sys/class/power_supply/battery/voltage_now", "r");
    if (fp) {
        fscanf(fp, "%d", &voltage);
        fclose(fp);
    }

    printf("[+] Battery Status: %s | Level: %d%% | Voltage: %.2f V\n",
           status, capacity, (double)voltage / 1000000.0);
}

void probe_framebuffer(void) {
    int fb_fd = open("/dev/fb0", O_RDWR);
    if (fb_fd < 0) {
        printf("[-] Framebuffer:    Unable to open /dev/fb0\n");
        return;
    }

    struct fb_var_screeninfo vinfo;
    struct fb_fix_screeninfo finfo;

    if (ioctl(fb_fd, FBIOGET_VSCREENINFO, &vinfo) == 0 &&
        ioctl(fb_fd, FBIOGET_FSCREENINFO, &finfo) == 0) {
        printf("[+] Framebuffer:    %d x %d (virtual: %d x %d), %d bpp\n",
               vinfo.xres, vinfo.yres, vinfo.xres_virtual, vinfo.yres_virtual, vinfo.bits_per_pixel);
        printf("[+] Video Memory:   %u KB (line length: %u bytes)\n",
               finfo.smem_len / 1024, finfo.line_length);
    } else {
        printf("[-] Framebuffer:    ioctl failed\n");
    }

    close(fb_fd);
}

int main(void) {
    print_banner();
    probe_system();
    probe_cpu();
    probe_battery();
    probe_framebuffer();

    printf("\n[+] Hardware probe completed successfully.\n");
    return 0;
}
