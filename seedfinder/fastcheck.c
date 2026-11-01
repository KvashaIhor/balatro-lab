/*
 * fastcheck.c -- native version of the cheapest Balatro seed checks (our own code).
 *
 * Same algorithm as rng.py (see that file for the explanation).  What makes it fast:
 *   - seeds are enumerated with the FIRST character varying fastest.  pseudohash() walks the
 *     string from the end, so the hash state after the last 7 seed characters is cached and each
 *     new seed costs ~1 hash step for the seed plus the key's own characters;
 *   - the first-hand filter draws the shuffled deck one position at a time and stops at the first
 *     card that is not in the target hand (85% of seeds stop after one draw).
 *
 * Build (fp-contract=off is REQUIRED: the game does not fuse a*b+c, clang on arm64 would):
 *   cc -O3 -mcpu=native -ffp-contract=off -o fastcheck fastcheck.c -lpthread
 *
 * Modes:
 *   ./fastcheck dump SEED...                         boss/voucher/tags/hand for each seed (for
 *                                                    cross-checking against opening.py)
 *   ./fastcheck bench SECONDS LOG                    single-thread speed of each filter
 *   ./fastcheck search LOG THREADS MAXSECONDS ALPHABET CHUNK_FIRST CHUNK_LAST HAND [BOSS] [VOUCHER]
 *        ALPHABET: 35 (1-9, A-Z) or 34 (no O: seeds the game generates itself)
 *        chunks: the last three seed characters fixed (ALPHA^3 chunks of ALPHA^5 seeds each)
 *        HAND: 8 cards like "AS,KH,TD,2C,..." (ranks 2-9 T J Q K A, suits C D H S); "-" = no filter
 *        BOSS/VOUCHER: index into opening.py's BOSSES_ANTE1 / VOUCHERS, or -1
 */
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LJ_PI 3.14159265358979323846
#define LJ_E 2.7182818284590452354

static const char ALPHA35[] = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
static const char ALPHA34[] = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ";

/* ---------------------------------------------------------------- hashing ------------------- */
static inline double lua_fract(double x) { return x - floor(x); }   /* Lua x % 1; inf/NaN -> NaN */

static inline double ph_step(double num, int c, int pos) {
    return lua_fract((1.1239285023 / num) * (double)c * LJ_PI + LJ_PI * (double)pos);
}

static double pseudohash_str(const char *s, int len) {
    double num = 1.0;
    for (int i = len; i >= 1; i--) num = ph_step(num, (unsigned char)s[i - 1], i);
    return num;
}

/* math.abs(tonumber(string.format("%.13f", x))) exactly (ties ignored: they need x = k/2^14). */
static inline double round13(double x) {
    if (x != x) return x;
    double y = x * 1e13;
    double e = fma(x, 1e13, -y);          /* exact product error (intentional fma) */
    double r = nearbyint(y);
    double t = y - r;                      /* exact */
    if (t == 0.5 && e > 0) r += 1.0;
    else if (t == -0.5 && e < 0) r -= 1.0;
    return fabs(r / 1e13);
}

static inline double pseudoseed_first(double keyhash, double hashed_seed, double *state) {
    double st = round13(lua_fract(2.134453429141 + keyhash * 1.72431234));
    *state = st;
    return (st + hashed_seed) / 2.0;
}
static inline double pseudoseed_next(double *state, double hashed_seed) {
    double st = round13(lua_fract(2.134453429141 + *state * 1.72431234));
    *state = st;
    return (st + hashed_seed) / 2.0;
}

/* ---------------------------------------------------------------- LuaJIT TW223 -------------- */
typedef struct { uint64_t s0, s1, s2, s3; } tw_t;

