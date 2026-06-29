/**
 * Ed25519 signing — the shared trust anchor.
 *
 * Mirrors Tomorrow's C1 verifiable-proof approach so every product in the
 * portfolio signs and verifies on the SAME asymmetric scheme: a third party can
 * verify a receipt/passport with only the embedded public key — no shared secret,
 * no call home. This is the difference between "trust me" and "verify it yourself."
 *
 * Key resolution:
 *   - env DARWIN_SIGNING_PRIVATE_KEY_PEM (Ed25519 PKCS8 PEM) = the stable prod anchor.
 *   - otherwise an ephemeral per-process keypair is generated (proofs still
 *     self-verify via their embedded key, but the anchor is not stable — set the
 *     env var in production).
 *   - DARWIN_SIGNING_DISABLED=true => content-addressed only (algorithm 'none').
 */
import {
  generateKeyPairSync,
  sign as nodeSign,
  verify as nodeVerify,
  createPublicKey,
  createPrivateKey,
  type KeyObject,
} from 'node:crypto';

export type SignatureAlgorithm = 'ed25519' | 'none';

export interface Signature {
  algorithm: SignatureAlgorithm;
  /** base64 signature ('' when algorithm is 'none') */
  value: string;
  /** SPKI PEM of the public key, embedded so verification needs no external state */
  publicKeyPem: string;
}

let cachedPrivate: KeyObject | null = null;
let cachedPublicPem: string | null = null;

function loadKeys(): { priv: KeyObject | null; pubPem: string } {
  if (process.env.DARWIN_SIGNING_DISABLED === 'true') {
    return { priv: null, pubPem: '' };
  }
  if (cachedPrivate && cachedPublicPem) {
    return { priv: cachedPrivate, pubPem: cachedPublicPem };
  }
  const pem = process.env.DARWIN_SIGNING_PRIVATE_KEY_PEM;
  if (pem) {
    cachedPrivate = createPrivateKey(pem);
  } else {
    const { privateKey } = generateKeyPairSync('ed25519');
    cachedPrivate = privateKey;
  }
  cachedPublicPem = createPublicKey(cachedPrivate).export({ type: 'spki', format: 'pem' }).toString();
  return { priv: cachedPrivate, pubPem: cachedPublicPem };
}

/** The published trust anchor (SPKI PEM). Verifiers pin this and confirm a
 *  proof's embedded key matches it. Empty string when signing is disabled. */
export function getPublicKeyPem(): string {
  return loadKeys().pubPem;
}

/** Sign a digest string. Returns an algorithm 'none' signature if disabled. */
export function signDigest(digestHex: string): Signature {
  const { priv, pubPem } = loadKeys();
  if (!priv) return { algorithm: 'none', value: '', publicKeyPem: '' };
  const value = nodeSign(null, Buffer.from(digestHex), priv).toString('base64');
  return { algorithm: 'ed25519', value, publicKeyPem: pubPem };
}

/**
 * Stateless verification: recompute nothing here — just check that the signature
 * validates against the public key EMBEDDED in the signature. Callers first
 * recompute the digest from public inputs, then call this.
 */
export function verifyDigest(digestHex: string, sig: Signature): boolean {
  if (sig.algorithm === 'none') return true; // content-addressed only; integrity checked by hash
  if (!sig.publicKeyPem || !sig.value) return false;
  try {
    const pub = createPublicKey(sig.publicKeyPem);
    return nodeVerify(null, Buffer.from(digestHex), pub, Buffer.from(sig.value, 'base64'));
  } catch {
    return false;
  }
}
