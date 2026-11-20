import { blake2AsU8a, signatureVerify, cryptoWaitReady } from '@polkadot/util-crypto';

export async function verifyPayloadSignature(registry, payload, signature, sender) {
  await cryptoWaitReady();
  const encoded = registry.createType('ExtrinsicPayload', payload, { version: payload.version });
  const bytes = encoded.toU8a({ method: true });
  return signatureVerify(bytes.length > 256 ? blake2AsU8a(bytes) : bytes, signature, sender).isValid;
}
