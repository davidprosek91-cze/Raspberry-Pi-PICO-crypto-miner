/*
   Havirov Coin – těžební firmware pro RPI PICO (a libovolnou Arduino kompatibilní desku)
   Verze 4.0 – bez externích knihoven, vlastní SHA-256 implementace
   Algoritmus: SHA-256d s hledáním nonce (Bitcoin styl)
   API přes USB sériovou linku
*/

#include <Arduino.h>

// ------------------------------------------------------------
//  VLASTNÍ IMPLEMENTACE SHA-256 (public domain)
// ------------------------------------------------------------
#define SHA256_BLOCK_SIZE 32

typedef struct {
  uint8_t data[64];
  uint32_t datalen;
  uint64_t bitlen;
  uint32_t state[8];
} sha256_ctx;

#define ROTLEFT(a,b) (((a) << (b)) | ((a) >> (32-(b))))
#define ROTRIGHT(a,b) (((a) >> (b)) | ((a) << (32-(b))))

#define CH(x,y,z) (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x,y,z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x) (ROTRIGHT(x,2) ^ ROTRIGHT(x,13) ^ ROTRIGHT(x,22))
#define EP1(x) (ROTRIGHT(x,6) ^ ROTRIGHT(x,11) ^ ROTRIGHT(x,25))
#define SIG0(x) (ROTRIGHT(x,7) ^ ROTRIGHT(x,18) ^ ((x) >> 3))
#define SIG1(x) (ROTRIGHT(x,17) ^ ROTRIGHT(x,19) ^ ((x) >> 10))

static const uint32_t K[64] = {
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

void sha256_init(sha256_ctx *ctx) {
  ctx->datalen = 0;
  ctx->bitlen = 0;
  ctx->state[0] = 0x6a09e667;
  ctx->state[1] = 0xbb67ae85;
  ctx->state[2] = 0x3c6ef372;
  ctx->state[3] = 0xa54ff53a;
  ctx->state[4] = 0x510e527f;
  ctx->state[5] = 0x9b05688c;
  ctx->state[6] = 0x1f83d9ab;
  ctx->state[7] = 0x5be0cd19;
}

static void sha256_transform(sha256_ctx *ctx) {
  uint32_t a, b, c, d, e, f, g, h, i, j, t1, t2, m[64];

  for (i = 0, j = 0; i < 16; ++i, j += 4)
    m[i] = (ctx->data[j] << 24) | (ctx->data[j+1] << 16) | (ctx->data[j+2] << 8) | (ctx->data[j+3]);
  for ( ; i < 64; ++i)
    m[i] = SIG1(m[i-2]) + m[i-7] + SIG0(m[i-15]) + m[i-16];

  a = ctx->state[0];
  b = ctx->state[1];
  c = ctx->state[2];
  d = ctx->state[3];
  e = ctx->state[4];
  f = ctx->state[5];
  g = ctx->state[6];
  h = ctx->state[7];

  for (i = 0; i < 64; ++i) {
    t1 = h + EP1(e) + CH(e,f,g) + K[i] + m[i];
    t2 = EP0(a) + MAJ(a,b,c);
    h = g;
    g = f;
    f = e;
    e = d + t1;
    d = c;
    c = b;
    b = a;
    a = t1 + t2;
  }

  ctx->state[0] += a;
  ctx->state[1] += b;
  ctx->state[2] += c;
  ctx->state[3] += d;
  ctx->state[4] += e;
  ctx->state[5] += f;
  ctx->state[6] += g;
  ctx->state[7] += h;
}

void sha256_update(sha256_ctx *ctx, const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; ++i) {
    ctx->data[ctx->datalen] = data[i];
    ctx->datalen++;
    if (ctx->datalen == 64) {
      sha256_transform(ctx);
      ctx->bitlen += 512;
      ctx->datalen = 0;
    }
  }
}

void sha256_final(sha256_ctx *ctx, uint8_t *hash) {
  size_t i = ctx->datalen;
  if (ctx->datalen < 56) {
    ctx->data[i++] = 0x80;
    while (i < 56)
      ctx->data[i++] = 0x00;
  } else {
    ctx->data[i++] = 0x80;
    while (i < 64)
      ctx->data[i++] = 0x00;
    sha256_transform(ctx);
    memset(ctx->data, 0, 56);
  }
  ctx->bitlen += ctx->datalen * 8;
  ctx->data[63] = ctx->bitlen;
  ctx->data[62] = ctx->bitlen >> 8;
  ctx->data[61] = ctx->bitlen >> 16;
  ctx->data[60] = ctx->bitlen >> 24;
  ctx->data[59] = ctx->bitlen >> 32;
  ctx->data[58] = ctx->bitlen >> 40;
  ctx->data[57] = ctx->bitlen >> 48;
  ctx->data[56] = ctx->bitlen >> 56;
  sha256_transform(ctx);

  for (i = 0; i < 4; ++i) {
    hash[i] = (ctx->state[0] >> (24 - i * 8)) & 0x000000ff;
    hash[i+4] = (ctx->state[1] >> (24 - i * 8)) & 0x000000ff;
    hash[i+8] = (ctx->state[2] >> (24 - i * 8)) & 0x000000ff;
    hash[i+12] = (ctx->state[3] >> (24 - i * 8)) & 0x000000ff;
    hash[i+16] = (ctx->state[4] >> (24 - i * 8)) & 0x000000ff;
    hash[i+20] = (ctx->state[5] >> (24 - i * 8)) & 0x000000ff;
    hash[i+24] = (ctx->state[6] >> (24 - i * 8)) & 0x000000ff;
    hash[i+28] = (ctx->state[7] >> (24 - i * 8)) & 0x000000ff;
  }
}
// ------------------------------------------------------------
//  KONEC SHA-256 IMPLEMENTACE
// ------------------------------------------------------------