static inline uint64_t tw_step(tw_t *t) {
    uint64_t z, r;
    z = t->s0; z = (((z << 31) ^ z) >> 45) ^ ((z & 0xFFFFFFFFFFFFFFFEull) << 18); r = z; t->s0 = z;
    z = t->s1; z = (((z << 19) ^ z) >> 30) ^ ((z & 0xFFFFFFFFFFFFFFC0ull) << 28); r ^= z; t->s1 = z;
    z = t->s2; z = (((z << 24) ^ z) >> 48) ^ ((z & 0xFFFFFFFFFFFFFE00ull) << 7); r ^= z; t->s2 = z;
    z = t->s3; z = (((z << 21) ^ z) >> 39) ^ ((z & 0xFFFFFFFFFFFE0000ull) << 8); r ^= z; t->s3 = z;
    return r;
}
static inline void tw_seed(tw_t *t, double d) {
    uint64_t u[4];
    uint32_t r = 0x11090601;
    for (int i = 0; i < 4; i++) {
        uint32_t m = 1u << (r & 255);
        r >>= 8;
        if (d != d) {
            u[i] = 0xFFF8000000000000ull;   /* x86 propagates its default NaN */
        } else {
            d = d * LJ_PI;
            d = d + LJ_E;
            memcpy(&u[i], &d, 8);
        }
        if (u[i] < m) u[i] += m;
    }
    t->s0 = u[0]; t->s1 = u[1]; t->s2 = u[2]; t->s3 = u[3];
    for (int i = 0; i < 10; i++) tw_step(t);
}
static inline double tw_random(tw_t *t) {
    uint64_t r = (tw_step(t) & 0x000FFFFFFFFFFFFFull) | 0x3FF0000000000000ull;
    double d;
    memcpy(&d, &r, 8);
    return d - 1.0;
}
/* math.random(n) - 1, i.e. a 0-based index */
static inline int tw_index(tw_t *t, int n) { return (int)floor(tw_random(t) * (double)n); }

/* Seeding then the first draw, fast.  Each component's update is linear over GF(2), so its state after
 * the 10 warm-up steps plus the first draw (11 steps) is a fixed 64x64 bit matrix times the seeded
 * value.  JUMP11[c][byte][v] holds that matrix applied to v placed at byte `byte`: 32 lookups replace
 * 44 steps.  tw_seed_first() leaves the state exactly where tw_seed() + tw_random() would. */
static uint64_t JUMP11[4][8][256];

static uint64_t tw_component_step(int c, uint64_t z) {
    switch (c) {
    case 0: return (((z << 31) ^ z) >> 45) ^ ((z & 0xFFFFFFFFFFFFFFFEull) << 18);
    case 1: return (((z << 19) ^ z) >> 30) ^ ((z & 0xFFFFFFFFFFFFFFC0ull) << 28);
    case 2: return (((z << 24) ^ z) >> 48) ^ ((z & 0xFFFFFFFFFFFFFE00ull) << 7);
    default: return (((z << 21) ^ z) >> 39) ^ ((z & 0xFFFFFFFFFFFE0000ull) << 8);
    }
}

static void jump_tables_init(void) {
    for (int c = 0; c < 4; c++) {
        uint64_t col[64];
        for (int b = 0; b < 64; b++) {
            uint64_t z = 1ull << b;
            for (int s = 0; s < 11; s++) z = tw_component_step(c, z);
            col[b] = z;
        }
        for (int byte = 0; byte < 8; byte++)
            for (int v = 0; v < 256; v++) {
                uint64_t acc = 0;
                for (int b = 0; b < 8; b++) if (v >> b & 1) acc ^= col[byte * 8 + b];
                JUMP11[c][byte][v] = acc;
            }
    }
}

static inline uint64_t jump11(int c, uint64_t u) {
    const uint64_t (*T)[256] = JUMP11[c];
    return T[0][u & 255] ^ T[1][u >> 8 & 255] ^ T[2][u >> 16 & 255] ^ T[3][u >> 24 & 255] ^
           T[4][u >> 32 & 255] ^ T[5][u >> 40 & 255] ^ T[6][u >> 48 & 255] ^ T[7][u >> 56];
}

