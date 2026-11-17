/* hp2codec: the game's movie codec (MV30, "MV3") and the PS2 SPU ADPCM, both ways, for the mod manager (ctypes).
 *
 * The decoder follows the port's native one (nfshp2-port-win, recomp/runtime/native_movie.cpp, itself retail's DCTImage::ToImage and
 * Huffman::Decompress) with the tables of retail's data (reNFSHP2's dcttable.cpp, dctimage.cpp, huffman2.cpp). The encoder writes
 * key frames only: a frame is s8 quality, s8 delta, u16 layout 0, then s16 size of the block types, the block types (2 bits
 * a block, low pair first; 0 grey, 1 DC, 2 the four low coefficients, 3 all 64 in zigzag), and one MSB-first bit stream with
 * a 16-bit coefficient count before each row of macroblocks. DC is coded as the difference from the block before in the
 * same row and plane. Planes are 4:2:0, stored bottom row first, full-range BT.601.
 *
 * Build: clang -O2 -shared -o hp2codec.dll hp2codec.c (see build.sh).
 */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

typedef uint8_t u8;
typedef int16_t s16;
typedef uint32_t u32;

static const s16 LUMA[64] = {12, 12, 15, 19, 25, 34, 40, 48, 12, 12, 18, 22, 27, 44, 47, 46, 17, 18, 21, 26, 35, 46,
                             52, 47, 18, 20, 24, 28, 40, 61, 59, 51, 20, 24, 32, 43, 50, 72, 72, 63, 25, 31, 42, 48,
                             58, 72, 81, 75, 38, 46, 54, 61, 71, 84, 88, 85, 50, 61, 65, 68, 79, 78, 86, 91};
static const s16 CHROMA[64] = {12, 16, 24, 47, 99, 99, 99, 99, 16, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99,
                               99, 99, 47, 66, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
                               99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99};
/* natural position -> coded (zigzag) position */
static const int ZIGZAG[64] = {0,  1,  5,  6,  14, 15, 27, 28, 2,  3,  7,  13, 16, 26, 29, 42, 4,  8,  12, 17, 25, 30,
                               41, 43, 9,  11, 18, 24, 31, 40, 44, 53, 10, 19, 23, 32, 39, 45, 52, 54, 20, 22, 33, 38,
                               46, 51, 55, 60, 21, 34, 37, 47, 50, 56, 59, 61, 35, 36, 48, 49, 57, 58, 62, 63};
static const s16 AAN[64] = {16384, 22725, 21407, 19266, 16384, 12873, 8867,  4520,  22725, 31521, 29692, 26722, 22725,
                            17855, 12299, 6270,  21407, 29692, 27969, 25172, 21407, 16819, 11585, 5906,  19266, 26722,
                            25172, 22654, 19266, 15137, 10426, 5315,  16384, 22725, 21407, 19266, 16384, 12873, 8867,
                            4520,  12873, 17855, 16819, 15137, 12873, 10114, 6967,  3552,  8867,  12299, 11585, 10426,
                            8867,  6967,  4799,  2446,  4520,  6270,  5906,  5315,  4520,  3552,  2446,  1247};
/* class 0 (a run of zeros) to 11: {code, length} */
static const int PREFIX[12][2] = {{0, 2},    {1, 2},     {4, 3},     {5, 3},     {6, 3},     {14, 4},
                                  {30, 5},   {62, 6},    {126, 7},   {254, 8},   {510, 9},   {511, 9}};
static const int ADVANCE[4] = {0, 1, 4, 64};

static int quality_scale(int q)
{
    if (q <= 0) q = 1;
    if (q > 100) q = 100;
    return q < 50 ? 5000 / q : 200 - q * 2;
}

/* the quantiser of a quality as the encoder divides by (the plain scaled table) */
static void plain_table(const s16 *base, int q, int *out)
{
    int sc = quality_scale(q);
    for (int i = 0; i < 64; i++) {
        int v = (base[i] * sc + 50) / 100;
        if (v <= 0) v = 1;
        if (v > 32767) v = 32767;
        out[i] = v;
    }
}

