/*
 * table.c -- the precomputed seed table: a run's seed from its opening in about a second.
 *
 * A rainbow table over all 34^8 seeds the game generates (no letter O).  The function it inverts is the
 * opening key: first hand (as a set), boss, voucher and both skip tags (rainbow.c, observe()).  A chain
 * starts at seed start(i), alternates key = observe(seed) and seed = reduce(key, column), and only its end
 * is stored (with i).  Success per table depends on chains x T / N (2 -> 75%); see rainbow.c's `test` mode
 * and logs/rainbow.log for the measurements behind the parameters.
 *
 * Files in DIR: t<table>.meta ("K T chains segments") and t<table>_s<NNN>.bin, one per segment: records
 * {end, chain} sorted by end.  Segments are written whole (temp file + rename), so an interrupted build
 * resumes at the first missing segment, and lookups use whatever segments exist.
 *
 * Build:  cc -O3 -mcpu=native -ffp-contract=off -o table table.c -lpthread -lm
 * Modes:  ./table build DIR TABLE T CHAINS_PER_N SEGMENTS THREADS LOG [K]
 *         ./table lookup DIR HAND BOSS VOUCHER TAG0 TAG1 THREADS     (indexes as in opening.py; HAND "AS,KH,...")
 *         ./table seed DIR SEED THREADS        look up a seed's own opening (tests)
 *         ./table info DIR                      what is built, and the expected success rate
 */
#define RAINBOW_NO_MAIN
#include "rainbow.c"
#include <errno.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>

typedef struct __attribute__((packed)) { uint64_t end; uint32_t chain; } rec_t;   /* 12 bytes */

static inline uint64_t chain_start(uint64_t i, int table) {
    return mix64(((uint64_t)table << 56) ^ i ^ 0x5EED5EEDull) % N;
}

static inline uint64_t key_of(uint64_t mask, int boss, int v, int t0, int t1) {
    return mix64(mask) ^ mix64(((uint64_t)boss << 24) | ((uint64_t)v << 16) | ((uint64_t)t0 << 8) | (uint64_t)t1);
}

static void set_space(int k) {
    K = k;
    N = 1;
    for (int i = 0; i < K; i++) N *= 34;
}

/* ---- build ------------------------------------------------------------------------------------- */
static struct {
    int table;
    long lo, hi;
    rec_t *recs;
    atomic_long next;
    atomic_llong chains_done;
} B;

static void *build_worker2(void *arg) {
    (void)arg;
    uint64_t x[BLOCK], keys[BLOCK];
    for (;;) {
        long i0 = atomic_fetch_add(&B.next, BLOCK);
        if (i0 >= B.hi) break;
        int n = (int)(B.hi - i0 < BLOCK ? B.hi - i0 : BLOCK);
        for (int l = 0; l < n; l++) x[l] = chain_start((uint64_t)(i0 + l), B.table);
        for (int col = 0; col < T; col++) {
            observe_block(x, n, keys);
            for (int l = 0; l < n; l++) x[l] = reduce(keys[l], col, B.table);
        }
        for (int l = 0; l < n; l++) B.recs[i0 + l - B.lo] = (rec_t){x[l], (uint32_t)(i0 + l)};
        atomic_fetch_add(&B.chains_done, n);
    }
    return NULL;
}

static int by_rec_end(const void *a, const void *b) {
    uint64_t x = ((const rec_t *)a)->end, y = ((const rec_t *)b)->end;
    return x < y ? -1 : x > y;
}

static int file_exists(const char *p) { struct stat st; return stat(p, &st) == 0; }

