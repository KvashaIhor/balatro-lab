/*
 * rainbow.c -- measures what a precomputed seed table (a rainbow table) would cost, on a scaled-down
 * seed space, so the full-size numbers can be extrapolated from measurements instead of guessed.
 *
 * The function inverted is observe(seed): everything the opening shows that we model exactly -- the
 * first hand (as a set), the boss, the voucher and both skip tags -- hashed to 64 bits.  A rainbow table
 * stores chains seed -> observe -> reduce -> seed -> ... of length T, keeping only each chain's start and
 * end; a lookup rebuilds candidate chain ends from the observed key (T^2/2 evaluations) and replays the
 * matching chain from its start.  Success rate, lookup cost and storage depend on N, T and chains/N, so a
 * small N with the same ratios predicts the full N.
 *
 * Build:  cc -O3 -mcpu=native -ffp-contract=off -o rainbow rainbow.c -lpthread -lm
 * Modes:  ./rainbow bench SECONDS LOG                      observe() speed, one thread, random seeds
 *         ./rainbow test LOG K T CHAINS_PER_N TABLES QUERIES THREADS
 *              K free seed characters (N = 34^K; the other 8-K characters fixed), chain length T,
 *              chains per table = CHAINS_PER_N * N / T
 */
#define FASTCHECK_NO_MAIN
#include "fastcheck.c"

#define BLOCK 256   /* seeds per block (see observe_block) */
#define TAG_RS 30   /* tag reroll streams kept per seed */