/* and as the decoder multiplies by (with the AAN scales) */
static void idct_table(const s16 *base, int q, s16 *out)
{
    int t[64];
    plain_table(base, q, t);
    for (int i = 0; i < 64; i++) out[i] = (s16)((t[i] * AAN[i] + 2048) >> 12);
}

/* ---- the clamp: 0 below 0, 255 above ---------------------------------------------------------------------------------- */
static u8 CLAMP_TAB[1024 * 4];
static const u8 *CLAMP;   /* CLAMP[x] for x in [-2048, 2048) */
static void init_clamp(void)
{
    if (CLAMP) return;
    for (int i = 0; i < 4096; i++) {
        int v = i - 2048;
        CLAMP_TAB[i] = (u8)(v < 0 ? 0 : v > 255 ? 255 : v);
    }
    CLAMP = CLAMP_TAB + 2048;
}
#define RANGE(x) CLAMP[(x) + 128]

/* ---- inverse transforms (retail's DCTBlock, IJG ifast) ---------------------------------------------------------------- */
#define MUL(x, c) (((x) * (c)) >> 8)

static void idct_columns(const s16 *in, const s16 *q, int *ws)
{
    for (int c = 8; c > 0; c--) {
        int t0 = in[0] * q[0], t1 = in[16] * q[16], t2 = in[32] * q[32], t3 = in[48] * q[48];
        int t10 = t0 + t2, t11 = t0 - t2, t13 = t1 + t3, t12 = MUL(t1 - t3, 362) - t13;
        t0 = t10 + t13;
        t3 = t10 - t13;
        t1 = t11 + t12;
        t2 = t11 - t12;
        int t4 = in[8] * q[8], t5 = in[24] * q[24], t6 = in[40] * q[40], t7 = in[56] * q[56];
        int z13 = t6 + t5, z10 = t6 - t5, z11 = t4 + t7, z12 = t4 - t7;
        t7 = z11 + z13;
        t11 = MUL(z11 - z13, 362);
        int z5 = MUL(z10 + z12, 473);
        t10 = MUL(z12, 277) - z5;
        t12 = MUL(z10, -669) + z5;
        t6 = t12 - t7;
        t5 = t11 - t6;
        t4 = t10 + t5;
        ws[0] = t0 + t7;
        ws[56] = t0 - t7;
        ws[8] = t1 + t6;
        ws[48] = t1 - t6;
        ws[16] = t2 + t5;
        ws[40] = t2 - t5;
        ws[32] = t3 + t4;
        ws[24] = t3 - t4;
        in++, q++, ws++;
    }
}

static void idct_row(const int *w, int o[8])
{
    int t10 = w[0] + w[4], t11 = w[0] - w[4], t13 = w[2] + w[6], t12 = MUL(w[2] - w[6], 362) - t13;
    int t0 = t10 + t13, t3 = t10 - t13, t1 = t11 + t12, t2 = t11 - t12;
    int z13 = w[5] + w[3], z10 = w[5] - w[3], z11 = w[1] + w[7], z12 = w[1] - w[7];
    int t7 = z11 + z13;
    t11 = MUL(z11 - z13, 362);
    int z5 = MUL(z10 + z12, 473);
    t10 = MUL(z12, 277) - z5;
    t12 = MUL(z10, -669) + z5;
    int t6 = t12 - t7, t5 = t11 - t6, t4 = t10 + t5;
    o[0] = t0 + t7, o[1] = t1 + t6, o[2] = t2 + t5, o[3] = t3 - t4;
    o[4] = t3 + t4, o[5] = t2 - t5, o[6] = t1 - t6, o[7] = t0 - t7;
}

static void idct4_columns(const s16 *in, const s16 *q, int *ws)
{
    for (int c = 2; c > 0; c--) {
        if (in[2] == 0) {
            int dc = in[0] * q[0];
            for (int r = 0; r < 8; r++) ws[r * 8] = dc;
        } else {
            int t4 = in[2] * q[8], t0 = in[0] * q[0];
            int t11 = MUL(t4, 362), z5 = MUL(t4, 473), t10 = MUL(t4, 277) - z5;
            ws[56] = t0 - t4;
            ws[0] = t0 + t4;
            int t6 = z5 - t4, t5 = t11 - t6, t7 = t10 + t5;
            ws[8] = t0 + t6;
            ws[48] = t0 - t6;
            ws[16] = t0 + t5;
            ws[40] = t0 - t5;
            ws[32] = t0 + t7;
            ws[24] = t0 - t7;
        }
        in++, q++, ws++;
    }
}