static int build(int argc, char **argv) {
    if (argc < 7) { fprintf(stderr, "build: DIR TABLE T CHAINS_PER_N SEGMENTS THREADS LOG [K]\n"); return 2; }
    const char *dir = argv[0];
    int table = atoi(argv[1]);
    T = atoi(argv[2]);
    double cpn = atof(argv[3]);
    int segs = atoi(argv[4]), threads = atoi(argv[5]);
    LOGF = fopen(argv[6], "a");
    set_space(argc > 7 ? atoi(argv[7]) : 8);
    long m = (long)(cpn * (double)N / T);
    if (m > 0xFFFFFFFFl) { fprintf(stderr, "too many chains for 32-bit chain numbers\n"); return 2; }
    mkdir(dir, 0755);
    char path[512], tmp[512];
    snprintf(path, sizeof path, "%s/t%d.meta", dir, table);
    FILE *mf = fopen(path, "r");
    if (mf) {
        int k2, t2, s2; long m2;
        if (fscanf(mf, "%d %d %ld %d", &k2, &t2, &m2, &s2) != 4 || k2 != K || t2 != T || m2 != m || s2 != segs) {
            fprintf(stderr, "%s exists with other parameters\n", path); return 2;
        }
        fclose(mf);
    } else {
        mf = fopen(path, "w");
        fprintf(mf, "%d %d %ld %d\n", K, T, m, segs);
        fclose(mf);
    }
    double evals_total = (double)m * T;
    logf_("build start: table %d, N = 34^%d = %.4g seeds, T = %d, %ld chains (chains x T / N = %.2f, expected success %.1f%%), "
          "%d segments, %d threads, %.3g evaluations", table, K, (double)N, T, m, (double)m * T / N,
          100 * theory((double)N, (double)m, T), segs, threads, evals_total);
    long done_before = 0;
    for (int s = 0; s < segs; s++) {
        snprintf(path, sizeof path, "%s/t%d_s%03d.bin", dir, table, s);
        if (file_exists(path)) done_before += m * (s + 1) / segs - m * s / segs;
    }
    if (done_before) logf_("resuming: %ld chains (%.1f%%) already built", done_before, 100.0 * done_before / m);
    double t0 = now_s();
    long done_here = 0;
    for (int s = 0; s < segs; s++) {
        snprintf(path, sizeof path, "%s/t%d_s%03d.bin", dir, table, s);
        if (file_exists(path)) continue;
        B.table = table;
        B.lo = m * s / segs;
        B.hi = m * (s + 1) / segs;
        long cnt = B.hi - B.lo;
        B.recs = malloc(cnt * sizeof(rec_t));
        atomic_store(&B.next, B.lo);
        atomic_store(&B.chains_done, 0);
        pthread_t th[256];
        for (int k = 0; k < threads; k++) pthread_create(&th[k], NULL, build_worker2, NULL);
        double tl = now_s();
        while (atomic_load(&B.chains_done) < cnt) {
            usleep(200000);
            if (now_s() - tl >= 60) {
                tl = now_s();
                long all = done_before + done_here + atomic_load(&B.chains_done);
                double rate = (done_here + atomic_load(&B.chains_done)) * (double)T / (tl - t0);
                logf_("progress: segment %d/%d, %ld/%ld chains (%.2f%%), %.1f M evaluations/s, ETA %.1f h, "
                      "success if stopped now %.1f%%", s + 1, segs, all, m, 100.0 * all / m, rate / 1e6,
                      (m - all) * (double)T / (rate > 0 ? rate : 1) / 3600, 100 * theory((double)N, (double)all, T));
            }
        }
        for (int k = 0; k < threads; k++) pthread_join(th[k], NULL);
        qsort(B.recs, cnt, sizeof(rec_t), by_rec_end);
        snprintf(tmp, sizeof tmp, "%s.tmp", path);
        FILE *f = fopen(tmp, "wb");
        if (!f || fwrite(B.recs, sizeof(rec_t), cnt, f) != (size_t)cnt || fclose(f)) {
            logf_("FAILED writing %s: %s; exit 1", tmp, strerror(errno));
            return 1;
        }
        rename(tmp, path);
        free(B.recs);
        done_here += cnt;
        long all = done_before + done_here;
        double rate = done_here * (double)T / (now_s() - t0);
        logf_("segment %d/%d written (%ld chains, %.0f MB); table %.2f%% built, %.1f M evaluations/s, ETA %.1f h, "
              "success now %.1f%%", s + 1, segs, cnt, cnt * sizeof(rec_t) / 1e6, 100.0 * all / m, rate / 1e6,
              (m - all) * (double)T / rate / 3600, 100 * theory((double)N, (double)all, T));
    }
    logf_("build end: table %d complete, %ld chains in %.1f h; exit 0", table, m, (now_s() - t0) / 3600);
    return 0;
}

