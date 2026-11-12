// Copyright © 2026 Truls Aagedal
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Native client for aagedal-scopes protocol 2: signal, lifecycle and timing.
// Usage: INPUT OUTPUT_PREFIX HWDEC WIDTH [play]
// Build as Objective-C with -DSCOPE_GPU for gpu-next on a CAMetalLayer;
// otherwise vo=null exercises the CPU backend only.
// Writes OUTPUT_PREFIX-<backend>-<plot>.bgra for each backend that works and
// prints one JSON object.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <sys/resource.h>
#include "mpv/client.h"
#ifdef SCOPE_GPU
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
static NSWindow *window;
static CAMetalLayer *layer;
static void configure(mpv_handle *m) {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    [NSApp finishLaunching];
    window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,640,360)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    layer = [CAMetalLayer layer]; layer.device = MTLCreateSystemDefaultDevice();
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    layer.frame = CGRectMake(0,0,640,360); layer.drawableSize = CGSizeMake(640,360);
    window.contentView.layer = layer; window.contentView.wantsLayer = YES;
    [window orderBack:nil];
    int64_t wid = (int64_t)(__bridge void *)layer;
    mpv_set_option(m,"wid",MPV_FORMAT_INT64,&wid);
    mpv_set_option_string(m,"vo","gpu-next");
    mpv_set_option_string(m,"gpu-api","vulkan");
    mpv_set_option_string(m,"gpu-context","moltenvk");
}
static void pump(void) {
    @autoreleasepool {
        NSEvent *e;
        while ((e = [NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate date]
                     inMode:NSDefaultRunLoopMode dequeue:YES])) [NSApp sendEvent:e];
        [NSApp updateWindows];
    }
}
#else
static void configure(mpv_handle *m) { mpv_set_option_string(m,"vo","null"); }
static void pump(void) {}
#endif

static const char *const plots[] = {"waveform", "parade", "vectorscope"};

// Process CPU time (all threads), seconds.
static double cpu_time(void) {
    struct rusage u; getrusage(RUSAGE_SELF, &u);
    return u.ru_utime.tv_sec + u.ru_utime.tv_usec / 1e6 +
           u.ru_stime.tv_sec + u.ru_stime.tv_usec / 1e6;
}
static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void check(int r) {
    if (r < 0) { fprintf(stderr, "%s\n", mpv_error_string(r)); exit(2); }
}
static mpv_node *find(mpv_node *n, const char *key) {
    if (n->format != MPV_FORMAT_NODE_MAP) return NULL;
    for (int i = 0; i < n->u.list->num; i++)
        if (!strcmp(n->u.list->keys[i], key)) return &n->u.list->values[i];
    return NULL;
}
static mpv_node *field(mpv_node *n, const char *key, mpv_format format) {
    mpv_node *f = find(n, key);
    if (!f || f->format != format) { fprintf(stderr, "bad field %s\n", key); exit(3); }
    return f;
}
static int capture(mpv_handle *m, mpv_node *result, const char *width,
                   const char *which, const char *backend) {
    // SCOPE_ANALYSIS overrides the analysis raster's longest edge.
    const char *analysis = getenv("SCOPE_ANALYSIS");
    const char *args[] = {"aagedal-scopes", width, which, backend,
                          analysis ? analysis : "0", NULL};
    return mpv_command_ret(m, args, result);
}
// Checks payload shapes and metadata; returns 0 or an exit code.
static int validate(mpv_node *n, int want_plots) {
    if (field(n, "protocol", MPV_FORMAT_INT64)->u.int64 != 2) return 20;
    int64_t w = field(n, "w", MPV_FORMAT_INT64)->u.int64;
    int64_t h = field(n, "h", MPV_FORMAT_INT64)->u.int64;
    if (h != llround(w * 9.0 / 16)) return 21;
    double pts = field(n, "pts", MPV_FORMAT_DOUBLE)->u.double_;
    if (!isfinite(pts)) return 22;
    field(n, "primaries", MPV_FORMAT_STRING);
    field(n, "transfer", MPV_FORMAT_STRING);
    field(n, "analysis-w", MPV_FORMAT_INT64);
    field(n, "analysis-h", MPV_FORMAT_INT64);
    for (int i = 0; i < 3; i++) {
        mpv_node *f = find(n, plots[i]);
        if (!(want_plots & (1 << i))) { if (f) return 23; continue; }
        if (!f || f->format != MPV_FORMAT_BYTE_ARRAY) return 24;
        if (f->u.ba->size != (size_t)((i == 2 ? h : w) * h * 4)) return 25;
    }
    return 0;
}
static void write_plots(mpv_node *n, const char *prefix, const char *backend) {
    for (int i = 0; i < 3; i++) {
        mpv_byte_array *ba = field(n, plots[i], MPV_FORMAT_BYTE_ARRAY)->u.ba;
        char path[4096];
        snprintf(path, sizeof(path), "%s-%s-%s.bgra", prefix, backend, plots[i]);
        FILE *file = fopen(path, "wb");
        if (!file || fwrite(ba->data, 1, ba->size, file) != ba->size) exit(7);
        fclose(file);
    }
}
// Mean wall-clock milliseconds of n captures; *cpu_ms gets the mean process
// CPU time (meaningful while paused, when nothing else runs).
static double time_captures(mpv_handle *m, const char *width, const char *which,
                            const char *backend, int n, int play, double *first,
                            double *last, double *cpu_ms) {
    mpv_node r;
    double total = 0, cpu_start = cpu_time();
    for (int i = 0; i < n; i++) {
        pump();
        double start = now();
        check(capture(m, &r, width, which, backend));
        total += now() - start;
        double pts = field(&r, "pts", MPV_FORMAT_DOUBLE)->u.double_;
        if (first && *first < 0) *first = pts;
        if (last) *last = pts;
        mpv_free_node_contents(&r);
        if (play) mpv_wait_event(m, .01);
    }
    *cpu_ms = (cpu_time() - cpu_start) / n * 1000;
    return total / n * 1000;
}

