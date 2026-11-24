"""Read-only loader for Auto-Chess character profiles and pure-text stories."""

import copy
import json
from pathlib import Path
import threading

_DATA_PATH = Path(__file__).resolve().parent / 'data' / 'autochess_stories.json'
_LOCK = threading.RLock()
_CACHE = None


def _load_cache():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        if not _DATA_PATH.exists():
            _CACHE = {'units': {}, 'stories_by_id': {}, 'story_index': []}
            return _CACHE
        raw = json.loads(_DATA_PATH.read_text(encoding='utf-8'))
        units = raw.get('units') or {}
        stories = raw.get('stories') or []
        stories_by_id = {}
        story_index = []
        for st in stories:
            sid = st.get('id')
            if not sid:
                continue
            stories_by_id[sid] = st
            chapters_meta = [
                {
                    'id': ch['id'],
                    'title': ch['title'],
                    'word_count': int(ch.get('word_count', 0) or 0),
                }
                for ch in (st.get('chapters') or ())
            ]
            story_index.append({
                'id': sid,
                'category': st.get('category', 'character'),
                'category_label': st.get('category_label', '角色背景故事'),
                'title': st.get('title', ''),
                'subtitle': st.get('subtitle', ''),
                'serial': st.get('serial'),
                'unit_name': st.get('unit_name'),
                'summary': st.get('summary', ''),
                'word_count': int(st.get('word_count', 0) or 0),
                'is_long': bool(st.get('is_long')),
                'chapter_count': len(chapters_meta),
                'chapters': chapters_meta,
            })
        _CACHE = {
            'units': units,
            'stories_by_id': stories_by_id,
            'story_index': story_index,
        }
        return _CACHE


def get_unit_lore(serial):
    """Return profile fields and short-story/jump metadata for an Auto-Chess unit."""
    cache = _load_cache()
    entry = cache['units'].get(serial)
    return copy.deepcopy(entry) if entry is not None else None


def list_story_index():
    """Return lightweight story metadata without chapter paragraph bodies."""
    cache = _load_cache()
    return copy.deepcopy(cache['story_index'])


def get_story_detail(story_id, chapter_id=None):
    """Return a story entry with chapter bodies populated on demand."""
    cache = _load_cache()
    st = cache['stories_by_id'].get(story_id)
    if st is None:
        return None
    chapters = st.get('chapters') or ()
    if not chapters:
        return None

    if chapter_id is not None:
        chapter_id = str(chapter_id).strip()
        if chapter_id == 'all':
            active_id = chapters[0]['id']
            include_all = True
        else:
            if not any(ch['id'] == chapter_id for ch in chapters):
                return None
            active_id = chapter_id
            include_all = False
    else:
        active_id = chapters[0]['id']
        include_all = int(st.get('word_count', 0) or 0) <= 15000

    out_chapters = []
    for ch in chapters:
        item = {
            'id': ch['id'],
            'title': ch['title'],
            'word_count': int(ch.get('word_count', 0) or 0),
        }
        if include_all or ch['id'] == active_id:
            item['paragraphs'] = copy.deepcopy(ch.get('paragraphs') or [])
        out_chapters.append(item)

    return {
        'id': st['id'],
        'category': st.get('category', 'character'),
        'category_label': st.get('category_label', '角色背景故事'),
        'title': st.get('title', ''),
        'subtitle': st.get('subtitle', ''),
        'serial': st.get('serial'),
        'unit_name': st.get('unit_name'),
        'summary': st.get('summary', ''),
        'word_count': int(st.get('word_count', 0) or 0),
        'is_long': bool(st.get('is_long')),
        'chapter_count': len(out_chapters),
        'active_chapter_id': active_id,
        'chapters': out_chapters,
    }