/* ---- lookup ------------------------------------------------------------------------------------ */
typedef struct { int table, T, K; long m; int segs; const rec_t *seg[1024]; long segn[1024]; long chains; } tab_t;

static int load_tables(const char *dir, tab_t *tabs, int max) {
    int nt = 0;
    for (int t = 0; t < max; t++) {
        char path[512];
        snprintf(path, sizeof path, "%s/t%d.meta", dir, t);
        FILE *mf = fopen(path, "r");
        if (!mf) continue;
        tab_t *tb = &tabs[nt];
        memset(tb, 0, sizeof *tb);
        tb->table = t;
        if (fscanf(mf, "%d %d %ld %d", &tb->K, &tb->T, &tb->m, &tb->segs) != 4) { fclose(mf); continue; }
        fclose(mf);
        for (int s = 0; s < tb->segs && s < 1024; s++) {
            snprintf(path, sizeof path, "%s/t%d_s%03d.bin", dir, t, s);
            int fd = open(path, O_RDONLY);
            if (fd < 0) continue;
            struct stat st;
            fstat(fd, &st);
            if (st.st_size > 0) {
                tb->seg[s] = mmap(NULL, st.st_size, PROT_READ, MAP_SHARED, fd, 0);
                tb->segn[s] = st.st_size / sizeof(rec_t);
                tb->chains += tb->segn[s];
            }
            close(fd);
        }
        if (tb->chains) nt++;
    }
    return nt;
}

typedef struct { uint64_t chain; int pos; } cand_t;

/* For each position, walk from the key to the chain end and collect chains whose stored end matches. */
static long walk_positions(tab_t *tb, uint64_t key, int pos_from, int pos_to, cand_t *out, long cap, long long *evals) {
    long nc = 0;
    for (int p0 = pos_from; p0 > pos_to; p0 -= BLOCK) {
        int n = p0 - pos_to < BLOCK ? p0 - pos_to : BLOCK;
        uint64_t x[BLOCK], k2[BLOCK];
        int col[BLOCK], pos[BLOCK];
        /* lane 0 gets the smallest position (the longest walk), so the lanes still walking are always a prefix */
        for (int l = 0; l < n; l++) { pos[l] = p0 - n + 1 + l; x[l] = reduce(key, pos[l], tb->table); col[l] = pos[l] + 1; }
        for (;;) {
            int act = 0;
            while (act < n && col[act] < tb->T) act++;
            if (!act) break;
            observe_block(x, act, k2);
            *evals += act;
            for (int l = 0; l < act; l++) { x[l] = reduce(k2[l], col[l], tb->table); col[l]++; }
        }
        for (int l = 0; l < n; l++)
            for (int s = 0; s < tb->segs; s++) {
                const rec_t *r = tb->seg[s];
                long lo = 0, hi = tb->segn[s];
                while (lo < hi) { long mid = (lo + hi) / 2; if (r[mid].end < x[l]) lo = mid + 1; else hi = mid; }
                for (; lo < tb->segn[s] && r[lo].end == x[l]; lo++)
                    if (nc < cap) out[nc++] = (cand_t){r[lo].chain, pos[l]};
            }
    }
    return nc;
}

