/*
 * hcr_probe2: where does a unit keep what it is targeting? Read-only.
 *
 *   hcr_probe2 <pid> <libg_base_hex> <interval_ms> <frames>
 *
 * Per frame, for every entity: every 8-byte field of its first 0x200 bytes
 * that equals another live entity's address (level 0), and, following each
 * field that looks like a heap pointer, every 8-byte field of the first
 * 0x180 bytes it points at that does (level 1). One JSON line per frame:
 *   {"t":tick,"m":[[entity,off,inner,value],...]}   inner = -1 for level 0
 * Matching runs on the device so the output stays small.
 * pread() on /proc/<pid>/mem only.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define BATTLE_GLOBAL 0x1AEEF98ull
#define MAX_UNITS 4096
#define ENT 0x200
#define INNER 0x180

static int fd = -1;
static int rd(uint64_t a, void *o, size_t n) { return a >= 0x10000ull && pread(fd, o, n, (off_t)a) == (ssize_t)n; }
static uint64_t u64(uint64_t a) { uint64_t v = 0; return rd(a, &v, 8) ? v : 0; }

static uint64_t addrs[MAX_UNITS];
static int naddr;
static int cmpu(const void *a, const void *b) {
  uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
  return x < y ? -1 : x > y;
}
static int is_entity(uint64_t v) {
  return v && bsearch(&v, addrs, naddr, 8, cmpu) != NULL;
}

int main(int argc, char **argv) {
  if (argc < 5) { fprintf(stderr, "usage: %s pid libg interval_ms frames\n", argv[0]); return 2; }
  char path[64];
  snprintf(path, sizeof path, "/proc/%s/mem", argv[1]);
  fd = open(path, O_RDONLY);
  if (fd < 0) { perror("open"); return 1; }
  uint64_t libg = strtoull(argv[2], NULL, 16);
  int interval = atoi(argv[3]);
  long frames = atol(argv[4]);
  setvbuf(stdout, NULL, _IOFBF, 1 << 20);
  static uint64_t ptr[MAX_UNITS];
  static uint8_t e[ENT], in[INNER];
  for (long n = 0; n < frames; ++n) {
    uint64_t root = u64(libg + BATTLE_GLOBAL), ctx = root ? u64(root + 0x18) : 0;
    uint64_t battle = ctx ? u64(ctx + 0x90) : 0;
    int32_t tick = -1;
    if (!battle || !rd(battle + 0x60, &tick, 4)) { printf("{\"t\":-1}\n"); fflush(stdout); goto wait; }
    uint64_t ps = u64(battle + 0xA8);
    uint64_t reg = ps ? u64(ps + 0x08) : 0, coll = reg ? u64(reg + 0x40) : 0, data = coll ? u64(coll + 0x08) : 0;
    int32_t count = -1;
    if (coll) rd(coll + 0x14, &count, 4);
    printf("{\"t\":%d,\"m\":[", tick);
    if (data && count > 0 && count <= MAX_UNITS && rd(data, ptr, (size_t)count * 8)) {
      memcpy(addrs, ptr, (size_t)count * 8);
      naddr = count;
      qsort(addrs, naddr, 8, cmpu);
      int first = 1;
      for (int i = 0; i < count; ++i) {
        if (!rd(ptr[i], e, ENT)) continue;
        for (int off = 0; off + 8 <= ENT; off += 8) {
          uint64_t v;
          memcpy(&v, e + off, 8);
          if (v == ptr[i]) continue;
          if (is_entity(v)) {
            printf("%s[%llu,%d,-1,%llu]", first ? "" : ",", (unsigned long long)ptr[i], off, (unsigned long long)v);
            first = 0;
            continue;
          }
          if (v < 0x100000000ull || v > 0x7fffffffffffull || (v & 7)) continue;
          if (!rd(v, in, INNER)) continue;
          for (int k = 0; k + 8 <= INNER; k += 8) {
            uint64_t w;
            memcpy(&w, in + k, 8);
            if (w != ptr[i] && is_entity(w)) {
              printf("%s[%llu,%d,%d,%llu]", first ? "" : ",", (unsigned long long)ptr[i], off, k, (unsigned long long)w);
              first = 0;
            }
          }
        }
      }
    }
    printf("]}\n");
    fflush(stdout);
  wait:
    if (interval > 0) { struct timespec ts = {interval / 1000, (long)(interval % 1000) * 1000000L}; nanosleep(&ts, NULL); }
  }
  close(fd);
  return 0;
}
