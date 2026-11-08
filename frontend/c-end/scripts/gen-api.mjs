#!/usr/bin/env node
/**
 * 从后端 openapi.json 生成 TypeScript 类型。
 *
 * 流程：
 *   1. 若 backend/openapi.json 不存在，先调用后端脚本导出
 *   2. 用 openapi-typescript 生成到 src/types/api-generated.d.ts
 *   3. 在文件头写入 auto-generated 标记
 *
 * 为什么读本地文件而不是 http://localhost:8000/openapi.json：
 *   生成类型不应依赖后端服务正在运行，否则 CI 和刚克隆仓库的人都跑不了。
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(here, '..', '..', '..'); // frontend/c-end/scripts -> repo root
const schemaPath = join(projectRoot, 'backend', 'openapi.json');
const outPath = join(here, '..', 'src', 'types', 'api-generated.d.ts');

const BANNER = `/**
 * AUTO-GENERATED FILE - DO NOT EDIT.
 *
 * 由 \`npm run gen:api\` 从 backend/openapi.json 生成。
 * 任何手工修改都会在下次生成时被覆盖。
 *
 * 如需调整类型，请修改后端 Pydantic 模型或 app/schemas/ 下的定义。
 */
`;

function ensureSchema() {
  if (existsSync(schemaPath)) {
    console.log(`✓ 使用已有 schema: ${schemaPath}`);
    return;
  }

  console.log('· 未找到 openapi.json，正在从后端导出…');
  try {
    execFileSync('uv', ['run', 'python', 'scripts/export_openapi.py'], {
      cwd: join(projectRoot, 'backend'),
      stdio: 'inherit',
    });
  } catch (error) {
    console.error('✗ 导出失败。请在 backend 目录手动执行：uv run python scripts/export_openapi.py');
    process.exit(1);
  }

  if (!existsSync(schemaPath)) {
    console.error(`✗ 导出后仍未找到 ${schemaPath}`);
    process.exit(1);
  }
}

function generate() {
  mkdirSync(dirname(outPath), { recursive: true });
  execFileSync('npx', ['openapi-typescript', schemaPath, '-o', outPath], {
    cwd: join(here, '..'),
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });

  // openapi-typescript 不会写自定义文件头，这里补上 auto-generated 标记
  const generated = readFileSync(outPath, 'utf8');
  if (!generated.includes('AUTO-GENERATED FILE')) {
    writeFileSync(outPath, BANNER + generated, 'utf8');
  }
}

function summarize() {
  const schema = JSON.parse(readFileSync(schemaPath, 'utf8'));
  const paths = Object.keys(schema.paths ?? {}).length;
  const models = Object.keys(schema.components?.schemas ?? {}).length;
  console.log(`✓ 已生成 ${outPath}`);
  console.log(`  路径 ${paths} 个，数据模型 ${models} 个`);
}

ensureSchema();
generate();
summarize();