static inline uint64_t mix64(uint64_t z) {
    z += 0x9E3779B97F4A7C15ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* ---- the (scaled) seed space ---------------------------------------------------------------- */
static uint64_t N;
static int K;
static const char TAIL[] = "Q7MZK2XA";   /* fixed characters K..7 */

static inline void seed_of(uint64_t idx, char s[9]) {
    for (int i = 0; i < 8; i++) s[i] = TAIL[i];
    for (int i = 0; i < K; i++) { s[i] = ALPHA34[idx % 34]; idx /= 34; }
    s[8] = 0;
}
/* ---- the observed opening, as one 64-bit key -------------------------------------------------- */
/* pseudohash(key .. seed) without building the string: the walk goes from the last character back. */
static inline double ph_key_seed(const char *key, int klen, const char *s) {
    double num = 1.0;
    for (int i = 8; i >= 1; i--) num = ph_step(num, (unsigned char)s[i - 1], klen + i);
    for (int i = klen; i >= 1; i--) num = ph_step(num, (unsigned char)key[i - 1], i);
    return num;
}

/* Resample keys "Voucher1_resample<it>" / "Tag1_resample<it>", built once (the game goes up to 1000 / 64). */
#define MAX_RS 1000
static char RS_V[MAX_RS][24], RS_T[64][24];
static int RS_VLEN[MAX_RS], RS_TLEN[64];
static void resample_keys_init(void) {
    for (int it = 2; it < MAX_RS; it++) RS_VLEN[it] = snprintf(RS_V[it], 24, "Voucher1_resample%d", it);
    for (int it = 2; it < 64; it++) RS_TLEN[it] = snprintf(RS_T[it], 24, "Tag1_resample%d", it);
}

static int voucher_fast(double hashed, const char *s) {
    double st;
    tw_t t;
    int v = (int)floor(tw_seed_first(&t, pseudoseed_first(ph_key_seed("Voucher1", 8, s), hashed, &st)) * 32.0);
    for (int it = 2; (v & 1) && it < MAX_RS; it++)
        v = (int)floor(tw_seed_first(&t, pseudoseed_first(ph_key_seed(RS_V[it], RS_VLEN[it], s), hashed, &st)) * 32.0);
    return v;
}

static void tags_fast(double hashed, const char *s, int out[2]) {
    double st_main, st_rs[64];
    uint64_t have_rs = 0;
    tw_t t;
    for (int which = 0; which < 2; which++) {
        double p = which ? pseudoseed_next(&st_main, hashed) : pseudoseed_first(ph_key_seed("Tag1", 4, s), hashed, &st_main);
        int tag = (int)floor(tw_seed_first(&t, p) * 24.0);
        for (int it = 2; !TAG_AVAILABLE_ANTE1[tag] && it < 64; it++) {
            double q = (have_rs >> it & 1) ? pseudoseed_next(&st_rs[it], hashed)
                                           : pseudoseed_first(ph_key_seed(RS_T[it], RS_TLEN[it], s), hashed, &st_rs[it]);
            have_rs |= 1ull << it;
            tag = (int)floor(tw_seed_first(&t, q) * 24.0);
        }
        out[which] = tag;
    }
}

static uint64_t observe(const char *s) {
    double hashed = pseudohash_str(s, 8), st;
    int cards[8];
    hand_check(pseudoseed_first(ph_key_seed("nr1", 3, s), hashed, &st), 0, cards);
    uint64_t mask = 0;
    for (int k = 0; k < 8; k++) mask |= 1ull << cards[k];
    int boss = boss_index(pseudoseed_first(ph_key_seed("boss", 4, s), hashed, &st));
    int v = voucher_fast(hashed, s), tg[2];
    tags_fast(hashed, s, tg);
    return mix64(mask) ^ mix64(((uint64_t)boss << 24) | ((uint64_t)v << 16) | ((uint64_t)tg[0] << 8) | (uint64_t)tg[1]);
}

/* ---- lockstep: LANES seeds at once ----------------------------------------------------------------
 * Every hash step waits for the previous one (a division each), so one seed leaves the core mostly
 * idle.  Advancing LANES independent seeds one step at a time lets those waits overlap (and lets the
 * compiler use 2-wide vector divides).  Same operations in the same order per seed: bit-identical. */
#define LANES 8
static const char *const KEYS[4] = {"nr1", "boss", "Voucher1", "Tag1"};
static const int KLEN[4] = {3, 4, 8, 4};

/* pseudohash(key .. seed) for n seeds (chars as doubles, seed-major), in lockstep */
static inline void ph_lanes(const char *key, int klen, const double (*c)[8], int n, double *num) {
    for (int j = 0; j < n; j++) num[j] = 1.0;
    for (int i = 8; i >= 1; i--) {
        const double pp = LJ_PI * (double)(klen + i);
        for (int j = 0; j < n; j++) {
            double q = (1.1239285023 / num[j]) * c[j][i - 1] * LJ_PI + pp;
            num[j] = q - floor(q);
        }
    }
    for (int i = klen; i >= 1; i--) {
        const double cc = (double)(unsigned char)key[i - 1], pp = LJ_PI * (double)i;
        for (int j = 0; j < n; j++) {
            double q = (1.1239285023 / num[j]) * cc * LJ_PI + pp;
            num[j] = q - floor(q);
        }
    }
}

static void observe_batch(const uint64_t *idx, uint64_t *out) {
    char s[LANES][9];
    double c[LANES][8], hashed[LANES], kh[4][LANES], st[LANES];
    for (int l = 0; l < LANES; l++) {
        seed_of(idx[l], s[l]);
        for (int i = 0; i < 8; i++) c[l][i] = (double)(unsigned char)s[l][i];
    }
    for (int l = 0; l < LANES; l++) hashed[l] = 1.0;
    for (int i = 8; i >= 1; i--) {
        const double pp = LJ_PI * (double)i;
        for (int l = 0; l < LANES; l++) {
            double q = (1.1239285023 / hashed[l]) * c[l][i - 1] * LJ_PI + pp;
            hashed[l] = q - floor(q);
        }
    }
    for (int k = 0; k < 4; k++) ph_lanes(KEYS[k], KLEN[k], (const double (*)[8])c, LANES, kh[k]);

    uint64_t mask[LANES];
    int boss[LANES], v[LANES], tg[LANES][2];
    tw_t t;
    for (int l = 0; l < LANES; l++) {               /* hand: all 8 cards */
        int cards[8];
        hand_check(pseudoseed_first(kh[0][l], hashed[l], &st[l]), 0, cards);
        mask[l] = 0;
        for (int k = 0; k < 8; k++) mask[l] |= 1ull << cards[k];
    }
    for (int l = 0; l < LANES; l++)
        boss[l] = (int)floor(tw_seed_first(&t, pseudoseed_first(kh[1][l], hashed[l], &st[l])) * 8.0);

    /* voucher, with resamples done in lockstep for the seeds that need them */
    int need[LANES], n = 0;
    for (int l = 0; l < LANES; l++) {
        v[l] = (int)floor(tw_seed_first(&t, pseudoseed_first(kh[2][l], hashed[l], &st[l])) * 32.0);
        if (v[l] & 1) need[n++] = l;
    }
    for (int it = 2; n && it < MAX_RS; it++) {
        double cc[LANES][8], h[LANES];
        for (int j = 0; j < n; j++) memcpy(cc[j], c[need[j]], sizeof cc[j]);
        ph_lanes(RS_V[it], RS_VLEN[it], (const double (*)[8])cc, n, h);
        int m = 0;
        for (int j = 0; j < n; j++) {
            int l = need[j];
            v[l] = (int)floor(tw_seed_first(&t, pseudoseed_first(h[j], hashed[l], &st[l])) * 32.0);
            if (v[l] & 1) need[m++] = l;
        }
        n = m;
    }

    /* tags: two draws from "Tag1"; an unavailable tag resamples with "Tag1_resample<it>", whose streams
     * carry over from the first draw to the second */
    double st_main[LANES], st_rs[LANES][64];
    uint64_t have_rs[LANES];
    int tag[LANES];
    for (int which = 0; which < 2; which++) {
        n = 0;
        for (int l = 0; l < LANES; l++) {
            if (!which) have_rs[l] = 0;
            double p = which ? pseudoseed_next(&st_main[l], hashed[l]) : pseudoseed_first(kh[3][l], hashed[l], &st_main[l]);
            tag[l] = (int)floor(tw_seed_first(&t, p) * 24.0);
            if (!TAG_AVAILABLE_ANTE1[tag[l]]) need[n++] = l;
        }
        for (int it = 2; n && it < 64; it++) {
            int fresh[LANES], nf = 0;                 /* seeds whose stream <it> hasn't been started */
            for (int j = 0; j < n; j++) if (!(have_rs[need[j]] >> it & 1)) fresh[nf++] = need[j];
            double h[LANES];
            if (nf) {
                double cc[LANES][8];
                for (int j = 0; j < nf; j++) memcpy(cc[j], c[fresh[j]], sizeof cc[j]);
                ph_lanes(RS_T[it], RS_TLEN[it], (const double (*)[8])cc, nf, h);
            }
            int m = 0, fi = 0;
            for (int j = 0; j < n; j++) {
                int l = need[j];
                double q = (have_rs[l] >> it & 1) ? pseudoseed_next(&st_rs[l][it], hashed[l])
                                                   : pseudoseed_first(h[fi++], hashed[l], &st_rs[l][it]);
                have_rs[l] |= 1ull << it;
                tag[l] = (int)floor(tw_seed_first(&t, q) * 24.0);
                if (!TAG_AVAILABLE_ANTE1[tag[l]]) need[m++] = l;
            }
            n = m;
        }
        for (int l = 0; l < LANES; l++) tg[l][which] = tag[l];
    }
    for (int l = 0; l < LANES; l++)
        out[l] = mix64(mask[l]) ^ mix64(((uint64_t)boss[l] << 24) | ((uint64_t)v[l] << 16) | ((uint64_t)tg[l][0] << 8) | (uint64_t)tg[l][1]);
}

/* pseudoseed_first + tw_seed_first for n seeds at once: the floating-point parts run as plain loops the
 * compiler vectorizes; the table lookups stay scalar.  Same operations per seed: bit-identical. */
static void seed_first_n(const double *keyhash, const double *hashed, int n, double *state, double *first, tw_t *tws) {
    double d[BLOCK];
    for (int j = 0; j < n; j++) {                       /* round13(fract(2.134453429141 + kh * 1.72431234)) */
        double x = 2.134453429141 + keyhash[j] * 1.72431234;
        x = x - floor(x);
        double y = x * 1e13, e = fma(x, 1e13, -y), r = nearbyint(y), tt = y - r;
        r = (tt == 0.5 && e > 0) ? r + 1.0 : (tt == -0.5 && e < 0) ? r - 1.0 : r;
        double st = fabs(r / 1e13);
        st = (x != x) ? x : st;
        state[j] = st;
        d[j] = (st + hashed[j]) / 2.0;
    }
    uint64_t u[4][BLOCK];
    static const uint64_t M[4] = {1ull << 1, 1ull << 6, 1ull << 9, 1ull << 17};
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < n; j++) {
            double x = d[j];
            uint64_t bits;
            if (x != x) bits = 0xFFF8000000000000ull;
            else { x = x * LJ_PI; x = x + LJ_E; memcpy(&bits, &x, 8); d[j] = x; }
            u[i][j] = bits < M[i] ? bits + M[i] : bits;
        }
    for (int j = 0; j < n; j++) {
        tw_t *t = &tws[j];
        t->s0 = jump11(0, u[0][j]); t->s1 = jump11(1, u[1][j]); t->s2 = jump11(2, u[2][j]); t->s3 = jump11(3, u[3][j]);
        uint64_t o = ((t->s0 ^ t->s1 ^ t->s2 ^ t->s3) & 0x000FFFFFFFFFFFFFull) | 0x3FF0000000000000ull;
        double x;
        memcpy(&x, &o, 8);
        first[j] = x - 1.0;
    }
}

