/*
 * hcr_probe: raw battle-memory dump for finding new fields, read-only.
 *
 *   hcr_probe <pid> <libg_base_hex> <interval_ms> <frames> <side>
 *
 * Same chain as hcr_reader. Per frame, one JSON line:
 *   {"t":tick,"me":"<hex of our player record, 0x400 bytes>",
 *    "u":[[addr,"<hex of the entity's first 0x200 bytes>",name],...]}
 *
 * Only our own player record (HCR side == <side>) is dumped: the opponent's
 * hand and elixir are hidden in the game and are not read here either.
 * pread() on /proc/<pid>/mem only; never writes, never attaches.
 * Used offline (tools/probe_fields.py) to locate unit target pointers,
 * deploy timers, king-tower activation and hero ability state.
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
#define ENT_BYTES 0x200
#define ME_BYTES 0x400

static int fd = -1;
static int rd(uint64_t a, void *o, size_t n) { return a >= 0x10000ull && pread(fd, o, n, (off_t)a) == (ssize_t)n; }
static uint64_t u64(uint64_t a) { uint64_t v = 0; return rd(a, &v, 8) ? v : 0; }

static void hex(const uint8_t *b, size_t n) {
  static const char *H = "0123456789abcdef";
  for (size_t i = 0; i < n; ++i) { putchar(H[b[i] >> 4]); putchar(H[b[i] & 15]); }
}

static void name_of(uint64_t e, char *out, size_t cap) {
  out[0] = 0;
  uint64_t data = u64(e + 0x48);
  uint32_t len = 0;
  if (!data || !rd(data + 0x2C, &len, 4) || len < 1 || len >= cap) return;
  uint64_t chars = data + 0x30;
  if (len >= 8 && !rd(data + 0x30, &chars, 8)) return;
  if (!rd(chars, out, len)) { out[0] = 0; return; }
  out[len] = 0;
  for (uint32_t i = 0; i < len; ++i) {
    char c = out[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) { out[0] = 0; return; }
  }
}

int main(int argc, char **argv) {
  if (argc < 6) { fprintf(stderr, "usage: %s pid libg interval_ms frames side\n", argv[0]); return 2; }
  char path[64];
  snprintf(path, sizeof path, "/proc/%s/mem", argv[1]);
  fd = open(path, O_RDONLY);
  if (fd < 0) { perror("open"); return 1; }
  uint64_t libg = strtoull(argv[2], NULL, 16);
  int interval = atoi(argv[3]);
  long frames = atol(argv[4]);
  int want = atoi(argv[5]);
  setvbuf(stdout, NULL, _IOFBF, 1 << 20);
  static uint8_t ent[ENT_BYTES], me[ME_BYTES];
  static uint64_t ptr[MAX_UNITS];
  for (long n = 0; n < frames; ++n) {
    uint64_t root = u64(libg + BATTLE_GLOBAL), ctx = root ? u64(root + 0x18) : 0;
    uint64_t battle = ctx ? u64(ctx + 0x90) : 0;
    int32_t tick = -1;
    if (!battle || !rd(battle + 0x60, &tick, 4)) { printf("{\"t\":-1}\n"); fflush(stdout); goto wait; }
    uint64_t ps = u64(battle + 0xA8);
    printf("{\"t\":%d,\"me\":\"", tick);
    if (ps) {
      uint64_t pl[2] = {0, 0};
      rd(ps + 0xE0, pl, sizeof pl);
      for (int k = 0; k < 2; ++k) {
        int32_t side = -9;
        if (pl[k] && rd(pl[k] + 0x78, &side, 4) && side == want && rd(pl[k], me, ME_BYTES)) { hex(me, ME_BYTES); break; }
      }
    }
    printf("\",\"u\":[");
    uint64_t reg = ps ? u64(ps + 0x08) : 0, coll = reg ? u64(reg + 0x40) : 0, data = coll ? u64(coll + 0x08) : 0;
    int32_t count = -1;
    if (coll) rd(coll + 0x14, &count, 4);
    if (data && count > 0 && count <= MAX_UNITS && rd(data, ptr, (size_t)count * 8)) {
      int first = 1;
      for (int i = 0; i < count; ++i) {
        if (!rd(ptr[i], ent, ENT_BYTES)) continue;
        char nm[130];
        name_of(ptr[i], nm, sizeof nm);
        printf("%s[%llu,\"", first ? "" : ",", (unsigned long long)ptr[i]);
        hex(ent, ENT_BYTES);
        printf("\",\"%s\",\"", nm);
        /* the structure at entity +0x50: unit addresses were found inside it */
        uint64_t sub = 0;
        memcpy(&sub, ent + 0x50, 8);
        static uint8_t sb[0x180];
        if (sub && rd(sub, sb, sizeof sb)) hex(sb, sizeof sb);
        printf("\"]");
        first = 0;
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
