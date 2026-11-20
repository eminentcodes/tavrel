/** Explicitly refresh static product screenshots through the real gateway workflow.
 * This uses a test wallet and an isolated empty ledger; it does not seed the running app.
 * Run npm run build after updating the assets.
 */
import { copyFile } from 'node:fs/promises';

await import('./check-frontend.mjs');
await copyFile('artifacts/ui/payment-review.png', 'frontend/public/payment-preview.png');
await copyFile('artifacts/ui/ledger.png', 'frontend/public/ledger-preview.png');
process.stdout.write('Updated static payment review and ledger images. Rebuild to include them.\n');
