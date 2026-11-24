/*
 * hcr_reader: stream Clash Royale battle frames from game memory, read-only.
 *
 *   hcr_reader <pid> <libg_base_hex> <interval_ms> [frames]
 *
 * Opens /proc/<pid>/mem O_RDONLY and only ever calls pread() on it. It never
 * writes to the game, never attaches ptrace, never sends input. One JSON line
 * per frame on stdout:
 *
 *   {"t":<tick>,"me":[side,elixir_raw,[hand...],[cycle...]],
 *    "u":[[addr,cat,kind,side,x,y,card,level,hp,maxhp,"name"],...]}
 *
 * "name" is the unit's character name from its data record (entity +0x48 ->
 * data; length at data +0x2c; under 8 chars inline at data +0x30, otherwise
 * a pointer there), e.g. "Skeleton", "Knight_EV1". It is the client's own
 * character name - the same names RoyaleSim's unit types use - so it tells a
 * Witch's skeleton from the Witch and an evolved Knight from a plain one.
 * Emitted only if it is 1-128 chars of [A-Za-z0-9_]; otherwise "".
 * UNVALIDATED until read in a battle.
 *
 * or {"t":-1} when no battle is active. Only the reader's OWN player record is
 * emitted (the one whose side matches HCR_SIDE, default: first player); the
 * opponent's hand and elixir are hidden in the real game and are not read.
 *
 * Offsets are for client 160402012 x86_64 only; scripts/gamestate/memread.py
 * refuses any other build before this binary is ever started.
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

static int fd = -1;

static int rd(uint64_t addr, void *out, size_t n) {
  if (addr < 0x10000ull) return 0;
  return pread(fd, out, n, (off_t)addr) == (ssize_t)n;
}
static uint64_t u64(uint64_t addr) { uint64_t v = 0; return rd(addr, &v, 8) ? v : 0; }
static int32_t i32at(const uint8_t *b, size_t off) { int32_t v; memcpy(&v, b + off, 4); return v; }
static uint64_t u64at(const uint8_t *b, size_t off) { uint64_t v; memcpy(&v, b + off, 8); return v; }

static void unit_name(const uint8_t *e, char *out, size_t cap) {
  out[0] = 0;
  uint64_t data = u64at(e, 0x48);
  if (!data) return;
  uint32_t len = 0;
  if (!rd(data + 0x2C, &len, 4) || len < 1 || len > 128 || len >= cap) return;
  uint64_t chars = data + 0x30;
  if (len >= 8 && !rd(data + 0x30, &chars, 8)) return;
  if (!rd(chars, out, len)) { out[0] = 0; return; }
  out[len] = 0;
  for (uint32_t i = 0; i < len; ++i) {
    char c = out[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) {
      out[0] = 0;
      return;
    }
  }
}

/* A data row's name (row +0x2C length, +0x30 chars or pointer), as unit_name. */
static void row_name_at(uint64_t data, char *out, size_t cap) {
  out[0] = 0;
  if (!data) return;
  uint32_t len = 0;
  if (!rd(data + 0x2C, &len, 4) || len < 1 || len > 64 || len >= cap) return;
  uint64_t chars = data + 0x30;
  if (len >= 8 && !rd(data + 0x30, &chars, 8)) return;
  if (!rd(chars, out, len)) { out[0] = 0; return; }
  out[len] = 0;
  for (uint32_t i = 0; i < len; ++i)
    if (out[i] < 32 || out[i] > 126 || out[i] == '"' || out[i] == ',' || out[i] == ':') { out[0] = 0; return; }
}

static void sleep_ms(int ms) {
  struct timespec ts = {ms / 1000, (long)(ms % 1000) * 1000000L};
  nanosleep(&ts, NULL);
}

/* Per client build (scripts/gamestate/offsets.json), from HCR_GLOBAL / HCR_HOP1 /
 * HCR_HOP2; defaults are build 160402012's. */
