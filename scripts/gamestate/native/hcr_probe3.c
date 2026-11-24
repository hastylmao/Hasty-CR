/*
 * hcr_probe3: look for each unit's attack target inside its components.
 * Read-only (pread on /proc/<pid>/mem).
 *
 *   hcr_probe3 <pid> <libg_base_hex> <interval_ms> <frames>
 *
 * The hit-point component is reached as entity +0x18 -> table, table +0x10.
 * For every slot of that table (0x00..0x78), read 0x200 bytes of the
 * component and report fields holding another live entity's ADDRESS (8-byte)
 * or ID (entity +0x08, 4-byte). Per frame:
 *   {"t":tick,"e":[[addr,id,side],...],"m":[[addr,slot,off,kind,value],...]}
 * kind 0 = address match, 1 = id match.
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
#define COMP 0x200

static int fd = -1;
static int rd(uint64_t a, void *o, size_t n) { return a >= 0x10000ull && pread(fd, o, n, (off_t)a) == (ssize_t)n; }
static uint64_t u64(uint64_t a) { uint64_t v = 0; return rd(a, &v, 8) ? v : 0; }

static uint64_t ptr[MAX_UNITS];
static int32_t ids[MAX_UNITS], sides[MAX_UNITS];
static int n;

static int find_addr(uint64_t v) { for (int i = 0; i < n; ++i) if (ptr[i] == v) return i; return -1; }
static int find_id(int32_t v) { if (v < 1000) return -1; for (int i = 0; i < n; ++i) if (ids[i] == v) return i; return -1; }

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
  static uint8_t c[COMP];
  for (long f = 0; f < frames; ++f) {
    uint64_t root = u64(libg + BATTLE_GLOBAL), ctx = root ? u64(root + 0x18) : 0;
    uint64_t battle = ctx ? u64(ctx + 0x90) : 0;
    int32_t tick = -1;
    if (!battle || !rd(battle + 0x60, &tick, 4)) { printf("{\"t\":-1}\n"); fflush(stdout); goto wait; }
    uint64_t ps = u64(battle + 0xA8);
    uint64_t reg = ps ? u64(ps + 0x08) : 0, coll = reg ? u64(reg + 0x40) : 0, data = coll ? u64(coll + 0x08) : 0;
    int32_t count = -1;
    if (coll) rd(coll + 0x14, &count, 4);
    n = 0;
    if (data && count > 0 && count <= MAX_UNITS && rd(data, ptr, (size_t)count * 8)) {
      n = count;
      for (int i = 0; i < n; ++i) {
        ids[i] = sides[i] = -1;
        rd(ptr[i] + 0x08, &ids[i], 4);
        rd(ptr[i] + 0x78, &sides[i], 4);
      }
    }
    printf("{\"t\":%d,\"e\":[", tick);
    for (int i = 0; i < n; ++i) printf("%s[%llu,%d,%d]", i ? "," : "", (unsigned long long)ptr[i], ids[i], sides[i]);
    printf("],\"m\":[");
    int first = 1;
    for (int i = 0; i < n; ++i) {
      uint64_t table = u64(ptr[i] + 0x18);
      if (!table) continue;
      for (int slot = 0; slot < 0x80; slot += 8) {
        uint64_t comp = u64(table + slot);
        if (comp < 0x100000000ull || comp > 0x7fffffffffffull || (comp & 7) || !rd(comp, c, COMP)) continue;
        for (int off = 0; off + 8 <= COMP; off += 4) {
          uint64_t v8; int32_t v4;
          memcpy(&v8, c + off, 8);
          memcpy(&v4, c + off, 4);
          int j;
          if (!(off & 7) && v8 != ptr[i] && (j = find_addr(v8)) >= 0) {
            printf("%s[%llu,%d,%d,0,%d]", first ? "" : ",", (unsigned long long)ptr[i], slot, off, j);
            first = 0;
          } else if (v4 != ids[i] && (j = find_id(v4)) >= 0) {
            printf("%s[%llu,%d,%d,1,%d]", first ? "" : ",", (unsigned long long)ptr[i], slot, off, j);
            first = 0;
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