int main(int argc, char **argv) {
    if (argc < 5) return 1;
    const char *input = argv[1], *prefix = argv[2], *hwdec = argv[3], *width = argv[4];
    int play = argc > 5;
    mpv_handle *m = mpv_create();
    configure(m);
    mpv_set_option_string(m, "ao", "null");
    mpv_set_option_string(m, "hwdec", hwdec);
    mpv_set_option_string(m, "pause", "yes");
    mpv_set_option_string(m, "keep-open", "yes");
    mpv_set_option_string(m, "msg-level", "all=error");
    check(mpv_initialize(m));

    mpv_node n = {0};
    if (capture(m, &n, width, "waveform+parade+vectorscope", "auto") >= 0) return 4;
    const char *load[] = {"loadfile", input, NULL};
    check(mpv_command(m, load));
    int ready = 0;
    for (int i = 0; i < 500 && !ready; i++) {
        pump();
        mpv_wait_event(m, .01);
        ready = capture(m, &n, width, "waveform+parade+vectorscope", "auto") >= 0;
        mpv_free_node_contents(&n);
    }
    if (!ready) return 5;

    printf("{");
    const char *backends[] = {"gpu", "cpu"};
    int have[2] = {0};
    for (int b = 0; b < 2; b++) {
        if (capture(m, &n, width, "waveform+parade+vectorscope", backends[b]) < 0) {
            printf("\"%s\":null,", backends[b]);
            continue;
        }
        int err = validate(&n, 7);
        if (err) return err;
        if (strcmp(field(&n, "backend", MPV_FORMAT_STRING)->u.string, backends[b])) return 26;
        have[b] = 1;
        write_plots(&n, prefix, backends[b]);
        printf("\"%s\":{\"w\":%lld,\"h\":%lld,\"pts\":%.9f,\"primaries\":\"%s\","
               "\"transfer\":\"%s\",\"peak\":%g,\"analysisW\":%lld,\"analysisH\":%lld,"
               "\"dolbyVision\":%d},",
               backends[b], (long long)field(&n, "w", MPV_FORMAT_INT64)->u.int64,
               (long long)field(&n, "h", MPV_FORMAT_INT64)->u.int64,
               field(&n, "pts", MPV_FORMAT_DOUBLE)->u.double_,
               field(&n, "primaries", MPV_FORMAT_STRING)->u.string,
               field(&n, "transfer", MPV_FORMAT_STRING)->u.string,
               field(&n, "peak-nits", MPV_FORMAT_DOUBLE)->u.double_,
               (long long)field(&n, "analysis-w", MPV_FORMAT_INT64)->u.int64,
               (long long)field(&n, "analysis-h", MPV_FORMAT_INT64)->u.int64,
               field(&n, "dolby-vision", MPV_FORMAT_FLAG)->u.flag);
        mpv_free_node_contents(&n);
    }
#ifdef SCOPE_GPU
    if (!have[0]) return 27;
#endif
    if (!have[1] && !have[0]) return 28;

    // A single requested plot comes back alone; no plot list means all three.
    check(capture(m, &n, width, "vectorscope", "auto"));
    int err = validate(&n, 4);
    if (err) return err;
    mpv_free_node_contents(&n);
    const char *all[] = {"aagedal-scopes", width, NULL};
    check(mpv_command_ret(m, all, &n));
    if ((err = validate(&n, 7))) return err;
    mpv_free_node_contents(&n);

    const char *bad[] = {"aagedal-scopes", "2000000000", NULL};
    if (mpv_command_ret(m, bad, &n) >= 0) return 9;
    mpv_free_node_contents(&n);

    if (play) check(mpv_set_property_string(m, "pause", "no"));
    int iters = 30;
    double first = -1, last = -1;
    printf("\"timingMS\":{");
    for (int b = 0; b < 2; b++) {
        if (!have[b]) continue;
        double cpu;
        // Warm up shader compilation for each plot combination first.
        time_captures(m, width, "waveform", backends[b], 1, 0, NULL, NULL, &cpu);
        printf("\"%s\":%.4f,", backends[b],
               time_captures(m, width, "waveform+parade+vectorscope", backends[b],
                             iters, play, b == 0 || !have[0] ? &first : NULL, &last, &cpu));
        printf("\"%sCPU\":%.4f,", backends[b], cpu);
        printf("\"%sWaveformOnly\":%.4f,", backends[b],
               time_captures(m, width, "waveform", backends[b], iters, play, NULL, NULL, &cpu));
    }
    double shot = 0;
    for (int i = 0; i < iters; i++) {
        pump();
        const char *cmd[] = {"screenshot-raw", "video", NULL};
        double start = now();
        check(mpv_command_ret(m, cmd, &n));
        shot += now() - start;
        mpv_free_node_contents(&n);
    }
    printf("\"screenshotOnly\":%.4f},\"firstPTS\":%.9f,\"lastPTS\":%.9f,",
           shot / iters * 1000, first, last);
    if (play && last <= first) return 10;

    check(mpv_set_property_string(m, "pause", "yes"));
    const char *seek[] = {"seek", "1", "absolute+exact", NULL};
    check(mpv_command(m, seek));
    ready = 0;
    for (int i = 0; i < 500 && !ready; i++) {
        pump();
        mpv_wait_event(m, .01);
        if (capture(m, &n, width, "waveform", "auto") >= 0)
            ready = fabs(field(&n, "pts", MPV_FORMAT_DOUBLE)->u.double_ - 1) < 1e-6;
        mpv_free_node_contents(&n);
    }
    if (!ready) return 11;
    const char *stop[] = {"stop", NULL};
    check(mpv_command(m, stop));
    if (capture(m, &n, width, "waveform", "auto") >= 0) return 12;
    mpv_free_node_contents(&n);
    mpv_terminate_destroy(m);
    printf("\"seekAndStop\":true}\n");
    return 0;
}