/* the 8 cards of the first hand, given the shuffle's first draw and the generator state after it */
static inline void hand_from(double first, tw_t *t, int *out) {
    int ov_pos[8], ov_card[8], nov = 0;
    for (int i = 52; i >= 45; i--) {
        int j = i == 52 ? (int)floor(first * 52.0) : tw_index(t, i);
        int ci = i - 1, cj = j;
        for (int k = 0; k < nov; k++) {
            if (ov_pos[k] == i - 1) ci = ov_card[k];
            if (ov_pos[k] == j) cj = ov_card[k];
        }
        int found = 0;
        for (int k = 0; k < nov; k++) if (ov_pos[k] == j) { ov_card[k] = ci; found = 1; }
        if (!found) { ov_pos[nov] = j; ov_card[nov] = ci; nov++; }
        out[52 - i] = cj;
    }
}

/* ---- blocks: BLOCK seeds at once, rerolls pooled across the block --------------------------------
 * Voucher and tag rerolls ("Voucher1_resample<it>", "Tag1_resample<it>") cost most of the time, and only
 * some seeds need each one; pooling them across a block keeps every lockstep group full.  Keys 2..9 share a
 * length, so the seed half of their hash is the same and is computed once in the main pass. Seeds that
 * need 10+ voucher rerolls or 30+ tag streams (vanishingly rare) are redone with the exact scalar code. */