static void idct4_row(int t0, int z11, int v[8])
{
    int t11 = MUL(z11, 362), z5 = MUL(z11, 473), t10 = MUL(z11, 277) - z5;
    int t6 = z5 - z11, t5 = t11 - t6, t4 = t10 + t5;
    v[0] = t0 + z11, v[1] = t0 + t6, v[2] = t0 + t5, v[3] = t0 - t4;
    v[4] = t0 + t4, v[5] = t0 - t5, v[6] = t0 - t6, v[7] = t0 - z11;
}

/* type: 0 grey, 1 DC, 2 four, 3 full (in natural order); add: on top of what is there */
static void put_block(int type, const s16 *c, const s16 *q, u8 *out, int width, int add)
{
    int ws[64], v[8];
    if (type == 0) {
        if (!add)
            for (int y = 0; y < 8; y++) memset(out + y * width, 0x80, 8);
        return;
    }
    if (type == 1) {
        int dc = (c[0] * q[0]) >> 5;
        for (int y = 0; y < 8; y++)
            for (int x = 0; x < 8; x++) out[y * width + x] = add ? CLAMP[dc + out[y * width + x]] : RANGE(dc);
        return;
    }
    if (type == 2) {
        idct4_columns(c, q, ws);
        for (int y = 0; y < 8; y++) {
            int z11 = ws[y * 8 + 1], t0 = ws[y * 8];
            if (z11 == 0)
                for (int i = 0; i < 8; i++) v[i] = t0;
            else
                idct4_row(t0, z11, v);
            for (int i = 0; i < 8; i++) {
                u8 *p = out + y * width + i;
                *p = add ? CLAMP[(v[i] >> 5) + *p] : RANGE(v[i] >> 5);
            }
        }
        return;
    }
    idct_columns(c, q, ws);
    for (int y = 0; y < 8; y++) {
        idct_row(ws + y * 8, v);
        for (int i = 0; i < 8; i++) {
            u8 *p = out + y * width + i;
            *p = add ? CLAMP[(v[i] >> 5) + *p] : RANGE(v[i] >> 5);
        }
    }
}

/* ---- the bit stream --------------------------------------------------------------------------------------------------- */
typedef struct {
    const u8 *p, *end;
    u32 accum, count;
} Bits;

static void fill(Bits *b)
{
    while (b->count < 25) {
        u32 byte = b->p < b->end ? *b->p : 0;
        b->p++;
        b->accum |= byte << (24 - b->count);
        b->count += 8;
    }
}

static u32 get_bits(Bits *b, u32 n)
{
    if (n == 0) return 0;
    fill(b);
    u32 v = b->accum >> (32 - n);
    b->accum = n >= 32 ? 0 : b->accum << n;
    b->count -= n;
    return v;
}

/* count values into out (which has 128 to spare: a run may write past the count, as retail's does) */
static void decompress(Bits *b, s16 *out, int count)
{
    s16 *end = out + count;
    while (out < end) {
        int cls;
        /* the prefix: 00 01 100 101 110 1110 11110 ... 111111110 111111111 */
        if (get_bits(b, 1) == 0) {
            cls = get_bits(b, 1);                          /* 00 -> 0, 01 -> 1 */
        } else {
            u32 two = get_bits(b, 2);
            if (two != 3) {
                cls = 2 + (int)two;                        /* 100 101 110 */
            } else {
                cls = 5;                                   /* 1110, then one more 1 a class */
                while (cls < 10 && get_bits(b, 1)) cls++;
                if (cls == 10) cls = get_bits(b, 1) ? 11 : 10;
            }
        }
        if (cls == 0) {
            int run = get_bits(b, 1) ? (int)get_bits(b, 6) + 9 : (int)get_bits(b, 3) + 1;
            for (int i = 0; i < run; i++) *out++ = 0;
            continue;
        }
        int neg = (int)get_bits(b, 1);
        int k = cls - 1;
        int v = (1 << k) + (int)get_bits(b, (u32)k);
        *out++ = (s16)(neg ? -v : v);
    }
}

