"""Balatro seed -> random stream, re-implemented from the published algorithm.

Written for this project (not copied). The algorithm was learned by reading:
  * Immolate (CC BY-NC-SA 4.0, https://github.com/SpectralPack/Immolate), lib/util.cl and
    lib/instance.cl, which re-implement the game's hashing and LuaJIT's math.random;
  * LuaJIT 2.1 lib_math.c / lj_prng.c (MIT) for the Tausworthe generator and math.randomseed;
  * dlew/balatro-erratic-generator (MIT) for independent test vectors.
See REPORT.md for licence notes.

How a Balatro seed turns into random numbers
--------------------------------------------
1. ``pseudohash(s)`` maps any string to a double in [0, 1).  It walks the string from the last
   character to the first:  num = frac(1.1239285023 / num * byte * pi + pi * position).
2. ``hashed_seed = pseudohash(seed)`` is computed once per run.
3. Every random decision in the game names a *key*, e.g. ``"boss"``, ``"Tag1"``, ``"Voucher1"``,
   ``"cdt1"``, ``"nr1"``.  Each key has its own state.  The first use of a key initialises it to
   ``pseudohash(key + seed)``.  Every use (including the first) then advances it:
       state = round_to_13_decimals(frac(2.134453429141 + state * 1.72431234))
   and returns ``(state + hashed_seed) / 2`` -- the "pseudoseed".
4. The pseudoseed is fed to LuaJIT's ``math.randomseed`` (a 4-component Tausworthe generator,
   TW223, seeded from the double's bit pattern and warmed up with 10 steps).  The game then calls
   ``math.random()`` (a double in [0, 1)), ``math.random(n)`` (an integer 1..n) or several of them
   (for shuffles) on that freshly seeded generator.

Floating point must be bit exact.  The game runs on x86-64 without fused multiply-add, so every
``a * b + c`` here is two separately rounded operations (Python never fuses).  The C port in
``fastcheck.c`` is compiled with ``-ffp-contract=off`` for the same reason.
"""
from __future__ import annotations

import math
import struct

__all__ = [
    "SEED_CHARS", "RANDOM_SEED_CHARS", "pseudohash", "lua_mod1", "round13",
    "LuaRandom", "GameRNG", "normalize_seed",
]

#: Characters accepted by the seed entry box (1-9, A-Z; a typed 0 becomes O).
SEED_CHARS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
#: Characters the game uses when it generates a random seed itself.  Believed to exclude 0 and O
#: (random_string draws from 1-9, A-N, P-Z).  UNVERIFIED here -- confirm by looking at a few
#: randomly generated in-game seeds: none should contain the letter O.
RANDOM_SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"

PI = math.pi          # == 3.14159265358979323846 rounded to double, same as Lua's math.pi
E = math.e            # == 2.7182818284590452354 rounded to double
M64 = (1 << 64) - 1

# x86-64 SSE produces this "real indefinite" quiet NaN for inf - inf.  Used only to reproduce the
# game's behaviour on the handful of seeds whose hash degenerates to NaN.
X86_DEFAULT_NAN_BITS = 0xFFF8000000000000

_D = struct.Struct("<d")
_Q = struct.Struct("<Q")


def dbl_to_bits(d: float) -> int:
    return _Q.unpack(_D.pack(d))[0]


def bits_to_dbl(u: int) -> float:
    return _D.unpack(_Q.pack(u))[0]


def normalize_seed(seed: str) -> str:
    """Upper-case and map 0 -> O, as the in-game seed box does."""
    s = seed.strip().upper().replace("0", "O")
    if not 1 <= len(s) <= 8 or any(c not in SEED_CHARS for c in s):
        raise ValueError(f"not a Balatro seed: {seed!r}")
    return s


def lua_mod1(x: float) -> float:
    """Lua's ``x % 1`` (a - floor(a/b)*b).  inf and NaN give NaN, as in LuaJIT."""
    if x != x or x in (math.inf, -math.inf):
        return math.nan
    return x - math.floor(x)


def pseudohash(s: str) -> float:
    """The game's string hash.  Returns NaN for the rare strings where the running value hits 0."""
    num = 1.0
    for i in range(len(s), 0, -1):
        if num != num:            # NaN stays NaN
            return num
        if num == 0.0:            # 1.1239285023 / 0 = inf  ->  inf % 1 = NaN
            return math.nan
        num = lua_mod1((1.1239285023 / num) * ord(s[i - 1]) * PI + PI * i)
    return num