/* continue a hash from its seed part through the key characters, for a group of seeds */
static inline void ph_finish(const char *key, int klen, const double *part, int n, double *num) {
    for (int j = 0; j < n; j++) num[j] = part[j];
    for (int i = klen; i >= 1; i--) {
        const double cc = (double)(unsigned char)key[i - 1], pp = LJ_PI * (double)i;
        for (int j = 0; j < n; j++) {
            double q = (1.1239285023 / num[j]) * cc * LJ_PI + pp;
            num[j] = q - floor(q);
        }
    }
}

/* seed part of a hash (seed characters at positions klen+8 .. klen+1), for a group of seeds */
static inline void ph_seed_part(int klen, const double (*c)[8], int n, double *num) {
    for (int j = 0; j < n; j++) num[j] = 1.0;
    for (int i = 8; i >= 1; i--) {
        const double pp = LJ_PI * (double)(klen + i);
        for (int j = 0; j < n; j++) {
            double q = (1.1239285023 / num[j]) * c[j][i - 1] * LJ_PI + pp;
            num[j] = q - floor(q);
        }
    }
}

typedef struct {
    double c[BLOCK][8], hashed[BLOCK], kh[4][BLOCK], vpart[BLOCK], tpart[BLOCK];
    double st_main[BLOCK], st_rs[BLOCK][TAG_RS];
    uint32_t have_rs[BLOCK];
    int v[BLOCK], tag[BLOCK][2], deep[BLOCK];
} block_t;

/* hash the given seeds (indexes into the block) with key KEY (length klen, all sharing `part`) */
static void finish_group(block_t *b, const int *list, int n, const char *key, int klen, const double *part_of, double *out) {
    for (int g = 0; g < n; g += LANES) {
        int m = n - g < LANES ? n - g : LANES;
        double part[LANES];
        for (int j = 0; j < m; j++) part[j] = part_of[list[g + j]];
        ph_finish(key, klen, part, m, out + g);
    }
}

