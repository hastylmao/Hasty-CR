/*
 * hcr_findclock: layout-free search for the battle object after a client update
 * that changed its fields as well as the global. Read-only (pread only).
 *
 *   hcr_findclock <pid> <lo_hex> <hi_hex> <libg_base_hex> [gap_ms=2000]
 *
 * For every 8-byte slot in [lo, hi) holding a pointer, every chain
 * root=[slot], ctx=[root+h1] (h1 0..0x80), obj=[ctx+h2] (h2 0..0x200) is
 * collected (unique obj only). Each obj's first 0x400 bytes are read, then
 * again after gap_ms; an int32 whose value is 1..8000 and grew by 0.6x..1.4x
 * of 20 ticks/s is a battle clock. Also prints the 1-hop form (obj=[root+h1]).
 * Output: "slot_off h1 h2 field_off v0 v1" (h2 = -1 for one hop).
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAXO 400000
#define SPAN 0x400

static int fd;
static int rd(uint64_t a, void *o, size_t n) {
  if (a < 0x10000ull || a > 0x800000000000ull) return 0;
  return pread(fd, o, n, (off_t)a) == (ssize_t)n;
}
static uint64_t u64(uint64_t a) { uint64_t v = 0; return rd(a, &v, 8) ? v : 0; }
static int heap(uint64_t v) { return v > 0x100000000ull && v < 0x800000000000ull && (v & 7) == 0; }

typedef struct { uint64_t obj, slot; int h1, h2; } Ch;
static Ch ch[MAXO];
static int n;
static int32_t *snap;

static int seen(uint64_t o) {
  for (int i = n - 1; i >= 0 && i > n - 64; --i) if (ch[i].obj == o) return 1;   /* cheap local dedupe */
  return 0;
}

int main(int argc, char **argv) {
  if (argc < 5) return 2;
  char path[64];
  snprintf(path, sizeof path, "/proc/%s/mem", argv[1]);
  fd = open(path, O_RDONLY);
  if (fd < 0) { perror("open"); return 1; }
  uint64_t lo = strtoull(argv[2], 0, 16), hi = strtoull(argv[3], 0, 16), base = strtoull(argv[4], 0, 16);
  int gap = argc > 5 ? atoi(argv[5]) : 2000;
  for (uint64_t s = lo; s < hi && n < MAXO - 300; s += 8) {
    uint64_t root = u64(s);
    if (!heap(root)) continue;
    for (int h1 = 0; h1 <= 0x80; h1 += 8) {
      uint64_t ctx = u64(root + h1);
      if (!heap(ctx)) continue;
      if (!seen(ctx)) { ch[n++] = (Ch){ctx, s, h1, -1}; }
      for (int h2 = 0; h2 <= 0x200 && n < MAXO - 1; h2 += 8) {
        uint64_t o = u64(ctx + h2);
        if (heap(o) && !seen(o)) ch[n++] = (Ch){o, s, h1, h2};
      }
    }
  }
  snap = malloc((size_t)n * SPAN);
  for (int i = 0; i < n; ++i)
    if (!rd(ch[i].obj, (uint8_t *)snap + (size_t)i * SPAN, SPAN)) memset((uint8_t *)snap + (size_t)i * SPAN, 0xff, SPAN);
  struct timespec ts = {gap / 1000, (long)(gap % 1000) * 1000000L};
  nanosleep(&ts, NULL);
  int lo_d = gap * 20 * 6 / 10000, hi_d = gap * 20 * 14 / 10000, out = 0;
  int32_t now[SPAN / 4];
  for (int i = 0; i < n && out < 200; ++i) {
    if (!rd(ch[i].obj, now, SPAN)) continue;
    int32_t *was = (int32_t *)((uint8_t *)snap + (size_t)i * SPAN);
    for (int k = 0; k < SPAN / 4; ++k) {
      int d = now[k] - was[k];
      if (was[k] >= 1 && was[k] <= 8000 && d >= lo_d && d <= hi_d) {
        printf("%llx %x %x %x %d %d\n", (unsigned long long)(ch[i].slot - base), ch[i].h1,
               (unsigned)ch[i].h2, k * 4, was[k], now[k]);
        ++out;
      }
    }
  }
  printf("done chains=%d hits=%d\n", n, out);
  return 0;
}
