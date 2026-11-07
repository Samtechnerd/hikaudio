// voice_live: live two-way voice with a Hikvision door station via HCNetSDK.
//   stdin : G.711 u-law 8 kHz mono audio to play on the door speaker (any chunk size)
//   stdout: G.711 u-law 8 kHz mono audio from the door microphone (160-byte frames)
// Credentials come from the environment: HIK_HOST, HIK_USER, HIK_PASS, optional HIK_PORT.
// usage: voice_live [voice_channel=1]. Ends on SIGTERM/SIGINT or when stdin closes.
// Door-station audio is sent in lockstep with the device's mic frames (the only mode that is audible).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include "HCNetSDK.h"

#define RING 16000  // 2 s of audio at 8 kHz; oldest audio is dropped on overflow
static unsigned char g_ring[RING];
static long g_rd = 0, g_wr = 0;  // monotonically increasing
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static volatile int g_stop = 0, g_eof = 0;

static void on_sig(int s) { (void)s; g_stop = 1; }

static void *reader(void *a) {
    (void)a;
    unsigned char b[320];
    for (;;) {
        ssize_t n = read(0, b, sizeof(b));
        if (n <= 0) { g_eof = 1; break; }
        pthread_mutex_lock(&g_mu);
        for (ssize_t i = 0; i < n; i++) g_ring[(g_wr++) % RING] = b[i];
        if (g_wr - g_rd > RING) g_rd = g_wr - RING;
        pthread_mutex_unlock(&g_mu);
    }
    return NULL;
}

static void CALLBACK onVoice(LONG h, char *buf, DWORD size, BYTE flag, void *user) {
    (void)user;
    if (flag != 1) return;  // 1 = frame from the door station mic
    fwrite(buf, 1, size, stdout);
    fflush(stdout);
    unsigned char out[160];
    memset(out, 0xFF, sizeof(out));  // u-law silence when nothing is queued
    pthread_mutex_lock(&g_mu);
    long avail = g_wr - g_rd;
    long n = avail < 160 ? avail : 160;
    for (long i = 0; i < n; i++) out[i] = g_ring[(g_rd + i) % RING];
    g_rd += n;
    pthread_mutex_unlock(&g_mu);
    NET_DVR_VoiceComSendData(h, (char *)out, 160);
}

int main(int argc, char **argv) {
    const char *host = getenv("HIK_HOST"), *user = getenv("HIK_USER"), *pass = getenv("HIK_PASS");
    const char *port = getenv("HIK_PORT");
    if (!host || !user || !pass) { fprintf(stderr, "HIK_HOST/HIK_USER/HIK_PASS not set\n"); return 2; }
    int chan = argc > 1 ? atoi(argv[1]) : 1;
    signal(SIGTERM, on_sig); signal(SIGINT, on_sig); signal(SIGPIPE, SIG_IGN);

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
    fprintf(stderr, "login ok\n");
    LONG h = NET_DVR_StartVoiceCom_MR_V30(uid, chan, onVoice, NULL);
    if (h < 0) {
        fprintf(stderr, "StartVoiceCom_MR_V30 failed (channel %d), error %u\n", chan, NET_DVR_GetLastError());
        NET_DVR_Logout(uid); NET_DVR_Cleanup(); return 1;
    }
    fprintf(stderr, "talk session open on channel %d\n", chan);
    pthread_t t; pthread_create(&t, NULL, reader, NULL); pthread_detach(t);
    while (!g_stop) {
        if (g_eof) {  // stdin closed: let queued audio drain, then finish
            pthread_mutex_lock(&g_mu); long left = g_wr - g_rd; pthread_mutex_unlock(&g_mu);
            if (left <= 0) break;
        }
        usleep(20000);
    }
    sleep(1);
    fprintf(stderr, "stopping\n");
    NET_DVR_StopVoiceCom(h);
    fprintf(stderr, "stopped\n");
    NET_DVR_Logout(uid);
    fprintf(stderr, "logged out\n");
    NET_DVR_Cleanup();
    fprintf(stderr, "done\n");
    return 0;
}