static inline double tw_seed_first(tw_t *t, double d) {
    uint64_t u[4];
    uint32_t r = 0x11090601;
    for (int i = 0; i < 4; i++) {
        uint32_t m = 1u << (r & 255);
        r >>= 8;
        if (d != d) {
            u[i] = 0xFFF8000000000000ull;
        } else {
            d = d * LJ_PI;
            d = d + LJ_E;
            memcpy(&u[i], &d, 8);
        }
        if (u[i] < m) u[i] += m;
    }
    t->s0 = jump11(0, u[0]); t->s1 = jump11(1, u[1]); t->s2 = jump11(2, u[2]); t->s3 = jump11(3, u[3]);
    uint64_t out = ((t->s0 ^ t->s1 ^ t->s2 ^ t->s3) & 0x000FFFFFFFFFFFFFull) | 0x3FF0000000000000ull;
    double x;
    memcpy(&x, &out, 8);
    return x - 1.0;
}

/* ---------------------------------------------------------------- per-seed checks ----------- */
/* deck order = opening.DECK_ORDER: suit C D H S, rank 2..9 A J K Q T (ASCII order) */
static const char RANKS_SORTED[] = "23456789AJKQT";
static const char SUITS[] = "CDHS";

/* Draw Fisher-Yates positions 52..45 of the "nr1" shuffle; stop at the first card not in mask.
 * Returns number of target cards drawn (8 = full match).  out[] gets the cards if non-NULL. */
static inline int hand_check(double pseed, uint64_t mask, int *out) {
    tw_t t;
    double first = tw_seed_first(&t, pseed);
    int ov_pos[8], ov_card[8], nov = 0;
    for (int i = 52; i >= 45; i--) {
        int j = i == 52 ? (int)floor(first * 52.0) : tw_index(&t, i);   /* 0-based partner position */
        int ci = i - 1, cj = j;                /* cards currently at positions i-1 and j */
        for (int k = 0; k < nov; k++) {
            if (ov_pos[k] == i - 1) ci = ov_card[k];
            if (ov_pos[k] == j) cj = ov_card[k];
        }
        /* position i-1 gets card cj (final); position j gets card ci */
        int found = 0;
        for (int k = 0; k < nov; k++) if (ov_pos[k] == j) { ov_card[k] = ci; found = 1; }
        if (!found) { ov_pos[nov] = j; ov_card[nov] = ci; nov++; }
        if (out) out[52 - i] = cj;
        if (!mask) continue;
        if (!((mask >> cj) & 1)) return 52 - i;
    }
    return 8;
}

static inline int boss_index(double pseed) {
    tw_t t;
    return (int)floor(tw_seed_first(&t, pseed) * 8.0);
}

/* Voucher1 with resamples "Voucher1_resample2", ...; only even (base) vouchers are available. */
static int voucher_index(double keyhash, double hashed, const char *seedstr) {
    double st;
    tw_t t;
    tw_seed(&t, pseudoseed_first(keyhash, hashed, &st));
    int v = tw_index(&t, 32);
    char buf[64];
    for (int it = 2; (v & 1) && it < 1000; it++) {
        int n = snprintf(buf, sizeof buf, "Voucher1_resample%d%s", it, seedstr);
        double st2;
        tw_seed(&t, pseudoseed_first(pseudohash_str(buf, n), hashed, &st2));
        v = tw_index(&t, 32);
    }
    return v;
}

/* Small/Big blind tags ("Tag1" twice, with resamples).  Available at ante 1 with a profile that
 * has discovered Blueprint and all editions: everything except the 9 min-ante-2 tags. */
