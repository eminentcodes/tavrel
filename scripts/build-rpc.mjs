import { build } from 'esbuild';
await build({ entryPoints: ['tavrel/native_rpc.mjs', 'tavrel/wallet_verify.mjs'],
  bundle: true, platform: 'node', target: 'node22', format: 'esm',
  outdir: 'tavrel', outExtension: { '.js': '.bundle.mjs' }, logLevel: 'warning',
  banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);" } });
console.log('Native RPC and wallet verifier bundled.');
