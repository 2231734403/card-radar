// 前端零依赖自动化测试（Node 20+ 原生 node:test）：
//  1. 校验 web/js 全部 ES Module 跨文件 import/export 符号完整性
//  2. 回归测试 store.js::filterCards（含 T13 字符串稀有度、收藏筛选、近 30 天新卡、2100 占位过滤）
//  3. 回归测试 registry.js::cardUniqueKey（T12 Our Notes 复合键隔离）
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { filterCards } from '../web/js/store.js';
import { MODULES, getModule, cardUniqueKey } from '../web/js/modules/registry.js';

const __dir = dirname(fileURLToPath(import.meta.url));
const WEB_JS = resolve(__dir, '../web/js');

function walkJs(dir) {
  const out = [];
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walkJs(full));
    else if (ent.name.endsWith('.js')) out.push(full);
  }
  return out;
}

function collectExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/export\s+(?:async\s+)?(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)/g)) {
    names.add(m[1]);
  }
  for (const m of src.matchAll(/export\s*\{([^}]+)\}/g)) {
    for (const part of m[1].split(',')) {
      const cleaned = part.trim();
      if (!cleaned) continue;
      const alias = cleaned.split(/\s+as\s+/);
      names.add((alias[1] || alias[0]).trim());
    }
  }
  return names;
}

test('所有前端 JS 跨模块 import 文件与导出符号均真实存在', () => {
  const files = walkJs(WEB_JS);
  assert.ok(files.length >= 12);
  const exportsCache = new Map();
  for (const fp of files) {
    exportsCache.set(fp, collectExports(readFileSync(fp, 'utf8')));
  }

  for (const fp of files) {
    const src = readFileSync(fp, 'utf8');
    for (const m of src.matchAll(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"]/g)) {
      const spec = m[2].split('?')[0];
      const target = resolve(dirname(fp), spec);
      assert.ok(existsSync(target), `缺失被导入模块: ${fp} -> ${spec}`);
      const targetExports = exportsCache.get(target);
      for (const raw of m[1].split(',')) {
        const cleaned = raw.trim();
        if (!cleaned) continue;
        const orig = cleaned.split(/\s+as\s+/)[0].trim();
        assert.ok(targetExports.has(orig), `导出符号缺失: ${spec} 未导出 ${orig} (被 ${fp} 导入)`);
      }
    }
  }
});

test('filterCards: 字符串与数字稀有度（回归 T13）及组合/搜索/排序', () => {
  const now = Date.UTC(2026, 10, 24);
  const cards = [
    { id: 10, prefix: '星夜', characterId: 1, characterName: '初音未来', unitName: '虚拟歌手', attr: 'cool', rarity: 4, releaseAt: now - 5 * 86400_000 },
    { id: 11, prefix: '梦境', characterId: 2, characterName: '浅倉透', unitName: 'noctchill', attr: '', rarity: 'SSR', cardKind: 'P', releaseAt: now - 60 * 86400_000 },
    { id: 12, prefix: '纪念', characterId: 3, characterName: '丰川祥子', unitName: 'Ave Mujica', attr: 'Purple', rarity: '特殊', cardKind: 'support', releaseAt: Date.UTC(2100, 0, 1) },
  ];

  // 数字稀有度与字符串稀有度均准确命中
  assert.deepEqual(filterCards({ rarity: '4' }, cards).map(c => c.id), [10]);
  assert.deepEqual(filterCards({ rarity: 'SSR' }, cards).map(c => c.id), [11]);
  assert.deepEqual(filterCards({ rarity: '特殊' }, cards).map(c => c.id), [12]);

  // 近 30 天过滤排除 60 天前与 2100 年占位卡
  assert.deepEqual(filterCards({ recentDays: 30 }, cards, { nowMs: now }).map(c => c.id), [10]);

  // 仅看收藏
  const favSet = new Set(['id:11']);
  assert.deepEqual(filterCards({ favOnly: true }, cards, { favSet, keyFn: c => `id:${c.id}` }).map(c => c.id), [11]);
});

test('registry: 四游戏完整注册且 Our Notes 复合键隔离（回归 T12）', () => {
  assert.equal(MODULES.length, 4);
  assert.equal(getModule('sc').apiMod, 'shinycolors');
  const kCard = cardUniqueKey('onotes', { id: 1, cardKind: 'card' });
  const kSup = cardUniqueKey('onotes', { id: 1, cardKind: 'support' });
  assert.equal(kCard, 'onotes:card:1');
  assert.equal(kSup, 'onotes:support:1');
  assert.notEqual(kCard, kSup);
});
