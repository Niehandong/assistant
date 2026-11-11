// 依次拉取三个服务的 /openapi.json 并生成 src/services/types/{iam,kb,open}.d.ts。
// 服务未启动则跳过并提示（退出码 0）。
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bin = path.join(root, 'node_modules', '.bin', 'openapi-typescript');

const services = [
  { name: 'iam', url: process.env.IAM_URL ?? 'http://127.0.0.1:8301' },
  { name: 'kb', url: process.env.KB_URL ?? 'http://127.0.0.1:8302' },
  { name: 'open', url: process.env.OPEN_URL ?? 'http://127.0.0.1:8303' },
];

for (const { name, url } of services) {
  const spec = `${url}/openapi.json`;
  try {
    const res = await fetch(spec, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.warn(`[gen:api] 跳过 ${name}：无法访问 ${spec}（${err.message}），请先启动服务`);
    continue;
  }
  const out = path.join(root, 'src', 'services', 'types', `${name}.d.ts`);
  execFileSync(bin, [spec, '-o', out], { stdio: 'inherit' });
  console.log(`[gen:api] 已生成 ${out}`);
}