static void observe_block(const uint64_t *idx, int count, uint64_t *out) {
    static __thread block_t *b;
    if (!b) b = malloc(sizeof *b);
    char sd[9];
    for (int l = 0; l < count; l++) {
        seed_of(idx[l], sd);
        for (int i = 0; i < 8; i++) b->c[l][i] = (double)(unsigned char)sd[i];
    }
    for (int g = 0; g < count; g += LANES) {
        const double (*c)[8] = (const double (*)[8])b->c[g];
        ph_seed_part(0, c, LANES, b->hashed + g);
        for (int k = 0; k < 4; k++) ph_lanes(KEYS[k], KLEN[k], c, LANES, b->kh[k] + g);
        ph_seed_part(18, c, LANES, b->vpart + g);   /* "Voucher1_resample2".."9" */
        ph_seed_part(14, c, LANES, b->tpart + g);   /* "Tag1_resample2".."9" */
    }
    tw_t t;
    static __thread tw_t *tws;
    if (!tws) tws = malloc(BLOCK * sizeof *tws);
    double st, sts[BLOCK], first[BLOCK];
    uint64_t mask[BLOCK];
    int boss[BLOCK], list[BLOCK], n = 0;
    seed_first_n(b->kh[0], b->hashed, count, sts, first, tws);        /* "nr1": the deck shuffle */
    for (int l = 0; l < count; l++) {
        int cards[8];
        hand_from(first[l], &tws[l], cards);
        mask[l] = 0;
        for (int k = 0; k < 8; k++) mask[l] |= 1ull << cards[k];
    }
    seed_first_n(b->kh[1], b->hashed, count, sts, first, tws);        /* "boss" */
    for (int l = 0; l < count; l++) boss[l] = (int)floor(first[l] * 8.0);
    seed_first_n(b->kh[2], b->hashed, count, sts, first, tws);        /* "Voucher1" */
    for (int l = 0; l < count; l++) {
        b->v[l] = (int)floor(first[l] * 32.0);
        b->deep[l] = 0;
        if (b->v[l] & 1) list[n++] = l;
    }
    seed_first_n(b->kh[3], b->hashed, count, b->st_main, first, tws);   /* "Tag1", first draw */
    /* voucher rerolls 2..9, pooled */
    double h[BLOCK];
    for (int it = 2; n && it < 10; it++) {
        finish_group(b, list, n, RS_V[it], RS_VLEN[it], b->vpart, h);
        int m = 0;
        for (int j = 0; j < n; j++) {
            int l = list[j];
            b->v[l] = (int)floor(tw_seed_first(&t, pseudoseed_first(h[j], b->hashed[l], &st)) * 32.0);
            if (b->v[l] & 1) list[m++] = l;
        }
        n = m;
    }
    for (int j = 0; j < n; j++) b->deep[list[j]] = 1;   /* still odd after 9: redo exactly below */

    /* tags: two draws from "Tag1"; rerolls use streams "Tag1_resample<it>" that carry over between draws */
    for (int which = 0; which < 2; which++) {
        n = 0;
        for (int l = 0; l < count; l++) {
            if (!which) b->have_rs[l] = 0;
            b->tag[l][which] = which ? (int)floor(tw_seed_first(&t, pseudoseed_next(&b->st_main[l], b->hashed[l])) * 24.0)
                                     : (int)floor(first[l] * 24.0);
            if (!TAG_AVAILABLE_ANTE1[b->tag[l][which]] && !b->deep[l]) list[n++] = l;
        }
        for (int it = 2; n && it < TAG_RS; it++) {
            int fresh[BLOCK], nf = 0;
            for (int j = 0; j < n; j++) if (!(b->have_rs[list[j]] >> it & 1)) fresh[nf++] = list[j];
            if (it >= 10) {                                   /* rare: redone exactly below */
                for (int j = 0; j < n; j++) b->deep[list[j]] = 1;
                break;
            }
            finish_group(b, fresh, nf, RS_T[it], RS_TLEN[it], b->tpart, h);
            int m = 0, fi = 0;
            for (int j = 0; j < n; j++) {
                int l = list[j];
                double q = (b->have_rs[l] >> it & 1) ? pseudoseed_next(&b->st_rs[l][it], b->hashed[l])
                                                      : pseudoseed_first(h[fi++], b->hashed[l], &b->st_rs[l][it]);
                b->have_rs[l] |= 1u << it;
                int tg = (int)floor(tw_seed_first(&t, q) * 24.0);
                b->tag[l][which] = tg;
                if (!TAG_AVAILABLE_ANTE1[tg]) list[m++] = l;
            }
            n = m;
        }
    }
    for (int l = 0; l < count; l++) {
        if (b->deep[l]) {                                  /* rare: the exact scalar path */
            seed_of(idx[l], sd);
            b->v[l] = voucher_fast(b->hashed[l], sd);
            tags_fast(b->hashed[l], sd, b->tag[l]);
        }
        out[l] = mix64(mask[l]) ^ mix64(((uint64_t)boss[l] << 24) | ((uint64_t)b->v[l] << 16) |
                                        ((uint64_t)b->tag[l][0] << 8) | (uint64_t)b->tag[l][1]);
    }
}

/* the slow, already cross-checked path, to prove observe() equal to it */
static uint64_t observe_ref(const char *s) {
    double hashed = pseudohash_str(s, 8), st;
    char buf[32];
    int n = snprintf(buf, sizeof buf, "nr1%s", s), cards[8];
    hand_check(pseudoseed_first(pseudohash_str(buf, n), hashed, &st), 0, cards);
    uint64_t mask = 0;
    for (int k = 0; k < 8; k++) mask |= 1ull << cards[k];
    n = snprintf(buf, sizeof buf, "boss%s", s);
    int boss = boss_index(pseudoseed_first(pseudohash_str(buf, n), hashed, &st));
    n = snprintf(buf, sizeof buf, "Voucher1%s", s);
    int v = voucher_index(pseudohash_str(buf, n), hashed, s);
    n = snprintf(buf, sizeof buf, "Tag1%s", s);
    int tg[2];
    tags_ante1(pseudohash_str(buf, n), hashed, s, tg);
    return mix64(mask) ^ mix64(((uint64_t)boss << 24) | ((uint64_t)v << 16) | ((uint64_t)tg[0] << 8) | (uint64_t)tg[1]);
}