/* Replay candidate chains from their starts to their positions; keep seeds whose opening is the key. */
static int verify(tab_t *tb, uint64_t key, cand_t *c, long nc, uint64_t *found, int maxf, long long *evals, long long *alarms) {
    int nf = 0;
    for (long g = 0; g < nc; g += BLOCK) {
        int n = nc - g < BLOCK ? (int)(nc - g) : BLOCK;
        uint64_t y[BLOCK], k2[BLOCK];
        int step[BLOCK];
        for (int l = 0; l < n; l++) { y[l] = chain_start(c[g + l].chain, tb->table); step[l] = 0; }
        /* advance every lane to its own position: sort-free, lanes that are done just stop */
        for (;;) {
            uint64_t xs[BLOCK];
            int idx[BLOCK], act = 0;
            for (int l = 0; l < n; l++) if (step[l] < c[g + l].pos) { idx[act] = l; xs[act++] = y[l]; }
            if (!act) break;
            observe_block(xs, act, k2);
            *evals += act;
            for (int j = 0; j < act; j++) { int l = idx[j]; y[l] = reduce(k2[j], step[l], tb->table); step[l]++; }
        }
        observe_block(y, n, k2);
        *evals += n;
        for (int l = 0; l < n; l++) {
            if (k2[l] != key) { (*alarms)++; continue; }
            int dup = 0;
            for (int f = 0; f < nf; f++) dup |= found[f] == y[l];
            if (!dup && nf < maxf) found[nf++] = y[l];
        }
    }
    return nf;
}

typedef struct { tab_t *tb; uint64_t key; int from, to; cand_t *c; long nc; long long evals; } walk_job_t;
static void *walk_worker(void *arg) {
    walk_job_t *j = arg;
    j->nc = walk_positions(j->tb, j->key, j->from, j->to, j->c, 1 << 20, &j->evals);
    return NULL;
}

static int do_lookup(const char *dir, uint64_t key, int threads, int quiet) {
    static tab_t tabs[8];
    int nt = load_tables(dir, tabs, 8);
    if (!nt) { printf("NO TABLE in %s\n", dir); return 3; }
    set_space(tabs[0].K);
    double t0 = now_s();
    uint64_t found[16];
    int nf = 0;
    long long evals = 0, alarms = 0;
    for (int ti = 0; ti < nt && !nf; ti++) {
        tab_t *tb = &tabs[ti];
        T = tb->T;
        walk_job_t jobs[64];
        pthread_t th[64];
        /* split positions so each thread gets about the same number of evaluations (~ (T - pos)) */
        int edges[65];
        edges[0] = T - 1;
        for (int k = 1; k <= threads; k++) {
            double frac = 1.0 - sqrt(1.0 - (double)k / threads);
            edges[k] = (int)(T - 1 - frac * T);
            if (edges[k] < -1) edges[k] = -1;
        }
        edges[threads] = -1;
        for (int k = 0; k < threads; k++) {
            jobs[k] = (walk_job_t){tb, key, edges[k], edges[k + 1], malloc(sizeof(cand_t) << 20), 0, 0};
            pthread_create(&th[k], NULL, walk_worker, &jobs[k]);
        }
        for (int k = 0; k < threads; k++) {
            pthread_join(th[k], NULL);
            evals += jobs[k].evals;
            nf += verify(tb, key, jobs[k].c, jobs[k].nc, found + nf, 16 - nf, &evals, &alarms);
            free(jobs[k].c);
        }
    }
    double el = now_s() - t0;
    for (int f = 0; f < nf; f++) { char sd[9]; seed_of(found[f], sd); printf("FOUND %s\n", sd); }
    if (!quiet) printf("STATS tables %d, %s, %.2fs, %lld evaluations, %lld false alarms\n", nt, nf ? "found" : "not found",
                       el, evals, alarms);
    return nf ? 0 : 1;
}

static int lookup_cmd(int argc, char **argv) {
    if (argc < 7) { fprintf(stderr, "lookup: DIR HAND BOSS VOUCHER TAG0 TAG1 THREADS\n"); return 2; }
    uint64_t mask = 0;
    char tmpb[128];
    strncpy(tmpb, argv[1], sizeof tmpb - 1);
    tmpb[sizeof tmpb - 1] = 0;
    int ncards = 0;
    for (char *tok = strtok(tmpb, ","); tok; tok = strtok(NULL, ",")) {
        int ci = card_index(tok);
        if (ci < 0) { fprintf(stderr, "bad card %s\n", tok); return 2; }
        mask |= 1ull << ci;
        ncards++;
    }
    if (ncards != 8) { fprintf(stderr, "need 8 cards\n"); return 2; }
    uint64_t key = key_of(mask, atoi(argv[2]), atoi(argv[3]), atoi(argv[4]), atoi(argv[5]));
    return do_lookup(argv[0], key, atoi(argv[6]), 0);
}