def round13(x: float) -> float:
    """``math.abs(tonumber(string.format("%.13f", x)))`` -- exact, via correctly rounded printf."""
    if x != x:
        return x
    return abs(float("%.13f" % x))


class LuaRandom:
    """LuaJIT 2.1 ``math.random`` / ``math.randomseed`` (TW223 Tausworthe generator)."""

    __slots__ = ("s0", "s1", "s2", "s3")

    def __init__(self, d: float = 0.0):
        self.seed(d)

    def seed(self, d: float) -> None:
        r = 0x11090601
        st = []
        for _ in range(4):
            m = 1 << (r & 255)
            r >>= 8
            if d != d:
                u = X86_DEFAULT_NAN_BITS      # NaN propagates unchanged through d*pi+e on x86
            else:
                d = d * PI            # two roundings, no FMA (matches the x86-64 build)
                d = d + E
                u = dbl_to_bits(d)
            if u < m:
                u += m
            st.append(u)
        self.s0, self.s1, self.s2, self.s3 = st
        for _ in range(10):
            self._step()

    def _step(self) -> int:
        z = self.s0
        z = ((((z << 31) & M64) ^ z) >> 45) ^ (((z & 0xFFFFFFFFFFFFFFFE) << 18) & M64)
        r = z
        self.s0 = z
        z = self.s1
        z = ((((z << 19) & M64) ^ z) >> 30) ^ (((z & 0xFFFFFFFFFFFFFFC0) << 28) & M64)
        r ^= z
        self.s1 = z
        z = self.s2
        z = ((((z << 24) & M64) ^ z) >> 48) ^ (((z & 0xFFFFFFFFFFFFFE00) << 7) & M64)
        r ^= z
        self.s2 = z
        z = self.s3
        z = ((((z << 21) & M64) ^ z) >> 39) ^ (((z & 0xFFFFFFFFFFFE0000) << 8) & M64)
        r ^= z
        self.s3 = z
        return r

    def random(self) -> float:
        """``math.random()``: a double in [0, 1)."""
        r = self._step()
        return bits_to_dbl((r & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000) - 1.0

    def randint(self, lo: int, hi: int) -> int:
        """``math.random(lo, hi)`` = floor(d * (hi - lo + 1)) + lo."""
        return int(math.floor(self.random() * (hi - lo + 1.0))) + lo

    def random_n(self, n: int) -> int:
        """``math.random(n)`` = floor(d * n) + 1, an integer in 1..n."""
        return int(math.floor(self.random() * n)) + 1


class GameRNG:
    """Per-run pseudo-random state: ``pseudoseed``, ``pseudorandom`` and friends."""

    def __init__(self, seed: str):
        self.seed = seed
        self.hashed_seed = pseudohash(seed)
        self.state: dict[str, float] = {}
        self.lua = LuaRandom(0.0)

    # --- core -----------------------------------------------------------------------------
    def pseudoseed(self, key: str) -> float:
        st = self.state.get(key)
        if st is None:
            st = pseudohash(key + self.seed)
        st = round13(lua_mod1(2.134453429141 + st * 1.72431234))
        self.state[key] = st
        return (st + self.hashed_seed) / 2

    def seeded(self, key: str) -> LuaRandom:
        """``math.randomseed(pseudoseed(key))`` and return the generator."""
        self.lua.seed(self.pseudoseed(key))
        return self.lua

    # --- helpers mirroring the game's pseudorandom* functions -------------------------------
    def random(self, key: str) -> float:
        """``pseudorandom(key)``: a double in [0, 1)."""
        return self.seeded(key).random()

    def randint(self, key: str, lo: int, hi: int) -> int:
        """``pseudorandom(key, lo, hi)``."""
        return self.seeded(key).randint(lo, hi)

    def element_index(self, key: str, n: int) -> int:
        """``pseudorandom_element`` over an n-element list that the game sorts into a known order.
        Returns a 0-based index into that order."""
        return self.seeded(key).random_n(n) - 1

    def shuffle(self, key: str, items: list) -> list:
        """``pseudoshuffle``: Fisher-Yates from the end; ``items`` must already be in sort_id order."""
        out = list(items)
        lr = self.seeded(key)
        for i in range(len(out), 1, -1):
            j = lr.random_n(i)
            out[i - 1], out[j - 1] = out[j - 1], out[i - 1]
        return out