static inline uint64_t f_idx(uint64_t idx) { char s[9]; seed_of(idx, s); return observe(s); }
static inline uint64_t reduce(uint64_t key, int col, int table) {
    return mix64(key ^ ((uint64_t)col << 40) ^ ((uint64_t)table * 0xD1B54A32D192ED03ull)) % N;
}

/* ---- tables ------------------------------------------------------------------------------------ */
typedef struct { uint64_t end, start; } chain_t;
typedef struct { chain_t *c; long m; int table; } rtable_t;
static int T;
static atomic_llong EVALS;

typedef struct { rtable_t *tb; long from, to; } build_job_t;
static void *build_worker(void *arg) {
    build_job_t *j = arg;
    long long ev = 0;
    for (long i = j->from; i < j->to; i++) {
        uint64_t x = mix64((uint64_t)i * 2654435761u + (uint64_t)j->tb->table * 977) % N, s0 = x;
        for (int col = 0; col < T; col++) x = reduce(f_idx(x), col, j->tb->table);
        ev += T;
        j->tb->c[i].start = s0;
        j->tb->c[i].end = x;
    }
    atomic_fetch_add(&EVALS, ev);
    return NULL;
}
static int by_end(const void *a, const void *b) {
    uint64_t x = ((const chain_t *)a)->end, y = ((const chain_t *)b)->end;
    return x < y ? -1 : x > y;
}

/* Returns 1 and the seed if found; counts evaluations and false alarms. */
static int lookup(rtable_t *tables, int ntab, uint64_t key, uint64_t *found, long long *evals, long long *alarms) {
    for (int ti = 0; ti < ntab; ti++) {
        rtable_t *tb = &tables[ti];
        for (int pos = T - 1; pos >= 0; pos--) {
            uint64_t x = reduce(key, pos, tb->table);
            for (int col = pos + 1; col < T; col++) { x = reduce(f_idx(x), col, tb->table); (*evals)++; }
            long lo = 0, hi = tb->m;           /* first chain with end >= x */
            while (lo < hi) { long mid = (lo + hi) / 2; if (tb->c[mid].end < x) lo = mid + 1; else hi = mid; }
            for (long i = lo; i < tb->m && tb->c[i].end == x; i++) {
                uint64_t y = tb->c[i].start;
                for (int col = 0; col < pos; col++) { y = reduce(f_idx(y), col, tb->table); (*evals)++; }
                (*evals)++;
                if (f_idx(y) == key) { *found = y; return 1; }
                (*alarms)++;
            }
        }
    }
    return 0;
}

typedef struct { rtable_t *tables; int ntab; long from, to; long long ok, evals, alarms; } query_job_t;
static void *query_worker(void *arg) {
    query_job_t *q = arg;
    for (long i = q->from; i < q->to; i++) {
        uint64_t target = mix64(0xC0FFEE + (uint64_t)i) % N, found;
        uint64_t key = f_idx(target);
        q->ok += lookup(q->tables, q->ntab, key, &found, &q->evals, &q->alarms);
    }
    return NULL;
}

static double theory(double n, double m, int t) {
    double miss = 1.0, mi = m;
    for (int i = 0; i < t; i++) { miss *= 1.0 - mi / n; mi = n * (1.0 - exp(-mi / n)); }
    return 1.0 - miss;
}