static uint64_t g_global = BATTLE_GLOBAL, g_hop1 = 0x18, g_hop2 = 0x90;

static int frame(uint64_t libg, int want_side) {
  uint64_t root = u64(libg + g_global);
  uint64_t ctx = root ? u64(root + g_hop1) : 0;
  uint64_t battle = ctx ? u64(ctx + g_hop2) : 0;
  if (!battle) { printf("{\"t\":-1}\n"); return 0; }
  int32_t tick = -1;
  rd(battle + 0x60, &tick, 4);
  uint64_t ps = u64(battle + 0xA8);
  if (!ps) { printf("{\"t\":%d,\"note\":\"no player state\"}\n", tick); return 0; }
  uint64_t players[2] = {0, 0};
  rd(ps + 0xE0, players, sizeof players);

  printf("{\"t\":%d", tick);
  for (int k = 0; k < 2; ++k) {
    uint8_t p[0x400];
    if (!players[k] || !rd(players[k], p, sizeof p)) continue;
    int32_t side = i32at(p, 0x78);
    if (want_side >= 0 && side != want_side) continue;
    int32_t hs = i32at(p, 0x21C), cs = i32at(p, 0x22C);
    if (hs < 0 || hs > 8) hs = 0;
    if (cs < 0 || cs > 8) cs = 0;
    int32_t hand[8] = {0}, cyc[8] = {0};
    rd(u64at(p, 0x210), hand, (size_t)hs * 4);
    rd(u64at(p, 0x220), cyc, (size_t)cs * 4);
    printf(",\"me\":[%d,%d,[", side, i32at(p, 0x2F8));
    for (int i = 0; i < hs; ++i) printf(i ? ",%d" : "%d", hand[i]);
    printf("],[");
    for (int i = 0; i < cs; ++i) printf(i ? ",%d" : "%d", cyc[i]);
    printf("]");
    /* Cards played so far: total count (+0x318) and each distinct card id in
     * first-play order (+0x288, 8 slots, -1 empty). Found 2026-10-14 with
     * hcr_probe; lets the bot learn its own deck order from memory instead of
     * trusting --deck (a wrong order swapped Cannon/Musketeer all morning). */
    printf(",%d,[", i32at(p, 0x318));
    for (int i = 0; i < 8; ++i) printf(i ? ",%d" : "%d", i32at(p, 0x288 + 4 * i));
    printf("]]");
    break;
  }

  uint64_t registry = u64(ps + 0x08);
  uint64_t coll = registry ? u64(registry + 0x40) : 0;
  uint64_t data = coll ? u64(coll + 0x08) : 0;
  int32_t count = -1;
  if (coll) rd(coll + 0x14, &count, 4);
  printf(",\"registry_count\":%d,\"registry_valid\":%s", count,
         data && count >= 0 && count <= MAX_UNITS ? "true" : "false");
  printf(",\"u\":[");
  if (data && count > 0 && count <= MAX_UNITS) {
    uint64_t ptr[MAX_UNITS];
    if (rd(data, ptr, (size_t)count * 8)) {
      int first = 1;
      for (int i = 0; i < count; ++i) {
        uint8_t e[0x124];
        if (!rd(ptr[i], e, sizeof e)) continue;
        int32_t hp = -1, mx = -1;
        uint64_t comps = u64at(e, 0x18);
        uint64_t hpo = comps ? u64(comps + 0x10) : 0;
        if (hpo) { int32_t pair[2]; if (rd(hpo + 0x10, pair, 8)) { hp = pair[0]; mx = pair[1]; } }
        char name[130];
        unit_name(e, name, sizeof name);
        /* 12th field: deploy time left in ms (entity +0x15c), 0 once on the
         * board; found 2026-10-14 with hcr_probe (1000 -> 0 in 50 ms steps on
         * every card, 0 on spawned children). */
        int32_t deploy = 0;
        rd(ptr[i] + 0x15C, &deploy, 4);
        /* 13th field: the unit's current target, an entity address (0 = none):
         * entity +0x18 -> component table, slot 0 -> +0x10. Found 2026-10-14
         * with hcr_probe3: 7,129 matches over 86 units, every one an enemy;
         * Hog Riders and Giants point only at towers and buildings. */
        uint64_t target = 0, table = comps ? u64(comps) : 0;
        if (table) target = u64(table + 0x10);
        /* 14th field: the attack clock, combat component +0x24 (ms since the attack
         * began, +50 a tick; a hit each HitSpeed). 15th: active buffs from the status
         * component (vtable libg +0x19FC7D8): array +0x18, count +0x24; each buff
         * +0x18 -> its data row (Freeze, ZapFreeze, Rage, Poison...), +0x8 ms left.
         * Same binary as the extracted engine; found 2026-10-21 (ENGINE_MAP). */
        int32_t clock = 0;
        if (table) rd(table + 0x24, &clock, 4);
        char buffs[256]; buffs[0] = 0;
        uint64_t slots[8] = {0};
        int ncomp = i32at(e, 0x24);
        if (comps && ncomp > 0 && ncomp <= 8 && rd(comps, slots, (size_t)ncomp * 8)) {
          for (int c = 0; c < ncomp; ++c) {
            if (!slots[c] || u64(slots[c]) != libg + 0x19FC7D8ULL) continue;
            uint64_t arr = u64(slots[c] + 0x18);
            int32_t nb = 0; rd(slots[c] + 0x24, &nb, 4);
            size_t used = 0;
            for (int b = 0; arr && b < nb && b < 4; ++b) {
              uint64_t bo = u64(arr + 8 * (uint64_t)b);
              if (!bo) continue;
              char bn[70]; row_name_at(u64(bo + 0x18), bn, sizeof bn);
              int32_t left = 0; rd(bo + 0x08, &left, 4);
              if (bn[0] && used + 80 < sizeof buffs)
                used += (size_t)snprintf(buffs + used, sizeof buffs - used, "%s%s:%d", used ? "," : "", bn, left);
            }
            break;
          }
        }
        printf("%s[%llu,%d,%d,%d,%d,%d,%d,%d,%d,%d,\"%s\",%d,%llu,%d,\"%s\"]", first ? "" : ",",
               (unsigned long long)ptr[i], i32at(e, 0x08), i32at(e, 0x30), i32at(e, 0x78),
               i32at(e, 0x7C), i32at(e, 0x80), i32at(e, 0xAC), i32at(e, 0x120), hp, mx, name, deploy,
               (unsigned long long)target, clock, buffs);
        first = 0;
      }
    }
  }
  printf("]}\n");
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <pid> <libg_base_hex> <interval_ms> [frames]\n", argv[0]);
    return 2;
  }
  char path[64];
  snprintf(path, sizeof path, "/proc/%s/mem", argv[1]);
  fd = open(path, O_RDONLY);
  if (fd < 0) { perror("open"); return 1; }
  uint64_t libg = strtoull(argv[2], NULL, 16);
  int interval = atoi(argv[3]);
  long frames = argc > 4 ? atol(argv[4]) : -1;
  const char *eg = getenv("HCR_GLOBAL"), *e1 = getenv("HCR_HOP1"), *e2 = getenv("HCR_HOP2");
  if (eg) g_global = strtoull(eg, 0, 16);
  if (e1) g_hop1 = strtoull(e1, 0, 16);
  if (e2) g_hop2 = strtoull(e2, 0, 16);
  const char *s = getenv("HCR_SIDE");
  int want_side = s ? atoi(s) : -1;
  setvbuf(stdout, NULL, _IOLBF, 0);
  for (long n = 0; frames < 0 || n < frames; ++n) {
    frame(libg, want_side);
    if (interval > 0) sleep_ms(interval);
  }
  close(fd);
  return 0;
}
