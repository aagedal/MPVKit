// Copyright © 2026 Truls Aagedal
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Native client for aagedal-decoder-raster (protocol 2).
// Usage: INPUT OUTPUT HWDEC
// Pauses on the first frame, writes the raster bytes to OUTPUT and prints its
// metadata and mean capture time as JSON. The raster comes from the decoder,
// not the VO, but hardware decoding needs a GPU VO: build as Objective-C with
// -DSCOPE_GPU for gpu-next on a CAMetalLayer, otherwise vo=null.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include "mpv/client.h"
#ifdef SCOPE_GPU
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
static NSWindow *window;
static void configure(mpv_handle *m) {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    [NSApp finishLaunching];
    window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,640,360)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    CAMetalLayer *layer = [CAMetalLayer layer]; layer.device = MTLCreateSystemDefaultDevice();
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
    }
}
#else
static void configure(mpv_handle *m) { mpv_set_option_string(m, "vo", "null"); }
static void pump(void) {}
#endif

static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void check(int r) {
    if (r < 0) { fprintf(stderr, "%s\n", mpv_error_string(r)); exit(2); }
}
static mpv_node *field(mpv_node *n, const char *key, mpv_format format) {
    if (n->format == MPV_FORMAT_NODE_MAP) {
        for (int i = 0; i < n->u.list->num; i++) {
            if (!strcmp(n->u.list->keys[i], key) && n->u.list->values[i].format == format)
                return &n->u.list->values[i];
        }
    }
    fprintf(stderr, "bad field %s\n", key);
    exit(3);
}

// Waits until a decoder raster is available, then returns its tightly packed
// pixels and media-time PTS. NULL on timeout or failure.
static unsigned char *grab(mpv_handle *m, size_t *size, double *pts) {
    for (int i = 0; i < 500; i++) {
        double p;
        if (mpv_get_property(m, "aagedal-decoder-raster-pts", MPV_FORMAT_DOUBLE, &p) >= 0) break;
        pump();
        mpv_wait_event(m, .01);
    }
    const char *cmd[] = {"aagedal-decoder-raster", NULL};
    mpv_node n;
    if (mpv_command_ret(m, cmd, &n) < 0) return NULL;
    mpv_byte_array *ba = field(&n, "data", MPV_FORMAT_BYTE_ARRAY)->u.ba;
    int64_t w = field(&n, "w", MPV_FORMAT_INT64)->u.int64;
    int64_t h = field(&n, "h", MPV_FORMAT_INT64)->u.int64;
    int64_t stride = field(&n, "stride", MPV_FORMAT_INT64)->u.int64;
    int bpp = !strcmp(field(&n, "format", MPV_FORMAT_STRING)->u.string, "rgba64") ? 8 : 4;
    *pts = field(&n, "pts", MPV_FORMAT_DOUBLE)->u.double_;
    *size = w * h * bpp;
    unsigned char *out = malloc(*size);
    for (int64_t y = 0; y < h; y++)
        memcpy(out + y * w * bpp, (char *)ba->data + y * stride, w * bpp);
    mpv_free_node_contents(&n);
    return out;
}

static void settle(mpv_handle *m, int ticks) {
    for (int i = 0; i < ticks; i++) { pump(); mpv_wait_event(m, .01); }
}

// RASTER_BACKWARD: play backward from 2 s, pause, capture; the raster must
// report media time (matching time-pos) and equal the same frame reached
// forward by an exact seek. Returns 0 or an exit code.
static int backward_check(mpv_handle *m) {
    const char *mid[] = {"seek", "2", "absolute+exact", NULL};
    check(mpv_command(m, mid));
    settle(m, 50);
    check(mpv_set_property_string(m, "play-direction", "backward"));
    settle(m, 50);
    check(mpv_set_property_string(m, "pause", "no"));
    // Backward output starts after the GOP is decoded; play some of it.
    double pos;
    for (int i = 0; i < 500; i++) {
        settle(m, 1);
        if (mpv_get_property(m, "time-pos", MPV_FORMAT_DOUBLE, &pos) >= 0 && pos < 1.8)
            break;
    }
    check(mpv_set_property_string(m, "pause", "yes"));
    settle(m, 20);
    size_t back_size, fwd_size;
    double back_pts, fwd_pts;
    unsigned char *back = grab(m, &back_size, &back_pts);
    if (!back) return 20;
    if (mpv_get_property(m, "time-pos", MPV_FORMAT_DOUBLE, &pos) < 0) return 21;
    if (!(back_pts > 0 && back_pts < 2) || fabs(back_pts - pos) > 1e-3) {
        fprintf(stderr, "backward raster pts %.6f, time-pos %.6f\n", back_pts, pos);
        return 22;
    }

    check(mpv_set_property_string(m, "play-direction", "forward"));
    settle(m, 50);
    char target[64];
    snprintf(target, sizeof(target), "%.9f", back_pts);
    const char *seek[] = {"seek", target, "absolute+exact", NULL};
    check(mpv_command(m, seek));
    settle(m, 50);
    unsigned char *fwd = grab(m, &fwd_size, &fwd_pts);
    if (!fwd) return 23;
    int same = back_size == fwd_size && !memcmp(back, fwd, back_size);
    printf("\"backward\":{\"pts\":%.6f,\"timePos\":%.6f,\"forwardPTS\":%.6f,"
           "\"identicalToForward\":%d},", back_pts, pos, fwd_pts, same);
    free(back);
    free(fwd);
    return same && fabs(fwd_pts - back_pts) < 1e-6 ? 0 : 24;
}