static const int TAG_AVAILABLE_ANTE1[24] = {1,1,0,1,1,1,1,1,1,0,1,0,0,0,0,0,1,1,1,1,0,1,0,1};
typedef struct { int it; double st; } rs_state_t;
static void tags_ante1(double keyhash, double hashed, const char *seedstr, int out[2]) {
    double st_main = keyhash;
    int have_main = 0;
    rs_state_t rs[64];                      /* resample-key states, indexed by it */
    for (int k = 0; k < 64; k++) rs[k].it = 0;
    tw_t t;
    char buf[64];
    for (int which = 0; which < 2; which++) {
        double ps = have_main ? pseudoseed_next(&st_main, hashed) : pseudoseed_first(keyhash, hashed, &st_main);
        have_main = 1;
        tw_seed(&t, ps);
        int tag = tw_index(&t, 24);
        for (int it = 2; !TAG_AVAILABLE_ANTE1[tag] && it < 64; it++) {
            double p;
            if (!rs[it].it) {
                int n = snprintf(buf, sizeof buf, "Tag1_resample%d%s", it, seedstr);
                p = pseudoseed_first(pseudohash_str(buf, n), hashed, &rs[it].st);
                rs[it].it = 1;
            } else {
                p = pseudoseed_next(&rs[it].st, hashed);
            }
            tw_seed(&t, p);
            tag = tw_index(&t, 24);
        }
        out[which] = tag;
    }
}

/* ---------------------------------------------------------------- dump mode ----------------- */
static int dump(int argc, char **argv) {
    for (int a = 0; a < argc; a++) {
        const char *s = argv[a];
        int n = (int)strlen(s);
        char buf[64];
        double hashed = pseudohash_str(s, n), st;
        int m = snprintf(buf, sizeof buf, "nr1%s", s);
        int cards[8];
        hand_check(pseudoseed_first(pseudohash_str(buf, m), hashed, &st), 0, cards);
        m = snprintf(buf, sizeof buf, "boss%s", s);
        int boss = boss_index(pseudoseed_first(pseudohash_str(buf, m), hashed, &st));
        m = snprintf(buf, sizeof buf, "Voucher1%s", s);
        int v = voucher_index(pseudohash_str(buf, m), hashed, s);
        m = snprintf(buf, sizeof buf, "Tag1%s", s);
        int tags[2];
        tags_ante1(pseudohash_str(buf, m), hashed, s, tags);
        printf("%s %.17g boss=%d voucher=%d tags=%d,%d hand=", s, hashed, boss, v, tags[0], tags[1]);
        for (int k = 0; k < 8; k++) printf("%s%c%c", k ? "," : "", SUITS[cards[k] / 13], RANKS_SORTED[cards[k] % 13]);
        printf("\n");
    }
    return 0;
}

/* ---------------------------------------------------------------- enumeration --------------- */
/* Hash prefix cache for one key length L: part[j] = state after seed chars 7..j (j=7..1). */
typedef struct { int L; double part[9]; } hcache_t;