// Konfigurace
#define BLOCK_SIZE         44    // prevHash(32) + timestamp(8) + nonce(4)
#define DIFFICULTY_BITS    20    // počet úvodních nulových bitů (20 ≈ 1M pokusů)
#define MAX_NONCE_TRIALS   200   // pokusů na jeden průchod loop()

// Globální proměnné
uint8_t block[BLOCK_SIZE];
uint32_t nonce = 0;
uint32_t hashrate = 0;
uint32_t blocksFound = 0;
uint32_t hashCount = 0;
uint32_t lastTime = 0;
uint8_t targetHash[32];          // cílová hodnota (odvozená od obtížnosti)

// Předchozí hash (pro jednoduchost pevný, v reálu by byl dynamický)
uint8_t prevHash[32] = {0};

// ------------------------------------------------------------------
// Výpočet cílové hodnoty podle počtu úvodních nulových bitů
void computeTarget(uint8_t bits) {
  memset(targetHash, 0xFF, 32);
  uint32_t leadingZeros = bits;
  for (uint32_t i = 0; i < leadingZeros / 8; i++) {
    targetHash[i] = 0x00;
  }
  if (leadingZeros % 8 != 0) {
    targetHash[leadingZeros / 8] &= (0xFF << (8 - (leadingZeros % 8)));
  }
}

// ------------------------------------------------------------------
// Ověření, zda hash splňuje obtížnost (hash < target)
bool checkDifficulty(uint8_t *hash) {
  for (int i = 0; i < 32; i++) {
    if (hash[i] > targetHash[i]) return false;
    if (hash[i] < targetHash[i]) return true;
  }
  return true; // rovnost
}

// ------------------------------------------------------------------
// Výpočet dvojitého SHA-256
void doubleSHA256(uint8_t *data, size_t len, uint8_t *out) {
  uint8_t hash1[32];
  sha256_ctx ctx;
  sha256_init(&ctx);
  sha256_update(&ctx, data, len);
  sha256_final(&ctx, hash1);

  sha256_init(&ctx);
  sha256_update(&ctx, hash1, 32);
  sha256_final(&ctx, out);
}

// ------------------------------------------------------------------
// Jeden těžební krok – provede MAX_NONCE_TRIALS pokusů
void mineStep() {
  uint8_t hash[32];
  uint64_t ts = micros();       // 32bit na RP2040, ale postačí
  memcpy(block + 32, &ts, 8);   // timestamp do bloku

  for (int i = 0; i < MAX_NONCE_TRIALS; i++) {
    memcpy(block + 40, &nonce, 4);
    doubleSHA256(block, BLOCK_SIZE, hash);
    hashCount++;

    if (checkDifficulty(hash)) {
      // Blok nalezen!
      blocksFound++;
      Serial.print("BLOCK FOUND! Nonce: ");
      Serial.println(nonce);
      Serial.print("Hash: ");
      for (int j = 0; j < 32; j++) {
        if (hash[j] < 0x10) Serial.print("0");
        Serial.print(hash[j], HEX);
      }
      Serial.println();

      // Po nalezení bloku aktualizujeme timestamp a resetujeme nonce
      ts = micros();
      memcpy(block + 32, &ts, 8);
      nonce = 0;
      continue;
    }

    nonce++;
    if (nonce == 0xFFFFFFFF) {
      nonce = 0;
      ts = micros();
      memcpy(block + 32, &ts, 8);
    }
  }
}

// ------------------------------------------------------------------
// Zpracování příkazů ze sériové linky (API)
void handleSerial() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "PING") {
    Serial.println("PONG");
  }
  else if (cmd == "STATUS") {
    Serial.print("HASHRATE: ");
    Serial.print(hashrate);
    Serial.println(" H/s");
    Serial.print("BLOCKS: ");
    Serial.println(blocksFound);
    Serial.print("DIFFICULTY: ");
    Serial.println(DIFFICULTY_BITS);
  }
  else if (cmd.startsWith("SUBMIT ")) {
    uint32_t submittedNonce = cmd.substring(7).toInt();
    Serial.print("SUBMIT received for nonce: ");
    Serial.println(submittedNonce);
  }
  else if (cmd.startsWith("DIFFICULTY ")) {
    int newBits = cmd.substring(11).toInt();
    if (newBits > 0 && newBits <= 32) {
      computeTarget(newBits);
      Serial.print("Difficulty set to ");
      Serial.println(newBits);
    } else {
      Serial.println("Invalid difficulty (1-32)");
    }
  }
  else {
    Serial.println("Unknown command");
  }
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  // Inicializace bloku – prevHash (pevný)
  memcpy(block, prevHash, 32);
  computeTarget(DIFFICULTY_BITS);
  lastTime = millis();
  Serial.println("Havirov Coin Miner ready");
  Serial.print("Difficulty bits: ");
  Serial.println(DIFFICULTY_BITS);
}

// ------------------------------------------------------------------
void loop() {
  mineStep();

  // Výpočet hashrate (jednou za sekundu)
  uint32_t now = millis();
  if (now - lastTime >= 1000) {
    hashrate = hashCount;
    hashCount = 0;
    lastTime = now;
  }

  handleSerial();
}
