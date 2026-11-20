/** Read-only fee/signing-payload integration check. Does not sign or submit. */
import { spawn } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
const child = spawn(process.execPath, ['tavrel/native_rpc.bundle.mjs'], { windowsHide: true, env: { ...process.env, TAVREL_RPC_DIAGNOSTIC: '1' } });
let output = ''; let errors = '';
child.stdout.on('data', data => { output += data; });
child.stderr.on('data', data => { errors += data; });
child.stdin.end(JSON.stringify({ action: 'quote',
  genesis_hash: '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242',
  payment: { sender: '0xd43593c715fdd31c61141abd04a99fd6822c8558854ccde39a5684e7a56da27d',
    recipient: '0x' + '12'.repeat(32), amount_units: '1' } }));
const timer = setTimeout(() => child.kill(), 50000);
const code = await new Promise(resolve => child.on('exit', resolve));
clearTimeout(timer);
if (code !== 0) throw new Error('Native RPC check failed: ' + output + '\n' + errors);
const result = JSON.parse(output).result;
if (!result?.payload || !result.fee_units || result.expires_height <= result.finalized_height) throw new Error('Missing quote/signing payload.');
await writeFile('artifacts/native-rpc-check.json', JSON.stringify({ observed_at: new Date().toISOString(),
  check: 'Read-only real Volta fee and signing-payload preparation', ...result,
  transfer_signed: false, transfer_submitted: false }, null, 2) + '\n');
console.log(JSON.stringify(result));