static int test(int argc, char **argv) {
    if (argc < 7) { fprintf(stderr, "test: LOG K T CHAINS_PER_N TABLES QUERIES THREADS\n"); return 2; }
    LOGF = fopen(argv[0], "a");
    K = atoi(argv[1]); T = atoi(argv[2]);
    double cpn = atof(argv[3]);
    int ntab = atoi(argv[4]);
    long queries = atol(argv[5]);
    int threads = atoi(argv[6]);
    N = 1; for (int i = 0; i < K; i++) N *= 34;
    long m = (long)(cpn * (double)N / T);
    logf_("test start: N = 34^%d = %llu, T = %d, chains/table = %ld (m*T/N = %.2f), tables %d, queries %ld, threads %d",
          K, (unsigned long long)N, T, m, (double)m * T / N, ntab, queries, threads);
    rtable_t *tables = calloc(ntab, sizeof *tables);
    double tb0 = now_s();
    for (int ti = 0; ti < ntab; ti++) {
        tables[ti] = (rtable_t){calloc(m, sizeof(chain_t)), m, ti};
        pthread_t th[64]; build_job_t jobs[64];
        for (int k = 0; k < threads; k++) {
            jobs[k] = (build_job_t){&tables[ti], m * k / threads, m * (k + 1) / threads};
            pthread_create(&th[k], NULL, build_worker, &jobs[k]);
        }
        for (int k = 0; k < threads; k++) pthread_join(th[k], NULL);
        qsort(tables[ti].c, m, sizeof(chain_t), by_end);
        /* every chain is kept: two chains with the same end merged somewhere, but each covered other seeds
         * before that (dropping duplicates halves storage and loses about a quarter of the coverage) */
        long u = 0;
        for (long i = 0; i < m; i++) if (!u || tables[ti].c[i].end != tables[ti].c[i - 1].end) u++;
        logf_("table %d built: %ld chains, %ld distinct ends (%.1f%%), %.1fs so far", ti, m, u, 100.0 * u / m, now_s() - tb0);
    }
    double build_s = now_s() - tb0;
    long long build_evals = atomic_load(&EVALS);
    logf_("build: %lld evaluations in %.1fs = %.2f M/s on %d threads", build_evals, build_s, build_evals / build_s / 1e6, threads);

    double tq0 = now_s();
    pthread_t th[64]; query_job_t q[64];
    for (int k = 0; k < threads; k++) {
        q[k] = (query_job_t){tables, ntab, queries * k / threads, queries * (k + 1) / threads, 0, 0, 0};
        pthread_create(&th[k], NULL, query_worker, &q[k]);
    }
    long long ok = 0, ev = 0, al = 0;
    for (int k = 0; k < threads; k++) { pthread_join(th[k], NULL); ok += q[k].ok; ev += q[k].evals; al += q[k].alarms; }
    double q_s = now_s() - tq0;
    double th1 = theory((double)N, (double)m, T), thn = 1.0 - pow(1.0 - th1, ntab);
    long distinct = 0;
    for (int ti = 0; ti < ntab; ti++) distinct += tables[ti].m;
    logf_("RESULT N=%llu T=%d m/table=%ld tables=%d: success %.1f%% (%lld/%ld; theory %.1f%% per table, %.1f%% all), "
          "evaluations per lookup %.0f (T^2/2 = %.0f per table), false alarms per lookup %.1f, %.3fs per lookup per thread, "
          "stored chains %ld = %.3f per seed",
          (unsigned long long)N, T, m, ntab, 100.0 * ok / queries, ok, queries, 100 * th1, 100 * thn,
          (double)ev / queries, (double)T * T / 2, (double)al / queries, q_s * threads / queries, distinct, (double)distinct / N);
    logf_("test end, exit 0");
    return 0;
}

/* where observe_batch's time goes: cumulative stages, ns per seed */
static void bench_stages(double secs) {
    uint64_t ids[LANES];
    volatile double sink = 0;
    const char *names[] = {"hash seed + 4 keys", "+ pseudoseeds and first draws", "+ 7 more hand cards", "full (voucher + tag rerolls)"};
    for (int stage = 0; stage < 4; stage++) {
        long long n = 0;
        double t0 = now_s(), t = t0;
        while (t - t0 < secs) {
            for (int r = 0; r < 256; r++) {
                for (int l = 0; l < LANES; l++) ids[l] = mix64((uint64_t)n++) % N;
                if (stage == 3) { uint64_t keys[LANES]; observe_batch(ids, keys); sink += (double)(keys[0] & 1); continue; }
                char sd[LANES][9];
                double c[LANES][8], hashed[LANES], kh[4][LANES], st;
                for (int l = 0; l < LANES; l++) { seed_of(ids[l], sd[l]); for (int i = 0; i < 8; i++) c[l][i] = (double)(unsigned char)sd[l][i]; }
                ph_lanes("", 0, (const double (*)[8])c, LANES, hashed);
                for (int k = 0; k < 4; k++) ph_lanes(KEYS[k], KLEN[k], (const double (*)[8])c, LANES, kh[k]);
                if (stage >= 1) {
                    tw_t tt;
                    for (int k = 0; k < 4; k++) for (int l = 0; l < LANES; l++) sink += tw_seed_first(&tt, pseudoseed_first(kh[k][l], hashed[l], &st));
                }
                if (stage >= 2) {
                    for (int l = 0; l < LANES; l++) { int cards[8]; hand_check(pseudoseed_first(kh[0][l], hashed[l], &st), 0, cards); sink += cards[7]; }
                }
                sink += hashed[0] + kh[3][LANES - 1];
            }
            t = now_s();
        }
        logf_("STAGE %-32s %6.0f ns per seed", names[stage], (t - t0) / n * 1e9);
    }
}