/* ---- the decoder ------------------------------------------------------------------------------------------------------ */
typedef struct {
    int w, h;
    u8 *y, *u, *v, *py, *pu, *pv;
    s16 *vects, *pvects;
    s16 *dct;
    u8 *transp;
} Decoder;

EXPORT Decoder *mv3_decoder_new(int w, int h)
{
    init_clamp();
    Decoder *d = (Decoder *)calloc(1, sizeof(Decoder));
    d->w = w, d->h = h;
    int a = w * h, c = a / 4, mbs = (w / 16) * (h / 16);
    d->y = (u8 *)calloc(a, 1), d->py = (u8 *)calloc(a, 1);
    d->u = (u8 *)calloc(c, 1), d->pu = (u8 *)calloc(c, 1);
    d->v = (u8 *)calloc(c, 1), d->pv = (u8 *)calloc(c, 1);
    d->vects = (s16 *)calloc(mbs * 2 + 256, 2), d->pvects = (s16 *)calloc(mbs * 2 + 256, 2);
    d->dct = (s16 *)calloc((w / 16) * 6 * 64 + 256, 2);
    d->transp = (u8 *)calloc(mbs / 4 + 4, 1);
    memset(d->py, 0, a);
    return d;
}

EXPORT void mv3_decoder_free(Decoder *d)
{
    if (!d) return;
    free(d->y), free(d->u), free(d->v), free(d->py), free(d->pu), free(d->pv);
    free(d->vects), free(d->pvects), free(d->dct), free(d->transp);
    free(d);
}

#define SWAP(a, b)              \
    do {                        \
        void *t_ = (void *)(a); \
        *(void **)&(a) = (b);   \
        *(void **)&(b) = t_;    \
    } while (0)