int main(int argc, char **argv) {
    if (argc < 4) return 1;
    mpv_handle *m = mpv_create();
    configure(m);
    mpv_set_option_string(m, "ao", "null");
    mpv_set_option_string(m, "hwdec", argv[3]);
    mpv_set_option_string(m, "pause", "yes");
    mpv_set_option_string(m, "keep-open", "yes");
    mpv_set_option_string(m, "aagedal-decoder-raster", "yes");
    mpv_set_option_string(m, "msg-level", "all=error");
    check(mpv_initialize(m));

    const char *cmd[] = {"aagedal-decoder-raster", NULL};
    mpv_node n;
    if (mpv_command_ret(m, cmd, &n) >= 0) return 4;
    const char *load[] = {"loadfile", argv[1], NULL};
    check(mpv_command(m, load));
    int ready = 0;
    for (int i = 0; i < 500 && !ready; i++) {
        pump();
        mpv_wait_event(m, .01);
        double pts;
        ready = mpv_get_property(m, "aagedal-decoder-raster-pts", MPV_FORMAT_DOUBLE, &pts) >= 0;
    }
    if (!ready) return 5;

    check(mpv_command_ret(m, cmd, &n));
    if (field(&n, "protocol", MPV_FORMAT_INT64)->u.int64 != 2) return 6;
    // Hardware decoding requested must actually deliver hardware frames.
    if (strcmp(argv[3], "no") && !field(&n, "hardware-transfer", MPV_FORMAT_FLAG)->u.flag)
        return 10;
    mpv_byte_array *ba = field(&n, "data", MPV_FORMAT_BYTE_ARRAY)->u.ba;
    int64_t w = field(&n, "w", MPV_FORMAT_INT64)->u.int64;
    int64_t h = field(&n, "h", MPV_FORMAT_INT64)->u.int64;
    int64_t stride = field(&n, "stride", MPV_FORMAT_INT64)->u.int64;
    const char *format = field(&n, "format", MPV_FORMAT_STRING)->u.string;
    int bpp = !strcmp(format, "rgba64") ? 8 : 4;
    if (ba->size != (size_t)(stride * h) || stride < w * bpp) return 7;
    FILE *file = fopen(argv[2], "wb");
    if (!file) return 8;
    // Tightly packed rows, so outputs with different strides compare equal.
    for (int64_t y = 0; y < h; y++)
        fwrite((char *)ba->data + y * stride, 1, w * bpp, file);
    fclose(file);
    printf("{\"w\":%lld,\"h\":%lld,\"codedW\":%lld,\"codedH\":%lld,\"rotation\":%lld,"
           "\"mirrored\":%d,\"format\":\"%s\",\"primaries\":\"%s\",\"transfer\":\"%s\","
           "\"bitDepth\":%lld,\"hardware\":%d,\"pts\":%.9f,",
           (long long)w, (long long)h,
           (long long)field(&n, "coded-w", MPV_FORMAT_INT64)->u.int64,
           (long long)field(&n, "coded-h", MPV_FORMAT_INT64)->u.int64,
           (long long)field(&n, "rotation", MPV_FORMAT_INT64)->u.int64,
           field(&n, "mirrored", MPV_FORMAT_FLAG)->u.flag, format,
           field(&n, "primaries", MPV_FORMAT_STRING)->u.string,
           field(&n, "transfer", MPV_FORMAT_STRING)->u.string,
           (long long)field(&n, "source-bit-depth", MPV_FORMAT_INT64)->u.int64,
           field(&n, "hardware-transfer", MPV_FORMAT_FLAG)->u.flag,
           field(&n, "pts", MPV_FORMAT_DOUBLE)->u.double_);
    mpv_free_node_contents(&n);

    double total = 0;
    for (int i = 0; i < 10; i++) {
        double start = now();
        check(mpv_command_ret(m, cmd, &n));
        total += now() - start;
        mpv_free_node_contents(&n);
    }
    if (getenv("RASTER_BACKWARD")) {
        int err = backward_check(m);
        if (err) return err;
    }
    // Unpaused playback revokes the raster.
    check(mpv_set_property_string(m, "pause", "no"));
    for (int i = 0; i < 20; i++) { pump(); mpv_wait_event(m, .01); }
    int revoked = mpv_command_ret(m, cmd, &n) < 0;
    if (!revoked) mpv_free_node_contents(&n);
    mpv_terminate_destroy(m);
    printf("\"meanMS\":%.3f,\"revokedWhilePlaying\":%d}\n", total / 10 * 1000, revoked);
    return revoked ? 0 : 9;
}
