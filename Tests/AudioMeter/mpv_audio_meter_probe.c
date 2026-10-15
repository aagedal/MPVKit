// SPDX-License-Identifier: GPL-3.0-or-later
// Isolated libmpv metadata probe; no audio hardware or display required.
#include <mpv/client.h>
#include <libavfilter/avfilter.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void require(int status, const char *operation) {
    if (status < 0) { fprintf(stderr, "%s: %s\n", operation, mpv_error_string(status)); exit(2); }
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *filters[] = {"astats", "asetnsamples", "ebur128"};
    for (int i = 0; i < 3; ++i) {
        if (!avfilter_get_by_name(filters[i])) { fprintf(stderr, "Missing %s\n", filters[i]); return 3; }
    }
    mpv_handle *mpv = mpv_create();
    if (!mpv) return 2;
    require(mpv_set_option_string(mpv, "vo", "null"), "vo");
    require(mpv_set_option_string(mpv, "ao", "null"), "ao");
    require(mpv_set_option_string(mpv, "audio-channels", "auto"), "channels");
    require(mpv_set_option_string(mpv, "keep-open", "yes"), "keep-open");
    require(mpv_set_option_string(mpv, "load-scripts", "no"), "scripts");
    require(mpv_initialize(mpv), "initialize");
    // Exercise runtime installation, the same path a meter toggle uses.
    const char *add[] = {"af", "add", argv[2], NULL};
    require(mpv_command(mpv, add), "add filter");
    const char *load[] = {"loadfile", argv[1], "replace", NULL};
    require(mpv_command_async(mpv, 1, load), "load");
    int observed = 0;
    for (int tick = 0; tick < 350; ++tick) {
        mpv_event *event = mpv_wait_event(mpv, 0.02);
        if (event->event_id == MPV_EVENT_END_FILE) {
            mpv_event_end_file *end = event->data;
            if (end->reason == MPV_END_FILE_REASON_ERROR) require(end->error, "decode");
        }
        double position = 0;
        if (mpv_get_property(mpv, "time-pos", MPV_FORMAT_DOUBLE, &position) < 0 || position < 1.1) continue;
        mpv_node node = {0};
        if (mpv_get_property(mpv, "af-metadata/meter", MPV_FORMAT_NODE, &node) < 0) continue;
        if (node.format == MPV_FORMAT_NODE_MAP && node.u.list && node.u.list->num > 0) {
            mpv_node_list *list = node.u.list;
            printf("{\"position\":%.6f,\"metadata\":{", position);
            int count = 0;
            for (int i = 0; i < list->num; ++i) {
                if (list->values[i].format != MPV_FORMAT_STRING) continue;
                // libavfilter's metering metadata keys and values are numeric/ASCII.
                printf("%s\"%s\":\"%s\"", count++ ? "," : "", list->keys[i], list->values[i].u.string);
            }
            printf("}}\n");
            observed = count;
        }
        mpv_free_node_contents(&node);
        if (observed) break;
    }
    // A removed analysis filter must not leave the player unable to seek/play.
    const char *remove[] = {"af", "remove", "@meter", NULL};
    require(mpv_command(mpv, remove), "remove filter");
    const char *seek[] = {"seek", "0.5", "absolute+exact", NULL};
    require(mpv_command(mpv, seek), "seek after removal");
    int resumed = 0;
    for (int tick = 0; tick < 150; ++tick) {
        mpv_event *event = mpv_wait_event(mpv, 0.02);
        if (event->event_id == MPV_EVENT_PLAYBACK_RESTART) { resumed = 1; break; }
    }
    mpv_terminate_destroy(mpv);
    return observed && resumed ? 0 : 4;
}