/* one frame chunk (its 4-byte header and data); rgb: w*h*3, top row first. Answers 0, or -1 for a frame it cannot read */
EXPORT int mv3_decode(Decoder *d, const u8 *chunk, int size, u8 *rgb)
{
    if (size < 6) return -1;
    const int w = d->w, h = d->h, half = w / 2, mbs = (w / 16) * (h / 16);
    int qual = (signed char)chunk[0], delta = (signed char)chunk[1];
    int layout = (chunk[2] << 8) | chunk[3];
    const u8 *comp = chunk + 4, *end = chunk + size;
    int key = layout == 0;
    s16 tab[4][64];
    idct_table(LUMA, qual, tab[0]);
    idct_table(LUMA, qual + delta, tab[1]);
    idct_table(CHROMA, qual, tab[2]);
    idct_table(CHROMA, qual + delta, tab[3]);
    s16 s;
    memcpy(&s, comp, 2);
    int typesize = s, reserve, vectsize = 0;
    if (key) {
        reserve = 2;
    } else {
        reserve = (mbs + 3) / 4 + 4;
        memcpy(&s, comp + 2, 2);
        vectsize = s;
        memcpy(d->transp, comp + 4, (mbs + 3) / 4);
    }
    const u8 *types = comp + reserve;
    if (types + typesize > end) return -1;
    Bits b = {types + typesize, end, 0, 0};
    if (!key) {
        if (vectsize * 2 > mbs * 2 + 128) return -1;
        decompress(&b, d->vects, vectsize * 2);
    }
    int rowcount = w / 16, block = 0, vect = 0, ti = 0;
    u8 *py = d->y, *pu = d->u, *pv = d->v;
    int maxcoef = (w / 16) * 6 * 64;
#define TYPE(n) ((types[(n) / 4] >> (((n) & 3) * 2)) & 3)
    for (int y = 0; y < h; y += 16) {
        int rowsize = (int)get_bits(&b, 16);
        if (!key) rowcount = (int)get_bits(&b, 8);
        if (rowsize > maxcoef) return -1;
        decompress(&b, d->dct, rowsize);
        int prev[3] = {0, 0, 0}, idx = block;
        s16 *c = d->dct;
        for (int i = 0; i < rowcount; i++) {
            for (int k = 0; k < 6; k++) {
                int t = TYPE(idx), ch = k < 4 ? 0 : k - 3;
                if (ADVANCE[t]) {
                    prev[ch] = (s16)(*c += (s16)prev[ch]);
                    c += ADVANCE[t];
                }
                idx++;
            }
        }
        c = d->dct;
        for (int x = 0; x < w; x += 16) {
            u8 *dst[6] = {py, py + 8, py + w * 8, py + w * 8 + 8, pu, pv};
            int wid[6] = {w, w, w, w, half, half};
            if (!key && ((d->transp[ti >> 2] >> (ti & 3)) & 1)) {
                const s16 *mv = d->vects + vect * 2;
                int vx = x + mv[0], vy = y + mv[1];
                if (vx < 0 || vy < 0 || vx + 16 > w || vy + 16 > h) return -1;
                for (int r = 0; r < 16; r++) memcpy(py + r * w, d->py + (vy + r) * w + vx, 16);
                int off = (vy / 2) * half + vx / 2;
                for (int r = 0; r < 8; r++) memcpy(pu + r * half, d->pu + off + r * half, 8);
                for (int r = 0; r < 8; r++) memcpy(pv + r * half, d->pv + off + r * half, 8);
                if (!(d->transp[ti >> 2] & (16 << (ti & 3)))) {
                    for (int k = 0; k < 6; k++) {
                        int t = TYPE(block);
                        s16 nat[64];
                        const s16 *src = c;
                        if (t == 3) {
                            for (int i = 0; i < 64; i++) nat[i] = c[ZIGZAG[i]];
                            src = nat;
                        }
                        put_block(t, src, tab[k < 4 ? 1 : 3], dst[k], wid[k], 1);
                        c += ADVANCE[t];
                        block++;
                    }
                }
                vect++;
            } else {
                for (int k = 0; k < 6; k++) {
                    int t = TYPE(block);
                    s16 nat[64];
                    const s16 *src = c;
                    if (t == 3) {
                        for (int i = 0; i < 64; i++) nat[i] = c[ZIGZAG[i]];
                        src = nat;
                    }
                    put_block(t, src, tab[k < 4 ? 0 : 2], dst[k], wid[k], 0);
                    c += ADVANCE[t];
                    block++;
                }
            }
            py += 16, pu += 8, pv += 8, ti++;
        }
        py += w * 15, pu += half * 7, pv += half * 7;
    }
    /* YUV -> RGB, the plane's bottom row first */
    int j = 0;
    const u8 *Y = d->y;
    for (int yy = 0; yy < h; yy += 2) {
        for (int xx = 0; xx < w; xx += 2) {
            int V = d->v[j] - 128, U = d->u[j] - 128;
            int uv1 = (V * 359) / 256, uv2 = (U * -88 - V * 183) / 256, uv3 = (U * 454) / 256;
            for (int dy = 0; dy < 2; dy++)
                for (int dx = 0; dx < 2; dx++) {
                    int l = Y[(yy + dy) * w + xx + dx];
                    u8 *o = rgb + ((h - 1 - (yy + dy)) * w + xx + dx) * 3;
                    o[0] = CLAMP[l + uv1], o[1] = CLAMP[l + uv2], o[2] = CLAMP[l + uv3];
                }
            j++;
        }
    }
    SWAP(d->y, d->py);
    SWAP(d->u, d->pu);
    SWAP(d->v, d->pv);
    SWAP(d->vects, d->pvects);
    return 0;
}

/* ---- the encoder (key frames) ----------------------------------------------------------------------------------------- */
typedef struct {
    u8 *p;
    int cap, len;
    u32 acc;
    int n;
    int overflow;
} BitW;

static void put(BitW *w, u32 v, int n)
{
    for (int i = n - 1; i >= 0; i--) {
        w->acc = (w->acc << 1) | ((v >> i) & 1);
        if (++w->n == 8) {
            if (w->len < w->cap) w->p[w->len] = (u8)w->acc;
            else w->overflow = 1;
            w->len++;
            w->n = 0;
            w->acc = 0;
        }
    }
}

