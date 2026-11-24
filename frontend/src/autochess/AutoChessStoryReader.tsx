import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, ChevronLeft, ChevronRight, LoaderCircle, Search } from 'lucide-react';
import { fetchAutoChessStories, fetchAutoChessStory } from './api';
import type { AutoChessStoryDetail, AutoChessStoryIndexItem } from './types';

type FontSize = 'sm' | 'md' | 'lg';

const FONT_SIZE_KEY = 'ac_story_font_size_v1';
const PROGRESS_KEY = 'ac_story_progress_v1';
const LAST_STORY_KEY = 'ac_story_last_id_v1';

const CATEGORY_ORDER: Array<{ id: string; label: string }> = [
  { id: 'opening', label: '大故事开篇' },
  { id: 'prequel', label: '特别前传' },
  { id: 'character', label: '角色背景故事' },
];

function readProgress(): Record<string, string> {
  try {
    const raw = localStorage.getItem(PROGRESS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function saveProgress(storyId: string, chapterId: string): void {
  try {
    const next = { ...readProgress(), [storyId]: chapterId };
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(next));
    localStorage.setItem(LAST_STORY_KEY, storyId);
  } catch {
    // Ignore storage quota errors in restricted webviews.
  }
}

function readFontSize(): FontSize {
  try {
    const v = localStorage.getItem(FONT_SIZE_KEY);
    return v === 'sm' || v === 'lg' ? v : 'md';
  } catch {
    return 'md';
  }
}

export function AutoChessStoryReader({
  stories: propStories,
  initialStoryId,
  initialChapterId,
  onOpenUnit,
}: {
  stories: AutoChessStoryIndexItem[];
  initialStoryId?: string;
  initialChapterId?: string;
  onOpenUnit?: (serial: string) => void;
}) {
  const [fallbackStories, setFallbackStories] = useState<AutoChessStoryIndexItem[]>([]);
  const stories = propStories.length > 0 ? propStories : fallbackStories;

  const [query, setQuery] = useState('');
  const [fontSize, setFontSize] = useState<FontSize>(() => readFontSize());
  const [activeStoryId, setActiveStoryId] = useState<string>(() => {
    if (initialStoryId) return initialStoryId;
    try {
      const last = localStorage.getItem(LAST_STORY_KEY);
      if (last) return last;
    } catch {
      // ignore
    }
    return propStories[0]?.id || 'opening_fuzhe';
  });
  const [activeChapterId, setActiveChapterId] = useState<string>(() => {
    if (initialChapterId) return initialChapterId;
    if (initialStoryId) return readProgress()[initialStoryId] || '';
    return '';
  });

  const [detail, setDetail] = useState<AutoChessStoryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retryNonce, setRetryNonce] = useState(0);
  const readerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (propStories.length > 0) return;
    let alive = true;
    fetchAutoChessStories()
      .then(list => {
        if (alive) setFallbackStories(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [propStories.length]);

  useEffect(() => {
    if (!stories.length) return;
    if (!stories.some(s => s.id === activeStoryId)) {
      setActiveStoryId(stories[0].id);
    }
  }, [stories, activeStoryId]);

  useEffect(() => {
    if (!initialStoryId) return;
    setActiveStoryId(initialStoryId);
    setActiveChapterId(initialChapterId || readProgress()[initialStoryId] || '');
  }, [initialStoryId, initialChapterId]);

  const currentMeta = useMemo(
    () => stories.find(s => s.id === activeStoryId) || stories[0] || null,
    [stories, activeStoryId],
  );

  useEffect(() => {
    if (!currentMeta) return;
    const validChapterIds = currentMeta.chapters.map(c => c.id);
    const saved = readProgress()[currentMeta.id];
    const targetChapter =
      (activeChapterId && validChapterIds.includes(activeChapterId) && activeChapterId) ||
      (saved && validChapterIds.includes(saved) && saved) ||
      validChapterIds[0] ||
      '';

    if (targetChapter !== activeChapterId) {
      setActiveChapterId(targetChapter);
      return;
    }

    let alive = true;
    setLoading(true);
    setError('');
    fetchAutoChessStory(currentMeta.id, targetChapter || undefined)
      .then(res => {
        if (!alive) return;
        setDetail(res);
        if (res?.active_chapter_id) {
          saveProgress(currentMeta.id, res.active_chapter_id);
        }
      })
      .catch(err => {
        if (alive) setError(err instanceof Error ? err.message : '加载故事失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [currentMeta?.id, activeChapterId, retryNonce]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = !q
      ? stories
      : stories.filter(s =>
          `${s.title} ${s.subtitle || ''} ${s.serial || ''} ${s.unit_name || ''} ${s.summary}`
            .toLowerCase()
            .includes(q),
        );
    return CATEGORY_ORDER.map(cat => ({
      ...cat,
      items: matched.filter(s => s.category === cat.id),
    })).filter(g => g.items.length > 0);
  }, [stories, query]);

  const selectStory = (story: AutoChessStoryIndexItem) => {
    const saved = readProgress()[story.id];
    const valid = story.chapters.some(c => c.id === saved) ? saved : story.chapters[0]?.id || '';
    setActiveStoryId(story.id);
    setActiveChapterId(valid);
    readerRef.current?.scrollTo({ top: 0, behavior: 'auto' });
  };

  const selectChapter = (chapterId: string) => {
    setActiveChapterId(chapterId);
    readerRef.current?.scrollTo({ top: 0, behavior: 'auto' });
  };

  const changeFontSize = (next: FontSize) => {
    setFontSize(next);
    try {
      localStorage.setItem(FONT_SIZE_KEY, next);
    } catch {
      // ignore
    }
  };

  const chapters = detail?.chapters || currentMeta?.chapters || [];
  const activeIdx = Math.max(
    0,
    chapters.findIndex(c => c.id === (detail?.active_chapter_id || activeChapterId)),
  );
  const activeChapter = detail?.chapters?.[activeIdx] || null;
  const paragraphs = activeChapter?.paragraphs || [];

  return (
    <div className="ac-story-layout">
      <aside className="ac-story-sidebar" aria-label="故事阅读目录">
        <div className="ac-wiki-search-wrap ac-story-search">
          <Search size={14} />
          <input
            aria-label="搜索故事或角色"
            placeholder="搜索篇名、棋子或关键词…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>

        <div className="ac-story-toc">
          {!filteredGroups.length ? (
            <div className="muted" style={{ padding: '12px 8px', fontSize: '0.84rem' }}>
              没有匹配的故事篇目
            </div>
          ) : (
            filteredGroups.map(group => (
              <div key={group.id} className="ac-story-group">
                <div className="ac-story-group-title">{group.label}</div>
                {group.items.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    className={`ac-story-item ${currentMeta?.id === item.id ? 'active' : ''}`}
                    onClick={() => selectStory(item)}
                  >
                    <strong>{item.title}</strong>
                    <small className="muted">
                      {item.chapter_count > 1 ? `${item.chapter_count} 节 · ` : ''}
                      {item.word_count.toLocaleString()} 字
                    </small>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </aside>

      <section className="ac-story-reader" ref={readerRef} aria-label="纯文字故事正文">
        {currentMeta ? (
          <>
            <header className="ac-story-toolbar">
              <div className="ac-story-head-copy">
                <div className="ac-story-badges">
                  <span className="ac-story-cat-pill">{currentMeta.category_label}</span>
                  <span className="muted">{currentMeta.word_count.toLocaleString()} 字</span>
                  {currentMeta.chapter_count > 1 && (
                    <span className="muted">共 {currentMeta.chapter_count} 节</span>
                  )}
                </div>
                <h3>{currentMeta.title}</h3>
                {currentMeta.subtitle && <p className="muted">{currentMeta.subtitle}</p>}
              </div>

              <div className="ac-story-controls">
                {currentMeta.serial && onOpenUnit && (
                  <button
                    type="button"
                    className="ac-wiki-trait-btn"
                    onClick={() => onOpenUnit(currentMeta.serial!)}
                  >
                    <BookOpen size={13} /> 查看 {currentMeta.serial} {currentMeta.unit_name || ''} 百科 →
                  </button>
                )}

                <div className="ac-story-font-group" role="group" aria-label="字体大小">
                  {([
                    ['sm', '小'],
                    ['md', '中'],
                    ['lg', '大'],
                  ] as const).map(([sz, lbl]) => (
                    <button
                      key={sz}
                      type="button"
                      className={'ac-wiki-chip ' + (fontSize === sz ? 'active' : '')}
                      onClick={() => changeFontSize(sz)}
                    >
                      {lbl}
                    </button>
                  ))}
                </div>
              </div>
            </header>

            {chapters.length > 1 && (
              <div className="ac-story-chapter-bar">
                <button
                  type="button"
                  className="ac-wiki-chip"
                  disabled={activeIdx <= 0}
                  onClick={() => selectChapter(chapters[activeIdx - 1].id)}
                >
                  <ChevronLeft size={14} /> 上一节
                </button>
                <select
                  aria-label="选择章节"
                  value={chapters[activeIdx]?.id || ''}
                  onChange={e => selectChapter(e.target.value)}
                >
                  {chapters.map((ch, idx) => (
                    <option key={ch.id} value={ch.id}>
                      {idx + 1}. {ch.title}（{ch.word_count.toLocaleString()} 字）
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="ac-wiki-chip"
                  disabled={activeIdx >= chapters.length - 1}
                  onClick={() => selectChapter(chapters[activeIdx + 1].id)}
                >
                  下一节 <ChevronRight size={14} />
                </button>
              </div>
            )}

            <div className={`ac-story-content font-${fontSize}`}>
              {loading && !paragraphs.length ? (
                <div className="ac-story-state">
                  <LoaderCircle size={20} className="spin" />
                  <span>正在加载正文…</span>
                </div>
              ) : error ? (
                <div className="ac-story-state error">
                  <span>{error}</span>
                  <button
                    type="button"
                    className="ac-wiki-chip"
                    onClick={() => setRetryNonce(n => n + 1)}
                  >
                    重试
                  </button>
                </div>
              ) : (
                <>
                  {chapters.length > 1 && activeChapter && (
                    <h4 className="ac-story-chapter-title">{activeChapter.title}</h4>
                  )}
                  {paragraphs.map((p, i) => {
                    if (p.kind === 'divider') {
                      return <hr key={i} className="ac-story-divider" />;
                    }
                    if (p.kind === 'heading') {
                      return (
                        <h5 key={i} className="ac-story-heading">
                          {p.text}
                        </h5>
                      );
                    }
                    if (p.kind === 'quote') {
                      return (
                        <blockquote key={i} className="ac-story-quote">
                          {p.text}
                        </blockquote>
                      );
                    }
                    if (p.kind === 'note') {
                      return (
                        <p key={i} className="ac-story-para ac-story-note">
                          <span>[{p.speaker || '判定'}]</span> {p.text}
                        </p>
                      );
                    }
                    if (p.kind === 'dialogue' && p.speaker) {
                      return (
                        <p key={i} className="ac-story-para ac-story-dialogue">
                          <strong>{p.speaker}：</strong>
                          {p.text}
                        </p>
                      );
                    }
                    return (
                      <p key={i} className="ac-story-para">
                        {p.text}
                      </p>
                    );
                  })}
                </>
              )}
            </div>

            {chapters.length > 1 && (
              <footer className="ac-story-nav">
                <button
                  type="button"
                  className="button subtle compact-button"
                  disabled={activeIdx <= 0}
                  onClick={() => selectChapter(chapters[activeIdx - 1].id)}
                >
                  <ArrowLeft size={14} /> 上一节
                </button>
                <span className="muted">
                  第 {activeIdx + 1} / {chapters.length} 节
                </span>
                <button
                  type="button"
                  className="button subtle compact-button"
                  disabled={activeIdx >= chapters.length - 1}
                  onClick={() => selectChapter(chapters[activeIdx + 1].id)}
                >
                  下一节 <ArrowRight size={14} />
                </button>
              </footer>
            )}
          </>
        ) : (
          <div className="ac-story-state">暂无可阅读的故事内容</div>
        )}
      </section>
    </div>
  );
}