static int seed_cmd(int argc, char **argv) {             /* look up a seed's own opening */
    if (argc < 3) { fprintf(stderr, "seed: DIR SEED THREADS\n"); return 2; }
    static tab_t tabs[8];
    if (!load_tables(argv[0], tabs, 8)) { printf("NO TABLE\n"); return 3; }
    set_space(tabs[0].K);
    return do_lookup(argv[0], observe(argv[1]), atoi(argv[2]), 0);
}

static int info_cmd(int argc, char **argv) {
    if (argc < 1) return 2;
    static tab_t tabs[8];
    int nt = load_tables(argv[0], tabs, 8);
    double miss = 1.0;
    for (int i = 0; i < nt; i++) {
        set_space(tabs[i].K);
        int done = 0;
        for (int s = 0; s < tabs[i].segs; s++) done += tabs[i].segn[s] > 0;
        double p = theory((double)N, (double)tabs[i].chains, tabs[i].T);
        miss *= 1 - p;
        printf("table %d: %d/%d segments, %ld/%ld chains, T %d, expected success %.1f%%\n", tabs[i].table, done,
               tabs[i].segs, tabs[i].chains, tabs[i].m, tabs[i].T, 100 * p);
    }
    printf("all tables: expected success %.1f%%\n", 100 * (1 - miss));
    return 0;
}

/* Self-test on a small space: build, then look up random seeds' openings; the success rate should
 * match theory.  ./table selftest DIR K T CHAINS_PER_N QUERIES THREADS LOG */
static int selftest(int argc, char **argv) {
    if (argc < 7) return 2;
    char *bargv[] = {argv[0], "0", argv[2], argv[3], "4", argv[5], argv[6], argv[1]};
    int r = build(8, bargv);
    if (r) return r;
    long q = atol(argv[4]), ok = 0, exact = 0;
    int threads = atoi(argv[5]);
    double t0 = now_s();
    for (long i = 0; i < q; i++) {
        char sd[9];
        uint64_t idx = mix64(0x7E57 + (uint64_t)i) % N;
        seed_of(idx, sd);
        uint64_t key = observe(sd);
        int saved = dup(1);                                  /* silence do_lookup's lines */
        int devnull = open("/dev/null", O_WRONLY);
        fflush(stdout); dup2(devnull, 1);
        static tab_t tabs[8];
        load_tables(argv[0], tabs, 8);
        int rr = do_lookup(argv[0], key, threads, 1);
        fflush(stdout); dup2(saved, 1); close(devnull); close(saved);
        ok += rr == 0;
        exact += rr == 0;
    }
    logf_("SELFTEST N=34^%s T=%s chains/N=%s: found %ld/%ld (%.1f%%; theory %.1f%%), %.3fs per lookup",
          argv[1], argv[2], argv[3], ok, q, 100.0 * ok / q, 100 * theory((double)N, atof(argv[3]) * N / atof(argv[2]), atoi(argv[2])),
          (now_s() - t0) / q);
    (void)exact;
    return 0;
}

int main(int argc, char **argv) {
    T0 = now_s();
    jump_tables_init();
    resample_keys_init();
    set_space(8);
    if (argc >= 2 && !strcmp(argv[1], "build")) return build(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "lookup")) return lookup_cmd(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "seed")) return seed_cmd(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "info")) return info_cmd(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "selftest")) return selftest(argc - 2, argv + 2);
    fprintf(stderr, "usage: %s build|lookup|seed|info|selftest ...\n", argv[0]);
    return 2;
}