static void put_values(BitW *w, const s16 *v, int count)
{
    int i = 0;
    while (i < count) {
        if (v[i] == 0) {
            int run = 1;
            while (i + run < count && v[i + run] == 0 && run < 72) run++;
            put(w, PREFIX[0][0], PREFIX[0][1]);
            if (run <= 8) {
                put(w, 0, 1);
                put(w, (u32)(run - 1), 3);
            } else {
                put(w, 1, 1);
                put(w, (u32)(run - 9), 6);
            }
            i += run;
            continue;
        }
        int m = v[i] < 0 ? -v[i] : v[i];
        if (m > 2047) m = 2047;
        int k = 0;
        while ((1 << (k + 1)) <= m) k++;   /* m in [2^k, 2^(k+1)) */
        put(w, PREFIX[k + 1][0], PREFIX[k + 1][1]);
        put(w, v[i] < 0 ? 1u : 0u, 1);
        put(w, (u32)(m - (1 << k)), k);
        i++;
    }
}

static void fdct8(const double *in, double *out)
{
    static double cs[8][8];
    static int ready;
    if (!ready) {
        for (int u = 0; u < 8; u++)
            for (int x = 0; x < 8; x++) cs[u][x] = (u ? 0.5 : sqrt(0.125)) * cos((2 * x + 1) * u * 3.14159265358979323846 / 16);
        ready = 1;
    }
    double tmp[64];
    for (int y = 0; y < 8; y++)
        for (int u = 0; u < 8; u++) {
            double s = 0;
            for (int x = 0; x < 8; x++) s += cs[u][x] * in[y * 8 + x];
            tmp[y * 8 + u] = s;
        }
    for (int u = 0; u < 8; u++)
        for (int v = 0; v < 8; v++) {
            double s = 0;
            for (int y = 0; y < 8; y++) s += cs[v][y] * tmp[y * 8 + u];
            out[v * 8 + u] = s;
        }
}

/* one block of a plane (top-left at p) -> its coefficients in natural order */
static void block_coefs(const u8 *p, int width, const int *q, int *c)
{
    double in[64], out[64];
    for (int y = 0; y < 8; y++)
        for (int x = 0; x < 8; x++) in[y * 8 + x] = p[y * width + x] - 128.0;
    fdct8(in, out);
    for (int i = 0; i < 64; i++) {
        double v = out[i] / q[i];
        int r = (int)(v < 0 ? v - 0.5 : v + 0.5);
        if (r > 2047) r = 2047;
        if (r < -2047) r = -2047;
        c[i] = r;
    }
}

/* rgb: w*h*3, top row first. out gets the frame chunk's bytes (header included). Answers its length, or -(the length it
 * needs) when cap is short. */
