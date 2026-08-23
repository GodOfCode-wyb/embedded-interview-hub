'use client';

import { useMemo, useState } from 'react';
import questionData from '../content/questions.json';
import experienceData from '../content/experiences.json';
import sourceData from '../content/sources.json';
import updateData from '../content/updates.json';

type QuestionStatus = 'source-only' | 'ai-draft' | 'reviewed' | 'verified' | 'outdated';
type View = 'questions' | 'experiences' | 'sources';

type Question = {
  id: string;
  title: string;
  domain: string;
  subtopic: string;
  difficulty: string;
  answer_short: string;
  answer_detail: string;
  follow_ups: string[];
  pitfalls: string[];
  tags: string[];
  source_ids: string[];
  status: QuestionStatus;
  updated_at: string;
};

type Experience = {
  id: string;
  company: string | null;
  role: string;
  round: string;
  date: string | null;
  summary: string;
  question_ids: string[];
  source_id: string;
};

type Source = {
  id: string;
  title: string;
  kind: string;
  url: string | null;
  trust: string;
};

const questions = questionData as Question[];
const experiences = experienceData as Experience[];
const sources = sourceData as Source[];
const statusLabel: Record<QuestionStatus, string> = {
  'source-only': '仅来源',
  'ai-draft': 'AI 草稿',
  reviewed: '已整理',
  verified: '已核验',
  outdated: '待更新',
};

const viewLabel: Record<View, string> = {
  questions: '题目索引',
  experiences: '面经来源',
  sources: '资料与更新',
};

function normalize(value: string) {
  return value.trim().toLocaleLowerCase('zh-CN');
}

