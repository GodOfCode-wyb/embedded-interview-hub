import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(root, 'content', name), 'utf8'));
const questions = readJson('questions.json');
const sources = readJson('sources.json');
const experiences = readJson('experiences.json');
const updates = readJson('updates.json');
const errors = [];
const allowedStatuses = new Set(['source-only', 'ai-draft', 'reviewed', 'verified', 'outdated']);

function uniqueIds(records, label) {
  const seen = new Set();
  for (const record of records) {
    if (!record.id || typeof record.id !== 'string') errors.push(`${label}: 缺少字符串 id`);
    else if (seen.has(record.id)) errors.push(`${label}: 重复 id ${record.id}`);
    seen.add(record.id);
  }
  return seen;
}

const questionIds = uniqueIds(questions, 'questions');
const sourceIds = uniqueIds(sources, 'sources');
uniqueIds(experiences, 'experiences');

for (const item of questions) {
  for (const key of ['title', 'domain', 'subtopic', 'difficulty', 'answer_short', 'answer_detail', 'updated_at']) {
    if (!item[key] || typeof item[key] !== 'string') errors.push(`${item.id}: ${key} 缺失`);
  }
  for (const key of ['follow_ups', 'pitfalls', 'tags', 'source_ids']) {
    if (!Array.isArray(item[key])) errors.push(`${item.id}: ${key} 必须是数组`);
  }
  for (const followUp of item.follow_ups ?? []) {
    if (typeof followUp === 'string') continue;
    if (!followUp || typeof followUp !== 'object'
      || !followUp.title || !followUp.answer_short || !followUp.answer_detail) {
      errors.push(`${item.id}: 结构化追问必须包含 title、answer_short、answer_detail`);
    }
  }
  for (const pitfall of item.pitfalls ?? []) {
    if (typeof pitfall === 'string') continue;
    if (!pitfall || typeof pitfall !== 'object'
      || !pitfall.title || !pitfall.explanation || !pitfall.correction) {
      errors.push(`${item.id}: 结构化踩坑项必须包含 title、explanation、correction`);
    }
  }
  if ((item.answer_version ?? 0) >= 2) {
    if (String(item.answer_detail ?? '').length < 250) errors.push(`${item.id}: 新版详解过短`);
    if (item.follow_ups.length < 2 || item.follow_ups.some((value) => typeof value !== 'object')) {
      errors.push(`${item.id}: 新版答案至少需要 2 个带答案追问`);
    }
    if (item.pitfalls.length < 1 || item.pitfalls.some((value) => typeof value !== 'object')) {
      errors.push(`${item.id}: 新版答案至少需要 1 个结构化踩坑项`);
    }
  }
  if (!allowedStatuses.has(item.status)) errors.push(`${item.id}: 非法状态 ${item.status}`);
  for (const sourceId of item.source_ids ?? []) {
    if (!sourceIds.has(sourceId)) errors.push(`${item.id}: 来源不存在 ${sourceId}`);
  }
  if (item.status === 'verified' && (item.source_ids ?? []).length === 0) {
    errors.push(`${item.id}: verified 题目必须有来源`);
  }
}

for (const item of experiences) {
  if (!item.role || !item.round || !item.summary) errors.push(`${item.id}: 面经必要字段缺失`);
  if (!sourceIds.has(item.source_id)) errors.push(`${item.id}: 面经来源不存在 ${item.source_id}`);
  for (const questionId of item.question_ids ?? []) {
    if (!questionIds.has(questionId)) errors.push(`${item.id}: 题目不存在 ${questionId}`);
  }
}

for (const item of updates) {
  if (!item.date || !item.title || !item.description) errors.push('updates: 更新记录字段缺失');
}

if (errors.length) {
  console.error(`内容校验失败（${errors.length} 项）`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(`内容校验通过：${questions.length} 道题、${experiences.length} 组面经、${sources.length} 个来源。`);