EXPORT int mv3_encode_key(const u8 *rgb, int w, int h, int quality, u8 *out, int cap)
{
    init_clamp();
    const int half = w / 2, hh = h / 2, mbw = w / 16, mbh = h / 16, nblocks = mbw * mbh * 6;
    u8 *Y = (u8 *)malloc(w * h), *U = (u8 *)malloc(half * hh), *V = (u8 *)malloc(half * hh);
    /* planes bottom row first; full-range BT.601, the decoder's inverse */
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            const u8 *p = rgb + ((h - 1 - y) * w + x) * 3;
            double l = 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2];
            int li = (int)(l + 0.5);
            Y[y * w + x] = (u8)(li < 0 ? 0 : li > 255 ? 255 : li);
        }
    for (int y = 0; y < hh; y++)
        for (int x = 0; x < half; x++) {
            double r = 0, g = 0, bl = 0;
            for (int dy = 0; dy < 2; dy++)
                for (int dx = 0; dx < 2; dx++) {
                    const u8 *p = rgb + ((h - 1 - (2 * y + dy)) * w + 2 * x + dx) * 3;
                    r += p[0], g += p[1], bl += p[2];
                }
            r /= 4, g /= 4, bl /= 4;
            double l = 0.299 * r + 0.587 * g + 0.114 * bl;
            double u = (bl - l) * 256.0 / 454.0 + 128, v = (r - l) * 256.0 / 359.0 + 128;
            int ui = (int)(u + 0.5), vi = (int)(v + 0.5);
            U[y * half + x] = (u8)(ui < 0 ? 0 : ui > 255 ? 255 : ui);
            V[y * half + x] = (u8)(vi < 0 ? 0 : vi > 255 ? 255 : vi);
        }
    int ql[64], qc[64];
    plain_table(LUMA, quality, ql);
    plain_table(CHROMA, quality, qc);
    int typesize = (nblocks + 3) / 4;
    u8 *types = (u8 *)calloc(typesize + 1, 1);
    s16 *row = (s16 *)malloc(sizeof(s16) * mbw * 6 * 64);
    BitW bw = {0};
    int bcap = cap > 0 ? cap : 0;
    u8 *bits = (u8 *)malloc(w * h * 4 + 1024);
    bw.p = bits, bw.cap = w * h * 4 + 1024;
    int block = 0;
    for (int my = 0; my < mbh; my++) {
        int n = 0, prev[3] = {0, 0, 0};
        for (int mx = 0; mx < mbw; mx++) {
            const u8 *src[6] = {Y + my * 16 * w + mx * 16, Y + my * 16 * w + mx * 16 + 8, Y + (my * 16 + 8) * w + mx * 16,
                                Y + (my * 16 + 8) * w + mx * 16 + 8, U + my * 8 * half + mx * 8, V + my * 8 * half + mx * 8};
            int wid[6] = {w, w, w, w, half, half};
            for (int k = 0; k < 6; k++) {
                int c[64], ch = k < 4 ? 0 : k - 3;
                block_coefs(src[k], wid[k], k < 4 ? ql : qc, c);
                int last = 0, nz = 0;
                for (int i = 0; i < 64; i++)
                    if (c[i]) nz = 1, last = i;
                int type;
                if (!nz)
                    type = 0;
                else if (last == 0)
                    type = 1;
                else {
                    int only4 = 1;
                    for (int i = 0; i < 64; i++)
                        if (c[i] && i != 0 && i != 1 && i != 8 && i != 9) only4 = 0;
                    type = only4 ? 2 : 3;
                }
                types[block / 4] |= (u8)(type << ((block & 3) * 2));
                block++;
                if (type == 0) continue;
                int dc = c[0] - prev[ch];
                /* the code holds no larger difference: this DC goes as near as it can, and the next counts from there */
                if (dc > 2047) dc = 2047;
                if (dc < -2047) dc = -2047;
                prev[ch] += dc;
                if (type == 1) {
                    row[n++] = (s16)dc;
                } else if (type == 2) {
                    row[n++] = (s16)dc, row[n++] = (s16)c[1], row[n++] = (s16)c[8], row[n++] = (s16)c[9];
                } else {
                    s16 z[64];
                    for (int i = 0; i < 64; i++) z[ZIGZAG[i]] = (s16)c[i];
                    z[0] = (s16)dc;
                    memcpy(row + n, z, sizeof z);
                    n += 64;
                }
            }
        }
        put(&bw, (u32)n, 16);
        put_values(&bw, row, n);
    }
    while (bw.n) put(&bw, 0, 1);
    for (int i = 0; i < 4; i++) put(&bw, 0, 8);     /* the reader fills ahead */
    int total = 4 + 2 + typesize + bw.len;
    int ret = total;
    if (total > bcap || bw.overflow) {
        ret = -total;
    } else {
        out[0] = (u8)quality, out[1] = 0, out[2] = 0, out[3] = 0;
        s16 ts = (s16)typesize;
        memcpy(out + 4, &ts, 2);
        memcpy(out + 6, types, typesize);
        memcpy(out + 6 + typesize, bits, bw.len);
    }
    free(Y), free(U), free(V), free(types), free(row), free(bits);
    return ret;
}

/* ---- PS2 SPU ADPCM ---------------------------------------------------------------------------------------------------- */
static const int COEF[5][2] = {{0, 0}, {60, 0}, {115, -52}, {98, -55}, {122, -60}};