export default function Home() {
  const [view, setView] = useState<View>('questions');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('全部');
  const [difficulty, setDifficulty] = useState('全部难度');
  const [selectedId, setSelectedId] = useState(questions[0].id);

  const categories = useMemo(
    () => ['全部', ...Array.from(new Set(questions.map((item) => item.domain)))],
    [],
  );

  const filteredQuestions = useMemo(() => {
    const keyword = normalize(query);
    return questions.filter((item) => {
      const matchesCategory = category === '全部' || item.domain === category;
      const matchesDifficulty = difficulty === '全部难度' || item.difficulty === difficulty;
      const haystack = normalize([
        item.title,
        item.answer_short,
        item.answer_detail,
        item.domain,
        item.subtopic,
        ...item.tags,
      ].join(' '));
      return matchesCategory && matchesDifficulty && (!keyword || haystack.includes(keyword));
    });
  }, [category, difficulty, query]);

  const filteredExperiences = useMemo(() => {
    const keyword = normalize(query);
    return experiences.filter((item) => !keyword || normalize([
      item.company ?? '公司未记录',
      item.role,
      item.round,
      item.summary,
    ].join(' ')).includes(keyword));
  }, [query]);

  const filteredSources = useMemo(() => {
    const keyword = normalize(query);
    return sources.filter((item) => !keyword || normalize([
      item.title,
      item.kind,
      item.trust,
    ].join(' ')).includes(keyword));
  }, [query]);

  const selected = filteredQuestions.find((item) => item.id === selectedId) ?? filteredQuestions[0];
  const sourceMap = new Map(sources.map((source) => [source.id, source]));

  function switchView(nextView: View) {
    setView(nextView);
    setQuery('');
  }

  return (
    <main className="site-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="嵌入式面试知识库首页">
          <span className="brand-mark">E</span>
          <span>
            <strong>Embedded Interview</strong>
            <small>嵌入式面试知识库</small>
          </span>
        </a>
        <nav className="topnav" aria-label="主要页面">
          {(Object.keys(viewLabel) as View[]).map((item) => (
            <button
              className={view === item ? 'nav-button active' : 'nav-button'}
              key={item}
              onClick={() => switchView(item)}
              type="button"
            >
              {viewLabel[item]}
            </button>
          ))}
        </nav>
        <div className="topbar-meta">
          <span className="live-dot" />
          持续整理公开面经
        </div>
      </header>

      <section className="hero" id="top">
        <p className="eyebrow">INTERVIEW KNOWLEDGE INDEX · 2026</p>
        <h1>把零散面经，整理成<br />可检索的嵌入式知识体系。</h1>
        <p className="hero-copy">
          聚焦 C/C++、STM32、RTOS、操作系统、计算机网络与 Linux 驱动；
          每道题保留简答、详解、追问和来源。
        </p>
        <label className="search-box">
          <span aria-hidden="true">⌕</span>
          <span className="sr-only">搜索{viewLabel[view]}</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={view === 'questions'
              ? '搜索：中断、DMA、虚函数、TCP……'
              : view === 'experiences'
                ? '搜索：公司、岗位、Camera……'
                : '搜索：Linux、FreeRTOS、标准……'}
          />
          <kbd>实时筛选</kbd>
        </label>
        <div className="hero-stats" aria-label="题库统计">
          <span><strong>{String(questions.length).padStart(2, '0')}</strong> 首批整理题</span>
          <span><strong>{categories.length - 1}</strong> 知识方向</span>
          <span><strong>{experiences.length}</strong> 组原始面经</span>
          <span><strong>{sources.filter((item) => item.url).length}</strong> 项外部资料</span>
        </div>
      </section>

      {view === 'questions' && (
        <section className="workspace" aria-label="知识库浏览区">
          <aside className="category-panel">
            <p className="panel-label">知识分类</p>
            <nav aria-label="题目分类">
              {categories.map((item) => {
                const count = item === '全部'
                  ? questions.length
                  : questions.filter((question) => question.domain === item).length;
                return (
                  <button
                    className={category === item ? 'category-button active' : 'category-button'}
                    key={item}
                    onClick={() => setCategory(item)}
                    type="button"
                  >
                    <span>{item}</span>
                    <b>{String(count).padStart(2, '0')}</b>
                  </button>
                );
              })}
            </nav>
            <div className="source-note">
              <span>采集原则</span>
              <p>保留原始链接与面试背景，不整篇转载，不把 AI 草稿伪装成真实面经。</p>
            </div>
          </aside>

          <section className="question-panel">
            <div className="section-heading">
              <div>
                <p className="panel-label">题目索引</p>
                <h2>{category === '全部' ? '全部高频题' : category}</h2>
              </div>
              <label className="difficulty-filter">
                <span className="sr-only">难度筛选</span>
                <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
                  <option>全部难度</option>
                  <option>基础</option>
                  <option>进阶</option>
                </select>
                <span>{filteredQuestions.length} 条结果</span>
              </label>
            </div>

            <div className="question-list">
              {filteredQuestions.map((item, index) => (
                <button
                  className={selected?.id === item.id ? 'question-card selected' : 'question-card'}
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  type="button"
                >
                  <span className="question-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="question-body">
                    <small>{item.domain} · {item.subtopic} · {item.difficulty}</small>
                    <strong>{item.title}</strong>
                    <span className="tag-row">
                      {item.tags.slice(0, 4).map((tag) => <i key={tag}>#{tag}</i>)}
                    </span>
                  </span>
                  <span className="question-arrow" aria-hidden="true">↗</span>
                </button>
              ))}
              {filteredQuestions.length === 0 && (
                <div className="empty-state">
                  <strong>没有找到匹配题目</strong>
                  <p>换一个关键词或筛选条件。</p>
                </div>
              )}
            </div>
          </section>

          <aside className="answer-panel" aria-live="polite">
            {selected ? (
              <>
                <p className="panel-label">快速复习</p>
                <div className="answer-badges">
                  <span className="answer-category">{selected.domain}</span>
                  <span className={`status-badge ${selected.status}`}>{statusLabel[selected.status]}</span>
                </div>
                <h2>{selected.title}</h2>
                <div className="answer-block">
                  <small>30 秒简答</small>
                  <p>{selected.answer_short}</p>
                </div>
                <div className="answer-block detail-section">
                  <small>展开回答</small>
                  <p>{selected.answer_detail}</p>
                </div>
                <div className="follow-up">
                  <small>面试官可能追问</small>
                  <ul>
                    {selected.follow_ups.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div className="pitfall-block">
                  <small>容易踩坑</small>
                  <p>{selected.pitfalls[0]}</p>
                </div>
                <footer>
                  <span>来源与参考</span>
                  <div className="source-links">
                    {selected.source_ids.map((sourceId) => {
                      const source = sourceMap.get(sourceId);
                      if (!source) return null;
                      return source.url ? (
                        <a key={sourceId} href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a>
                      ) : <p key={sourceId}>{source.title}</p>;
                    })}
                  </div>
                  <p>更新于 {selected.updated_at}</p>
                </footer>
              </>
            ) : (
              <div className="empty-state"><strong>选择一道题查看答案</strong></div>
            )}
          </aside>
        </section>
      )}

      {view === 'experiences' && (
        <section className="content-view">
          <header className="content-heading">
            <div><p className="panel-label">INTERVIEW LOGS</p><h2>真实面经索引</h2></div>
            <p>只整理来源中明确出现的信息；公司、时间和结果缺失时保持未知。</p>
          </header>
          <div className="experience-grid">
            {filteredExperiences.map((experience) => (
              <article className="experience-card" key={experience.id}>
                <div className="experience-meta">
                  <span>{experience.date ?? '日期未记录'}</span>
                  <span>{experience.round}</span>
                </div>
                <p className="company-name">{experience.company ?? '公司未记录'}</p>
                <h3>{experience.role}</h3>
                <p className="experience-summary">{experience.summary}</p>
                <div className="experience-questions">
                  <small>收录 {experience.question_ids.length} 道题</small>
                  {experience.question_ids.slice(0, 4).map((questionId) => {
                    const question = questions.find((item) => item.id === questionId);
                    return question ? <span key={questionId}>{question.title}</span> : null;
                  })}
                </div>
                <footer>{sourceMap.get(experience.source_id)?.title}</footer>
              </article>
            ))}
          </div>
        </section>
      )}

      {view === 'sources' && (
        <section className="content-view">
          <header className="content-heading">
            <div><p className="panel-label">PROVENANCE & CHANGELOG</p><h2>资料与更新</h2></div>
            <p>官方资料用于核验答案，公开面经用于统计问题出现情况，两者不混为一谈。</p>
          </header>
          <div className="source-layout">
            <div className="source-grid">
              {filteredSources.map((source) => (
                <article className="source-card" key={source.id}>
                  <div><span className="source-kind">{source.kind}</span><small>{source.trust}</small></div>
                  <h3>{source.title}</h3>
                  {source.url
                    ? <a href={source.url} target="_blank" rel="noreferrer">访问原始资料 ↗</a>
                    : <p>来自本地原始面试笔记</p>}
                </article>
              ))}
            </div>
            <aside className="updates">
              <p className="panel-label">更新记录</p>
              {updateData.map((update) => (
                <article className="update-row" key={`${update.date}-${update.title}`}>
                  <time>{update.date}</time>
                  <h3>{update.title}</h3>
                  <p>{update.description}</p>
                </article>
              ))}
            </aside>
          </div>
        </section>
      )}
    </main>
  );
}
