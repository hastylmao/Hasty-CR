/*
 * hcr_findbattle: after a client update, find the libg global that leads to
 * the live battle. Read-only: opens /proc/<pid>/mem O_RDONLY and only pread()s
 * single small fields, never bulk heap.
 *
 *   hcr_findbattle <pid> <lo_hex> <hi_hex> <libg_base_hex>
 *
 * Every 8-byte slot in [lo, hi) (libg's writable mappings) is tried as the
 * global: root = [slot]; for each hop pair (h1, h2) in a small range,
 * battle = [[root + h1] + h2]; the battle passes if it looks like the
 * 160402012 layout: tick at +0x60 in 1..7000, player-state pointer at +0xA8,
 * two player records at ps + 0xE0 whose hand vector (+0x210, size +0x21C)
 * holds 4 distinct indexes 0..7 in at least one record. Prints candidates as
 * "slot_off h1 h2 tick". Run it twice a few seconds apart: the true one's tick
 * grows.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static int fd;
static int rd(uint64_t a, void *o, size_t n) {
  if (a < 0x10000ull || a > 0x800000000000ull) return 0;
  return pread(fd, o, n, (off_t)a) == (ssize_t)n;
}
static uint64_t u64(uint64_t a) { uint64_t v = 0; return rd(a, &v, 8) ? v : 0; }
static int heap(uint64_t v) { return v > 0x100000000ull && v < 0x800000000000ull && (v & 7) == 0; }

static int hand_ok(uint64_t rec) {
  int32_t size = 0;
  if (!rd(rec + 0x21C, &size, 4) || size != 4) return 0;
  uint64_t vec = u64(rec + 0x210);
  int32_t h[4];
  if (!heap(vec) || !rd(vec, h, 16)) return 0;
  int seen = 0;
  for (int i = 0; i < 4; ++i) {
    if (h[i] < 0 || h[i] > 7 || (seen >> h[i]) & 1) return 0;
    seen |= 1 << h[i];
  }
  return 1;
}

static int battle_ok(uint64_t b, int32_t *tick) {
  if (!rd(b + 0x60, tick, 4) || *tick < 1 || *tick > 7000) return 0;
  uint64_t ps = u64(b + 0xA8);
  if (!heap(ps)) return 0;
  uint64_t p0 = u64(ps + 0xE0), p1 = u64(ps + 0xE8);
  if (!heap(p0) || !heap(p1)) return 0;
  return hand_ok(p0) || hand_ok(p1);
}

int main(int argc, char **argv) {
  if (argc < 5) { fprintf(stderr, "usage\n"); return 2; }
  char path[64];
  snprintf(path, sizeof path, "/proc/%s/mem", argv[1]);
  fd = open(path, O_RDONLY);
  if (fd < 0) { perror("open"); return 1; }
  uint64_t lo = strtoull(argv[2], 0, 16), hi = strtoull(argv[3], 0, 16);
  uint64_t base = strtoull(argv[4], 0, 16);
  int found = 0;
  for (uint64_t s = lo; s < hi; s += 8) {
    uint64_t root = u64(s);
    if (!heap(root)) continue;
    for (uint64_t h1 = 0; h1 <= 0x80; h1 += 8) {
      uint64_t ctx = u64(root + h1);
      if (!heap(ctx)) continue;
      for (uint64_t h2 = 0; h2 <= 0x200; h2 += 8) {
        uint64_t b = u64(ctx + h2);
        int32_t tick;
        if (heap(b) && battle_ok(b, &tick)) {
          printf("%llx %llx %llx %d\n", (unsigned long long)(s - base),
                 (unsigned long long)h1, (unsigned long long)h2, tick);
          if (++found > 40) return 0;
        }
      }
    }
  }
  printf("done %d\n", found);
  return 0;
}