/* frames of 16 bytes -> 28 samples each; hist: two ints carried between calls. Answers the samples written. */
EXPORT int adpcm_decode(const u8 *in, int frames, s16 *out, int *hist)
{
    int h1 = hist[0], h2 = hist[1], n = 0;
    for (int f = 0; f < frames; f++) {
        const u8 *p = in + f * 16;
        int shift = p[0] & 15, pred = p[0] >> 4;
        if (pred > 4) pred = 0;
        int f0 = COEF[pred][0], f1 = COEF[pred][1];
        for (int j = 0; j < 14; j++) {
            int byte = p[2 + j];
            for (int s = 0; s < 2; s++) {
                int nib = s ? byte >> 4 : byte & 15;
                int v = (s16)(nib << 12);
                int x = (v >> shift) + ((f0 * h1 + f1 * h2 + 32) >> 6);
                if (x > 32767) x = 32767;
                if (x < -32768) x = -32768;
                h2 = h1, h1 = x;
                out[n++] = (s16)x;
            }
        }
    }
    hist[0] = h1, hist[1] = h2;
    return n;
}

/* samples (a multiple of 28) -> frames of 16 bytes, the best filter and shift for each by trying them all; flags byte 0
 * (a stream) unless loop_flags. hist as in decode. Answers the frames written. */
EXPORT int adpcm_encode(const s16 *in, int samples, u8 *out, int *hist)
{
    int h1 = hist[0], h2 = hist[1];
    int frames = samples / 28;
    for (int f = 0; f < frames; f++) {
        const s16 *s = in + f * 28;
        long long best = -1;
        u8 bestf[16];
        int bh1 = 0, bh2 = 0;
        for (int pred = 0; pred < 5; pred++)
            for (int shift = 0; shift <= 12; shift++) {
                int a = h1, b = h2;
                long long err = 0;
                u8 fr[16] = {0};
                fr[0] = (u8)((pred << 4) | shift);
                for (int i = 0; i < 28; i++) {
                    int p = (COEF[pred][0] * a + COEF[pred][1] * b + 32) >> 6;
                    int d = s[i] - p;
                    /* the nibble whose decode comes nearest */
                    int q;
                    int scale = 1 << (12 - shift);
                    q = d >= 0 ? (d + scale / 2) / scale : -((-d + scale / 2) / scale);
                    if (q > 7) q = 7;
                    if (q < -8) q = -8;
                    int v = (s16)((q & 15) << 12);
                    int x = (v >> shift) + p;
                    if (x > 32767) x = 32767;
                    if (x < -32768) x = -32768;
                    long long e = (long long)(s[i] - x);
                    err += e * e;
                    b = a, a = x;
                    fr[2 + i / 2] |= (u8)((q & 15) << ((i & 1) * 4));
                    if (best >= 0 && err >= best) break;
                }
                if (best < 0 || err < best) {
                    best = err;
                    memcpy(bestf, fr, 16);
                    bh1 = a, bh2 = b;
                }
            }
        memcpy(out + f * 16, bestf, 16);
        h1 = bh1, h2 = bh2;
    }
    hist[0] = h1, hist[1] = h2;
    return frames;
}

/* ---- JDLZ, the PC games' compression ("JDLZ", 0x02, 0x10, u16, u32 unpacked size, u32 packed size, then two flag
 * streams: a 1 in the first is a match, whose kind the second gives; NFS-ModTools' CompLib) ---------------------------- */
EXPORT int jdlz_decompress(const u8 *in, int inlen, u8 *out, int outlen)
{
    if (inlen < 16 || memcmp(in, "JDLZ", 4) != 0) return -1;
    int flags1 = 1, flags2 = 1, ip = 16, op = 0;
    while (ip < inlen && op < outlen) {
        if (flags1 == 1) {
            if (ip >= inlen) break;
            flags1 = in[ip++] | 0x100;
        }
        if (flags2 == 1) {
            if (ip >= inlen) break;
            flags2 = in[ip++] | 0x100;
        }
        if (flags1 & 1) {
            if (ip + 1 >= inlen) break;
            int length, dist;
            if (flags2 & 1) {
                length = (in[ip + 1] | ((in[ip] & 0xF0) << 4)) + 3;
                dist = (in[ip] & 0x0F) + 1;
            } else {
                dist = (in[ip + 1] | ((in[ip] & 0xE0) << 3)) + 17;
                length = (in[ip] & 0x1F) + 3;
            }
            ip += 2;
            if (dist > op) return -2;
            for (int i = 0; i < length && op < outlen; i++, op++) out[op] = out[op - dist];
            flags2 >>= 1;
        } else {
            out[op++] = in[ip++];
        }
        flags1 >>= 1;
    }
    return op;
}
