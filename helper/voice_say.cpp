// voice_say: play a raw G.711 u-law (or a-law) 8 kHz mono file to a Hikvision door station
// via HCNetSDK voice talk. Credentials come from the environment, never argv.
//   HIK_HOST, HIK_USER, HIK_PASS (and optional HIK_PORT, default 8000)
//   HIK_MODE: normal (default, 80B/10ms after 0.5s) | fast160 (160B/20ms, no pre-delay) | lockstep (send inside callback)
//   HIK_CAPTURE: write the gate's mic audio to this file
// usage: voice_say <file.ulaw> [voice_channel=1] [chunk=80] [tail_seconds=1]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "HCNetSDK.h"

static volatile long g_cb_dev = 0, g_cb_local = 0, g_cb_bytes = 0;
static FILE *g_cap = NULL;
static char *g_audio = NULL;
static long g_len = 0;
static volatile long g_off = 0;
static int g_lockstep = 0;
static volatile LONG g_h = -1;

static void CALLBACK onVoice(LONG h, char *buf, DWORD size, BYTE flag, void *user) {
    (void)user;
    g_cb_bytes += size;
    if (g_cap && flag == 1) fwrite(buf, 1, size, g_cap);
    if (flag == 1) g_cb_dev++; else g_cb_local++;
    if (g_lockstep && flag == 1 && g_off < g_len) {
        long n = (g_len - g_off) < 160 ? (g_len - g_off) : 160;
        NET_DVR_VoiceComSendData(h, g_audio + g_off, (DWORD)n);
        g_off += n;
    }
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: voice_say <file.ulaw> [channel] [chunk] [tail]\n"); return 2; }
    const char *host = getenv("HIK_HOST"), *user = getenv("HIK_USER"), *pass = getenv("HIK_PASS");
    const char *port = getenv("HIK_PORT"), *mode = getenv("HIK_MODE");
    if (!host || !user || !pass) { fprintf(stderr, "HIK_HOST/HIK_USER/HIK_PASS not set\n"); return 2; }
    int chan = argc > 2 ? atoi(argv[2]) : 1;
    int chunk = argc > 3 ? atoi(argv[3]) : 80;
    int tail = argc > 4 ? atoi(argv[4]) : 1;
    if (chunk < 40 || chunk > 1024) chunk = 80;
    int fast = mode && !strcmp(mode, "fast160");
    g_lockstep = mode ? !strcmp(mode, "lockstep") : 1;
    if (fast) chunk = 160;

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open audio"); return 2; }
    fseek(f, 0, SEEK_END); g_len = ftell(f); fseek(f, 0, SEEK_SET);
    g_audio = (char *)malloc(g_len);
    if (fread(g_audio, 1, g_len, f) != (size_t)g_len) { perror("read audio"); return 2; }
    fclose(f);
    if (getenv("HIK_CAPTURE")) g_cap = fopen(getenv("HIK_CAPTURE"), "wb");

    NET_DVR_Init();
    NET_DVR_SetConnectTime(3000, 2);
    NET_DVR_SetLogToFile(3, (char *)"/tmp/sdklog", 1);
    NET_DVR_USER_LOGIN_INFO li; memset(&li, 0, sizeof(li));
    NET_DVR_DEVICEINFO_V40 di; memset(&di, 0, sizeof(di));
    li.bUseAsynLogin = 0;
    li.wPort = port ? atoi(port) : 8000;
    strncpy(li.sDeviceAddress, host, NET_DVR_DEV_ADDRESS_MAX_LEN - 1);
    strncpy(li.sUserName, user, NAME_LEN - 1);
    strncpy(li.sPassword, pass, NAME_LEN - 1);
    LONG uid = NET_DVR_Login_V40(&li, &di);
    if (uid < 0) { fprintf(stderr, "login failed, error %u\n", NET_DVR_GetLastError()); NET_DVR_Cleanup(); return 1; }
    fprintf(stderr, "login ok mode=%s\n", mode ? mode : "normal");

    LONG h = NET_DVR_StartVoiceCom_MR_V30(uid, chan, onVoice, NULL);
    if (h < 0) {
        fprintf(stderr, "StartVoiceCom_MR_V30 failed (channel %d), error %u\n", chan, NET_DVR_GetLastError());
        NET_DVR_Logout(uid); NET_DVR_Cleanup(); return 1;
    }
    g_h = h;
    fprintf(stderr, "talk session open on channel %d, %ld bytes (%.1f s)\n", chan, g_len, g_len / 8000.0);
    long sent_ok = 0, sent_fail = 0;
    if (g_lockstep) {
        for (int i = 0; i < (int)(g_len / 8000.0 * 20) + 100 && g_off < g_len; i++) usleep(50000);
        sleep(2);
    } else {
        if (!fast) usleep(500000);
        for (long off = 0; off < g_len; off += chunk) {
            DWORD n = (g_len - off) < chunk ? (DWORD)(g_len - off) : (DWORD)chunk;
            if (NET_DVR_VoiceComSendData(h, g_audio + off, n)) sent_ok++;
            else { sent_fail++; if (sent_fail == 1) fprintf(stderr, "send failed at %ld, error %u\n", off, NET_DVR_GetLastError()); }
            usleep((useconds_t)(n * 125));
        }
    }
    sleep(tail);
    fprintf(stderr, "sent ok=%ld fail=%ld lockstep_off=%ld; callbacks from device=%ld bytes=%ld\n", sent_ok, sent_fail, g_off, g_cb_dev, g_cb_bytes);
    if (g_cap) fclose(g_cap);
    NET_DVR_StopVoiceCom(h);
    NET_DVR_Logout(uid);
    NET_DVR_Cleanup();
    fprintf(stderr, "done\n");
    return 0;
}
