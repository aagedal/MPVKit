// Copyright © 2026 Truls Aagedal
// SPDX-License-Identifier: GPL-3.0-or-later
// CPU scope math (mpv video/scope.c), run under ASan/UBSan:
// clang -fsanitize=address,undefined -O1 -g -I<mpv>/video -I<libplacebo include>
// Only libplacebo headers are needed; the matrix lookups are stubbed with the
// published BT.709/BT.2020 luma coefficients, and the HDR test with a peak.
#include "scope.c"
#include <assert.h>
#include <stdio.h>

static const struct pl_raw_primaries prim_stub;
const struct pl_raw_primaries *pl_raw_primaries_get(enum pl_color_primaries prim)
{
    return prim == PL_COLOR_PRIM_BT_709 || prim == PL_COLOR_PRIM_BT_2020 ? &prim_stub : NULL;
}
float pl_color_transfer_nominal_peak(enum pl_color_transfer trc)
{
    return trc >= PL_COLOR_TRC_PQ ? 10 : 1; // HDR transfers follow PQ in the enum
}
static enum pl_color_primaries current_prim;
pl_matrix3x3 pl_get_rgb2xyz_matrix(const struct pl_raw_primaries *prim)
{
    pl_matrix3x3 m = {0};
    bool bt2020 = current_prim == PL_COLOR_PRIM_BT_2020;
    m.m[1][0] = bt2020 ? 0.2627f : 0.2126f;
    m.m[1][1] = bt2020 ? 0.6780f : 0.7152f;
    m.m[1][2] = bt2020 ? 0.0593f : 0.0722f;
    return m;
}

static bool init(struct mp_scope_params *sp, int w, int plots,
                 enum pl_color_primaries prim, enum pl_color_transfer trc)
{
    current_prim = prim;
    struct pl_color_space color = { .primaries = prim, .transfer = trc };
    return mp_scope_params_init(sp, w, plots, &color);
}