static inline void hc_update(hcache_t *h, const int *chars, int from) {
    /* recompute part[from..1]; part[8] = 1.0 (start) */
    for (int j = from; j >= 1; j--) h->part[j] = ph_step(h->part[j + 1], chars[j], h->L + j + 1);
}
static inline double hc_finish(const hcache_t *h, int c0, const char *key) {
    double num = ph_step(h->part[1], c0, h->L + 1);
    for (int i = h->L; i >= 1; i--) num = ph_step(num, (unsigned char)key[i - 1], i);
    return num;
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
static FILE *LOGF;
static pthread_mutex_t LOGMU = PTHREAD_MUTEX_INITIALIZER;
static double T0;
static void logf_(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
#include <stdarg.h>
static void logf_(const char *fmt, ...) {
    char msg[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    time_t tt = time(NULL);
    char ts[32];
    strftime(ts, sizeof ts, "%Y-%m-%d %H:%M:%S", localtime(&tt));
    pthread_mutex_lock(&LOGMU);
    printf("%s +%7.1fs  %s\n", ts, now_s() - T0, msg);
    fflush(stdout);
    if (LOGF) { fprintf(LOGF, "%s +%7.1fs  %s\n", ts, now_s() - T0, msg); fflush(LOGF); }
    pthread_mutex_unlock(&LOGMU);
}

typedef struct {
    const char *alpha; int base;
    long chunk_first, chunk_last;
    uint64_t hand_mask; int boss; int voucher;
    double deadline;
} job_t;
static job_t JOB;
static atomic_long NEXT_CHUNK;
static atomic_llong SEEDS_DONE, HAND_PASS, ALL_PASS;
static atomic_int STOP;

/* Scan one chunk: chars[7], chars[6], chars[5] fixed. */
static void scan_chunk(long chunk) {
    const int B = JOB.base;
    int d[8] = {0};
    d[5] = chunk % B; d[6] = (chunk / B) % B; d[7] = (int)(chunk / B / B);
    int chars[8];
    for (int k = 0; k < 8; k++) chars[k] = (unsigned char)JOB.alpha[d[k]];
    hcache_t hs = {.L = 0}, hn = {.L = 3}, hb = {.L = 4};
    hs.part[8] = hn.part[8] = hb.part[8] = 1.0;
    hc_update(&hs, chars, 7); hc_update(&hn, chars, 7); hc_update(&hb, chars, 7);
    long long local = 0, lhand = 0, lall = 0;
    char seedstr[9]; seedstr[8] = 0;
    for (;;) {
        for (int c0 = 0; c0 < B; c0++) {
            int ch0 = (unsigned char)JOB.alpha[c0];
            double hashed = ph_step(hs.part[1], ch0, 1);
            double st;
            int pass = 1;
            if (JOB.hand_mask) {
                double kh = hc_finish(&hn, ch0, "nr1");
                pass = hand_check(pseudoseed_first(kh, hashed, &st), JOB.hand_mask, NULL) == 8;
                if (pass) lhand++;
            }
            if (pass && JOB.boss >= 0) {
                double kh = hc_finish(&hb, ch0, "boss");
                pass = boss_index(pseudoseed_first(kh, hashed, &st)) == JOB.boss;
            }
            if (pass) {
                seedstr[0] = (char)ch0;
                for (int k = 1; k < 8; k++) seedstr[k] = (char)chars[k];
                if (JOB.voucher >= 0) {
                    char buf[32];
                    int n = snprintf(buf, sizeof buf, "Voucher1%s", seedstr);
                    pass = voucher_index(pseudohash_str(buf, n), hashed, seedstr) == JOB.voucher;
                }
                if (pass) { lall++; logf_("MATCH %s", seedstr); }
            }
        }
        local += B;
        /* odometer on digits 1..4 (digits 5..7 fixed by the chunk) */
        int k = 1;
        while (k <= 4) {
            if (++d[k] < B) break;
            d[k] = 0; chars[k] = (unsigned char)JOB.alpha[0]; k++;
        }
        if (k > 4) break;
        chars[k] = (unsigned char)JOB.alpha[d[k]];
        for (int j = 1; j < k; j++) chars[j] = (unsigned char)JOB.alpha[d[j]];
        hc_update(&hs, chars, k); hc_update(&hn, chars, k); hc_update(&hb, chars, k);
        if ((local & 0xFFFFF) < (unsigned)B) {
            atomic_fetch_add(&SEEDS_DONE, local); atomic_fetch_add(&HAND_PASS, lhand);
            atomic_fetch_add(&ALL_PASS, lall); local = lhand = lall = 0;
            if (atomic_load(&STOP)) return;
        }
    }
    atomic_fetch_add(&SEEDS_DONE, local); atomic_fetch_add(&HAND_PASS, lhand); atomic_fetch_add(&ALL_PASS, lall);
}

static void *worker(void *arg) {
    (void)arg;
    for (;;) {
        if (atomic_load(&STOP)) break;
        long c = atomic_fetch_add(&NEXT_CHUNK, 1);
        if (c > JOB.chunk_last) break;
        scan_chunk(c);
    }
    return NULL;
}

static int card_index(const char *s) {     /* "AS" -> index into deck order */
    const char *r = strchr(RANKS_SORTED, s[0]), *u = strchr(SUITS, s[1]);
    if (!r || !u || !s[0] || !s[1]) return -1;
    return (int)(u - SUITS) * 13 + (int)(r - RANKS_SORTED);
}

static int search(int argc, char **argv) {
    if (argc < 7) { fprintf(stderr, "search: bad args\n"); return 2; }
    LOGF = fopen(argv[0], "w");
    int threads = atoi(argv[1]);
    double maxsec = atof(argv[2]);
    JOB.base = atoi(argv[3]);
    JOB.alpha = JOB.base == 34 ? ALPHA34 : ALPHA35;
    JOB.chunk_first = atol(argv[4]);
    JOB.chunk_last = atol(argv[5]);
    JOB.hand_mask = 0;
    if (strcmp(argv[6], "-")) {
        char tmp[128]; strncpy(tmp, argv[6], sizeof tmp - 1); tmp[sizeof tmp - 1] = 0;
        for (char *tok = strtok(tmp, ","); tok; tok = strtok(NULL, ",")) {
            int ci = card_index(tok);
            if (ci < 0) { fprintf(stderr, "bad card %s\n", tok); return 2; }
            JOB.hand_mask |= 1ull << ci;
        }
    }
    JOB.boss = argc > 7 ? atoi(argv[7]) : -1;
    JOB.voucher = argc > 8 ? atoi(argv[8]) : -1;
    long nchunks = JOB.chunk_last - JOB.chunk_first + 1;
    double total = (double)nchunks * pow(JOB.base, 5);
    logf_("search start: %d threads, alphabet %d, chunks %ld..%ld (%.3g seeds), hand mask %llx, boss %d, "
          "voucher %d, max %.0fs", threads, JOB.base, JOB.chunk_first, JOB.chunk_last, total,
          (unsigned long long)JOB.hand_mask, JOB.boss, JOB.voucher, maxsec);
    atomic_store(&NEXT_CHUNK, JOB.chunk_first);
    pthread_t th[256];
    double t0 = now_s();
    for (int i = 0; i < threads; i++) pthread_create(&th[i], NULL, worker, NULL);
    long long last = 0;
    double tl = t0;
    int stopped_by_time = 0;
    for (;;) {
        usleep(200000);
        long long done = atomic_load(&SEEDS_DONE);
        double t = now_s();
        int finished = atomic_load(&NEXT_CHUNK) > JOB.chunk_last + threads;
        if (t - tl >= 5.0 || finished) {
            double rate = done / (t - t0);
            logf_("progress %.4g / %.4g seeds (%.2f%%), %.1f M seeds/s (last 5s %.1f M/s), hand-pass %lld, "
                  "full-pass %lld, ETA %.0fs", (double)done, total, 100.0 * done / total, rate / 1e6,
                  (done - last) / (t - tl) / 1e6, (long long)atomic_load(&HAND_PASS),
                  (long long)atomic_load(&ALL_PASS), (total - done) / (rate > 0 ? rate : 1));
            last = done; tl = t;
        }
        if (t - t0 >= maxsec && !atomic_load(&STOP)) { atomic_store(&STOP, 1); stopped_by_time = 1; }
        if (finished || atomic_load(&STOP)) break;
    }
    for (int i = 0; i < threads; i++) pthread_join(th[i], NULL);
    double el = now_s() - t0;
    long long done = atomic_load(&SEEDS_DONE);
    logf_("search end (%s): %lld seeds in %.1fs = %.1f M seeds/s on %d threads; hand-pass %lld, full-pass %lld; exit 0",
          stopped_by_time ? "time limit" : "range complete", done, el, done / el / 1e6, threads,
          (long long)atomic_load(&HAND_PASS), (long long)atomic_load(&ALL_PASS));
    return 0;
}

/* ---------------------------------------------------------------- bench mode ---------------- */
static int bench(int argc, char **argv) {
    double secs = argc > 0 ? atof(argv[0]) : 5;
    LOGF = argc > 1 ? fopen(argv[1], "w") : NULL;
    const char *names[] = {"hashes only (seed + nr1 key, cached prefix)", "boss (key 'boss', 1 draw)",
                           "first hand, early-exit filter (key 'nr1')", "voucher (key 'Voucher1' + resamples)",
                           "tags (key 'Tag1' x2 + resamples)"};
    logf_("bench start: %d checks x %.0fs single thread, ETA %.0fs", 5, secs, 5 * secs);
    uint64_t mask = 0;
    const char *hand[] = {"2C", "9C", "QD", "6H", "3S", "TS", "AD", "KH"};
    for (int i = 0; i < 8; i++) mask |= 1ull << card_index(hand[i]);
    for (int mode = 0; mode < 5; mode++) {
        int d[8] = {0}, chars[8];
        for (int k = 0; k < 8; k++) { d[k] = (k * 7 + 3) % 35; chars[k] = ALPHA35[d[k]]; }
        hcache_t hs = {.L = 0}, hn = {.L = 3}, hb = {.L = 4};
        hs.part[8] = hn.part[8] = hb.part[8] = 1.0;
        hc_update(&hs, chars, 7); hc_update(&hn, chars, 7); hc_update(&hb, chars, 7);
        long long n = 0;
        volatile long long sink = 0;
        double t0 = now_s(), t = t0;
        char seedstr[9]; seedstr[8] = 0;
        while (t - t0 < secs) {
            for (int rep = 0; rep < 64; rep++) {
                for (int c0 = 0; c0 < 35; c0++) {
                    int ch0 = ALPHA35[c0];
                    double hashed = ph_step(hs.part[1], ch0, 1), st;
                    if (mode == 0) { sink += (long long)(hc_finish(&hn, ch0, "nr1") * 1e6) + (long long)(hashed * 7); }
                    else if (mode == 1) sink += boss_index(pseudoseed_first(hc_finish(&hb, ch0, "boss"), hashed, &st));
                    else if (mode == 2) sink += hand_check(pseudoseed_first(hc_finish(&hn, ch0, "nr1"), hashed, &st), mask, NULL);
                    else {
                        seedstr[0] = (char)ch0;
                        for (int k = 1; k < 8; k++) seedstr[k] = (char)chars[k];
                        char buf[32];
                        if (mode == 3) {
                            int m = snprintf(buf, sizeof buf, "Voucher1%s", seedstr);
                            sink += voucher_index(pseudohash_str(buf, m), hashed, seedstr);
                        } else {
                            int m = snprintf(buf, sizeof buf, "Tag1%s", seedstr), tg[2];
                            tags_ante1(pseudohash_str(buf, m), hashed, seedstr, tg);
                            sink += tg[0] + tg[1];
                        }
                    }
                }
                n += 35;
                int k = 1;
                while (k < 8 && ++d[k] == 35) { d[k] = 0; k++; }
                for (int j = 1; j <= k && j < 8; j++) chars[j] = ALPHA35[d[j]];
                int from = k < 8 ? k : 7;
                hc_update(&hs, chars, from); hc_update(&hn, chars, from); hc_update(&hb, chars, from);
            }
            t = now_s();
        }
        logf_("RESULT %s: %.2f M seeds/s single thread (%lld seeds in %.1fs) [sink %lld]", names[mode],
              n / (t - t0) / 1e6, n, t - t0, (long long)sink);
    }
    logf_("bench end, exit 0");
    return 0;
}

#ifndef FASTCHECK_NO_MAIN
int main(int argc, char **argv) {
    T0 = now_s();
    jump_tables_init();
    if (argc >= 2 && !strcmp(argv[1], "dump")) return dump(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "bench")) return bench(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "search")) return search(argc - 2, argv + 2);
    fprintf(stderr, "usage: %s dump SEED... | bench SECONDS LOG | search LOG THREADS MAXSEC ALPHABET "
                    "CHUNK_FIRST CHUNK_LAST HAND [BOSS] [VOUCHER]\n", argv[0]);
    return 2;
}
#endif