static int bench_observe(int argc, char **argv) {
    double secs = argc > 0 ? atof(argv[0]) : 5;
    LOGF = argc > 1 ? fopen(argv[1], "a") : NULL;
    K = 8; N = 1; for (int i = 0; i < 8; i++) N *= 34;
    long long n = 0;
    volatile uint64_t sink = 0;
    double t0 = now_s(), t = t0;
    while (t - t0 < secs) {
        for (int r = 0; r < 4096; r++) sink ^= f_idx(mix64((uint64_t)n++) % N);
        t = now_s();
    }
    logf_("RESULT observe (hand + boss + voucher + 2 tags) on random seeds: %.2f M/s single thread [sink %llu]",
          n / (t - t0) / 1e6, (unsigned long long)sink);
    long bad = 0;
    for (long i = 0; i < 200000; i++) {
        char s[9];
        seed_of(mix64(0xABCDEF + (uint64_t)i) % N, s);
        bad += observe(s) != observe_ref(s);
    }
    logf_("observe == reference on 200000 random seeds: %s (%ld differ)", bad ? "NO" : "yes", bad);

    uint64_t ids[LANES], keys[LANES];
    n = 0;
    t0 = now_s(); t = t0;
    while (t - t0 < secs) {
        for (int r = 0; r < 512; r++) {
            for (int l = 0; l < LANES; l++) ids[l] = mix64((uint64_t)n++) % N;
            observe_batch(ids, keys);
            sink ^= keys[0] ^ keys[LANES - 1];
        }
        t = now_s();
    }
    logf_("RESULT observe_batch (%d seeds in lockstep): %.2f M/s single thread [sink %llu]", LANES,
          n / (t - t0) / 1e6, (unsigned long long)sink);
    bad = 0;
    for (long i = 0; i < 200000; i += LANES) {
        for (int l = 0; l < LANES; l++) ids[l] = mix64(0xABCDEF + (uint64_t)(i + l)) % N;
        observe_batch(ids, keys);
        for (int l = 0; l < LANES; l++) { char s[9]; seed_of(ids[l], s); bad += keys[l] != observe_ref(s); }
    }
    logf_("observe_batch == reference on 200000 random seeds: %s (%ld differ)", bad ? "NO" : "yes", bad);

    uint64_t bid[BLOCK], bkey[BLOCK];
    n = 0;
    t0 = now_s(); t = t0;
    while (t - t0 < secs) {
        for (int r = 0; r < 32; r++) {
            for (int l = 0; l < BLOCK; l++) bid[l] = mix64((uint64_t)n++) % N;
            observe_block(bid, BLOCK, bkey);
            sink ^= bkey[0] ^ bkey[BLOCK - 1];
        }
        t = now_s();
    }
    logf_("RESULT observe_block (%d seeds, rerolls pooled): %.2f M/s single thread [sink %llu]", BLOCK,
          n / (t - t0) / 1e6, (unsigned long long)sink);
    bad = 0;
    for (long i = 0; i < 1000000; i += BLOCK) {
        for (int l = 0; l < BLOCK; l++) bid[l] = mix64(0x5EED + (uint64_t)(i + l)) % N;
        observe_block(bid, BLOCK, bkey);
        for (int l = 0; l < BLOCK; l++) { char sd[9]; seed_of(bid[l], sd); bad += bkey[l] != observe_ref(sd); }
    }
    logf_("observe_block == reference on 1000192 random seeds: %s (%ld differ)", bad ? "NO" : "yes", bad);
    return 0;
}

#ifndef RAINBOW_NO_MAIN
int main(int argc, char **argv) {
    T0 = now_s();
    jump_tables_init();
    resample_keys_init();
    if (argc >= 2 && !strcmp(argv[1], "bench")) return bench_observe(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "stages")) { K = 8; N = 1; for (int i = 0; i < 8; i++) N *= 34; bench_stages(2); return 0; }
    if (argc >= 2 && !strcmp(argv[1], "test")) return test(argc - 2, argv + 2);
    fprintf(stderr, "usage: %s bench SECONDS LOG | test LOG K T CHAINS_PER_N TABLES QUERIES THREADS\n", argv[0]);
    return 2;
}
#endif