int main(void)
{
    struct mp_scope_params sp;
    int cases = 0;

    // Independently known ST 2084 and fixed-gamma HLG anchors.
    assert(init(&sp, 64, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_2020, PL_COLOR_TRC_PQ));
    assert(fabsf(scope_nits(&sp, 0.50807842f) - 100) < .05);
    assert(fabsf(scope_nits(&sp, 0.7518271f) - 1000) < .5);
    assert(fabsf(scope_nits(&sp, 1) - 10000) < 1);
    assert(init(&sp, 64, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_2020, PL_COLOR_TRC_HLG));
    assert(fabsf(scope_nits(&sp, 1) - 1000) < .1);

    // Supported and rejected signals, sizes and plot masks.
    assert(init(&sp, 720, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_BT_1886));
    assert(sp.transfer == MP_SCOPE_SDR && sp.h == 405 && fabsf(sp.kr - 0.2126f) < 1e-6);
    assert(init(&sp, 72, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_SRGB) && sp.h == 41);
    assert(!init(&sp, 720, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_UNKNOWN));
    assert(!init(&sp, 720, MP_SCOPE_ALL, PL_COLOR_PRIM_UNKNOWN, PL_COLOR_TRC_BT_1886));
    assert(!init(&sp, 720, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_2020, PL_COLOR_TRC_V_LOG));
    assert(!init(&sp, 63, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_BT_1886));
    assert(!init(&sp, 1441, MP_SCOPE_ALL, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_BT_1886));
    assert(!init(&sp, 720, 0, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_BT_1886));

    // Rotation moves samples between columns: a black left half and a white
    // right half of a 4x2 image land in mirrored columns when rotated 180.
    uint16_t lr[4 * 2 * 4] = {0};
    for (int y = 0; y < 2; y++)
        for (int x = 2; x < 4; x++)
            for (int c = 0; c < 4; c++) lr[(y * 4 + x) * 4 + c] = 65535;
    assert(init(&sp, 64, MP_SCOPE_WAVEFORM, PL_COLOR_PRIM_BT_709, PL_COLOR_TRC_BT_1886));
    for (int rot = 0; rot <= 180; rot += 180) {
        struct mp_scope_layout l;
        mp_scope_layout(&sp, &l);
        uint32_t *bins = calloc(l.total, 4);
        mp_scope_accumulate(&sp, bins, lr, 4, 2, 4 * 8, rot);
        // Source columns 0..3 map to plot columns 0, 16, 32, 48; white is
        // the top row, black the bottom row.
        for (int x = 0; x < 4; x++) {
            int col = (rot ? 3 - x : x) * sp.w / 4;
            bool white = x >= 2;
            assert(bins[((white ? 0 : sp.h - 1) * sp.w + col) * 4] == 2);
            assert(bins[((white ? sp.h - 1 : 0) * sp.w + col) * 4] == 0);
        }
        free(bins);
        cases++;
    }

    // Bounds, counts and premultiplication over sizes, transfers, rotations
    // and plot masks, with extreme sample values in the source.
    enum { SW = 23, SH = 17 };
    uint16_t src[SW * SH * 4];
    for (int i = 0; i < SW * SH; i++) {
        src[i * 4 + 0] = i % 3 ? i * 263 % 65536 : 0;
        src[i * 4 + 1] = i % 5 ? (SW * SH - i) * 211 % 65536 : 65535;
        src[i * 4 + 2] = i % 7 * 9362;
        src[i * 4 + 3] = 65535;
    }
    const int widths[] = {64, 360, 720, 1080, 1440};
    const enum pl_color_transfer trcs[] = {PL_COLOR_TRC_BT_1886, PL_COLOR_TRC_PQ, PL_COLOR_TRC_HLG};
    const int masks[] = {MP_SCOPE_WAVEFORM, MP_SCOPE_PARADE, MP_SCOPE_VECTORSCOPE, MP_SCOPE_ALL};
    for (int k = 0; k < 5; k++)
    for (int t = 0; t < 3; t++)
    for (int rot = 0; rot < 360; rot += 90)
    for (int m = 0; m < 4; m++) {
        assert(init(&sp, widths[k], masks[m], t ? PL_COLOR_PRIM_BT_2020 : PL_COLOR_PRIM_BT_709, trcs[t]));
        struct mp_scope_layout l;
        mp_scope_layout(&sp, &l);
        uint32_t *bins = calloc(l.total, 4);
        mp_scope_accumulate(&sp, bins, src, SW, SH, SW * 8, rot);
        uint64_t wave = 0, parade = 0, vector = 0;
        for (size_t i = l.wave; i < l.parade; i += 4) wave += bins[i];
        for (size_t i = l.parade; i < l.vector; i++) parade += bins[i];
        for (size_t i = l.vector; i < l.max; i += 4) vector += bins[i];
        assert(wave == (masks[m] & MP_SCOPE_WAVEFORM ? SW * SH : 0));
        assert(parade == (masks[m] & MP_SCOPE_PARADE ? 4 * SW * SH : 0));
        assert(masks[m] & MP_SCOPE_VECTORSCOPE ? vector > 0 && vector <= SW * SH : !vector);

        uint8_t *plot[3] = {0};
        for (int i = 0; i < 3; i++)
            if (sp.plots & (1 << i)) plot[i] = calloc(mp_scope_plot_size(&sp, i), 1);
        mp_scope_paint(&sp, bins, plot);
        // Premultiplied waveform colors never exceed their alpha.
        if (plot[0]) {
            for (int i = 0; i < sp.w * sp.h; i++)
                for (int c = 0; c < 3; c++) assert(plot[0][4 * i + c] <= plot[0][4 * i + 3]);
        }
        for (int i = 0; i < 3; i++) free(plot[i]);
        free(bins);
        cases++;
    }
    printf("NATIVE_SCOPE_MATH_ACCEPTANCE: %d accumulation/paint cases, ASan/UBSan\n", cases);
    return 0;
}
