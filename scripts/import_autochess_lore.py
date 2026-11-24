#!/usr/bin/env python3
"""Offline importer that builds backend/data/autochess_stories.json from docs and card files.

Usage:
    python scripts/import_autochess_lore.py          # Parse sources, write JSON, validate
    python scripts/import_autochess_lore.py --check  # Validate existing JSON without modifying
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / 'docs'
ATT_DIR = DOCS_DIR / '附件'
PREQUEL_PATH = Path(r'D:\Datastruct\luoguc\The100daysFinale\歌词1121\歌词夹\目录与背景故事\背景故事-前传.txt')
OUT_PATH = ROOT / 'backend' / 'data' / 'autochess_stories.json'

UNIT_NAMES = {
    'Y1': '炎焱',
    'Y2': '达尼厄斯',
    'Y3': '灵牛',
    'Y4': '星闪',
    'Y5': '血天使',
    'Y6': '雪人',
    'Y7': '环花暖',
    'Y8': '比哈米',
    'Y9': '木落-荣枯',
    'Y10': '春晌',
    'Y11': '蓝',
    'Y12': '斯瑞提卡',
    'Y13': '“巨人”',
    'Y14': '余烬',
    'Y15': '葬火',
    'Y16': '罗杰',
    'Y17': '夜诏明',
    'Y18': '夕歌谣梦',
    'Y19': '木落-焚秋',
}


def _clean_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip(' \t\u3000') for line in text.split('\n')]
    # Collapse excessive blank lines to at most one blank line.
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1 and out:
                out.append('')
        else:
            blank_run = 0
            out.append(line.strip() if line.startswith('\t') else line)
    while out and not out[-1].strip():
        out.pop()
    return '\n'.join(out).strip()


def _unwrap_soft_lines(text: str) -> str:
    """Join lines that were hard-wrapped at a fixed column inside a cell or text block."""
    raw = text.replace('\r\n', '\n').replace('\r', '\n')
    out: list[str] = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            if out and out[-1] != '':
                out.append('')
            continue
        if re.fullmatch(r'[—\-_=]{6,}', s):
            out.append(s)
            continue
        if out and out[-1] and not re.fullmatch(r'[—\-_=]{6,}', out[-1]):
            prev = out[-1]
            # Keep intentional line break after standalone dialogue/quote or heading
            is_dialogue_break = prev.endswith(('”', '」')) or s.startswith(('“', '「'))
            is_term = prev[-1] in '。！？…”」》：'
            if not is_term or (s and s[0] in '。，！？；：、”」'):
                if not is_dialogue_break or (s and s[0] in '。，！？；：、”」'):
                    out[-1] = prev + s
                    continue
        out.append(s)
    return '\n'.join(out).strip()


def _text_to_paragraphs(text: str, kind: str = 'narrator') -> list[dict]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    paras = []
    for raw_line in cleaned.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r'[—\-_=]{6,}', line):
            paras.append({'kind': 'divider', 'text': '──────────'})
        else:
            paras.append({'kind': kind, 'text': line})
    return paras


def _count_chars(paragraphs: list[dict]) -> int:
    total = 0
    for p in paragraphs:
        if p.get('kind') == 'divider':
            continue
        total += len(p.get('text', ''))
        if p.get('speaker'):
            total += len(p['speaker'])
    return total


def _make_excerpt(text: str, limit: int = 135) -> str:
    flat = re.sub(r'\s+', ' ', text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    for sep in ('。', '！', '？', '……', '；', '，'):
        idx = cut.rfind(sep)
        if idx >= limit // 2:
            return cut[:idx + 1] + '……'
    return cut.rstrip('，、 ') + '……'


def _parse_juqing_txt(path: Path) -> dict[str, dict]:
    """Parse unit blocks Y1..Y17 from docs/剧情.txt."""
    raw = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    lines = raw.split('\n')

    blocks: dict[str, list[str]] = {}
    current_serial: str | None = None
    for line in lines:
        m = re.match(r'^(Y\d+)\s+(.+?)\s*$', line)
        if m:
            current_serial = m.group(1)
            blocks[current_serial] = []
            continue
        if current_serial is not None:
            if line.strip() == '自走棋模式' or line.startswith('Y14-17的背景故事'):
                current_serial = None
                continue
            blocks[current_serial].append(line)

    parsed: dict[str, dict] = {}
    field_keys = (
        '原名', '年龄', '学校', '班级', '年级', '社团', '外貌',
        '成为魔法少女的时间', '退出魔法少女的时间',
        '退出魔法少女（■■■）的时间', '退出魔法少女（■■）的时间',
        '背景故事简介', '背景故事', '友人', '讨厌的人', '特殊关系',
    )
    for serial, blines in blocks.items():
        fields: list[tuple[str, str]] = []
        cur_k: str | None = None
        cur_vals: list[str] = []

        def _flush():
            nonlocal cur_k, cur_vals
            if cur_k is not None:
                if cur_k == '外貌':
                    val = _unwrap_soft_lines('\n'.join(v.strip() for v in cur_vals if v.strip()))
                else:
                    val = '\n'.join(v.strip() for v in cur_vals if v.strip()).strip()
                fields.append((cur_k, val))
            cur_k = None
            cur_vals = []

        for line in blines:
            stripped = line.strip()
            if not stripped:
                if cur_k in ('背景故事', '背景故事简介') and cur_vals:
                    cur_vals.append('')
                continue
            # Ignore internal draft notes in brackets.
            if stripped.startswith('（Y5-Y13暂时预设') or stripped == '（由角色卡获得）':
                continue
            matched = False
            for k in field_keys:
                for sep in ('：', ':'):
                    prefix = f'{k}{sep}'
                    if stripped.startswith(prefix):
                        _flush()
                        cur_k = k
                        rest = stripped[len(prefix):].strip()
                        if rest:
                            cur_vals.append(rest)
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                if cur_k is not None:
                    cur_vals.append(stripped)
        _flush()
        parsed[serial] = {'fields': fields}
    return parsed


def _load_pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return [(pg.extract_text() or '') for pg in reader.pages]


def _extract_pdf_supplemental(pages: list[str]) -> dict[str, dict]:
    """Extract verified appearance & early-timeline backstory for Y5-Y8, Y10, Y12."""
    full = '\n'.join(pages)
    # Sanity-check expected markers in PDF so we don't silently drift from source.
    assert '血天使（张小花）' in full
    assert '雪人（李欣怡）' in full
    assert '环花暖（姜阮阮）' in full
    assert '比哈米（尤嘉怡）' in full
    assert '斯瑞提卡' in full

    return {
        'Y5': {
            'story': (
                '血天使是完完全全的小朋友性格，说话习惯比较简单，一般不会说出太复杂的语句。'
                '她从小母亲去世，由父亲带大，家里清贫，父亲是一名屠户，因为不擅社交很少有人雇他帮忙。\n'
                '当瓦尔出现在她面前询问是否愿意成为魔法少女时，张小花几乎没加思索便答应下来，连“血天使”这个名字都是瓦尔替她取的。'
                '刚成为魔法少女时她对新世界既好奇又局促，如今在同伴们的影响下，从天而降时已学会保持优雅端庄——'
                '只是偶尔仍会保持把馒头带回家分给父亲的小习惯。'
            ),
        },
        'Y6': {
            'appearance': (
                '较矮。人如其名，看起来就像是用雪堆起来的雪人一样，头上戴着可爱的方形雪人帽子，'
                '上面还有一根黄色的胡萝卜装饰。配色以白色为主，浅蓝色为点缀。'
            ),
            'story': (
                '性格偏向冒失、大大咧咧，口头禅是“啊啊啊啊啊”，常脱口而出“啊啊啊啊啊怎么会这样”“啊啊啊不会吧！”。\n'
                '她出生在富裕家庭，家住别墅区，算得上是一位大小姐；不过平日里并无太多条条框框的拘束，'
                '行为举止毫无大小姐架子，只是最基本的礼貌底线依然能守得住。'
            ),
        },
        'Y7': {
            'age': '14',
            'appearance': (
                '身高中等（约 150~160 cm）；未变身时是穿着简单、便于行动日常服的普通中学生。'
                '变身后身着由花朵堆叠而成的服饰，以黄色与粉色为主调，留着并不张扬的黑色头发，可以通过发箍上的花朵释放能力。'
            ),
            'story': (
                '家庭背景普通，在长辈面前十分乖巧，面对后辈时常会摆出一副可靠前辈的姿态，'
                '但言行多出于善意与照拂。\n'
                '她性格温和善良、有礼貌且善解人意，在同伴需要时总是勇敢挺身而出，是非常典型的传统魔法少女。'
            ),
        },
        'Y8': {
            'appearance': (
                '中等身高，初中生。变身后穿着米白色小斗篷，兜帽上的兽耳与兽爪手套让人感觉像一只小狗；'
                '整体以米白、浅黄为主色调并点缀粉红，像一座层叠的小蛋糕。'
            ),
            'story': (
                '她是魔法少女中正面战力最弱的一位，因此一直想证明自己并非队伍的累赘。'
                '她性格和环花暖一样温和善良，略带一点怯生生的小心翼翼，但在自己的能力取得进步时又格外乐于分享。\n'
                '她相信“为大家带来快乐”也是魔法少女的责任之一，因此常会悄悄给他人赠送自己做的蛋糕，'
                '或是在变身后收起能力去蛋糕店打工，假装成一名普通而热爱穿搭的少女。'
            ),
        },
        'Y10': {
            'appearance': '黑色长发，身形消瘦，日常多穿着被反复清洗、深色部分已略微发白的新海中学校服。',
        },
        'Y12': {
            'appearance': (
                '长长的头发，苍白的皮肤，总是漂浮在空中，拥有诡异的四只手臂；'
                '一双大大的眼睛看着人时常带着纯粹而欣喜的神色，声线温柔而甜美。'
            ),
            'story': (
                '原本是普通人，在接触到自然魔力现象后，出于强烈而纯粹的好奇心自愿成为 X 公司人体试验的受试者。'
                '她既无惨痛的过往，也不怀抱世俗的是非观念——对她而言，能让自己感到愉悦的便是正确，无法令内心生趣的便是无味。\n'
                '她一步步成为 X 公司的高层与外在掌控者，着手推行“魔法少女计划”，'
                '借公司收集自然魔力制成 X 药剂，并作为幕后旁观者搭起自走棋与模拟战的舞台——'
                '归根结底，坐在幕后看着自己的魔法少女们各自奔走、挣扎与交锋，对她而言本就是一件再有趣不过的事。'
            ),
        },
    }


def _read_xlsx_cells(path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        if '设定表' in wb.sheetnames:
            ws = wb['设定表']
            rows = list(ws.iter_rows(min_row=1, max_row=30, max_col=8, values_only=True))
            return {'type': 'unfair', 'rows': rows}
        info: dict = {'type': 'coc', 'simple': {}, 'main': {}}
        for sname in wb.sheetnames:
            if '简化' in sname:
                ws = wb[sname]
                for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=36, max_col=12, values_only=True), 1):
                    info['simple'][r_idx] = {c_idx: v for c_idx, v in enumerate(row, 1) if v is not None}
                break
        if '人物卡' in wb.sheetnames:
            ws = wb['人物卡']
            for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=82, max_col=35, values_only=True), 1):
                if r_idx <= 10 or r_idx >= 60:
                    info['main'][r_idx] = {c_idx: v for c_idx, v in enumerate(row, 1) if v is not None}
        return info
    finally:
        wb.close()


def _cell_str(val) -> str:
    if val is None:
        return ''
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def _parse_opening_fuzhe(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        xml_bytes = zf.read('word/document.xml')
    root = ET.fromstring(xml_bytes)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    raw_paras = [
        ''.join(t.text or '' for t in p.findall('.//w:t', ns)).strip()
        for p in root.findall('.//w:p', ns)
    ]
    paras = [p for p in raw_paras if p]

    # Chapter boundaries verified against P1..P2369 (1-based).
    chapter_defs = [
        ('ch_01', '题记与序幕 · 20XX 年战火', 1, 45),
        ('ch_02', 'SIDE A · 2024.04.22 初三（一）班', 46, 177),
        ('ch_03', 'SIDE A · 2024.05.24 高一楼天台', 178, 239),
        ('ch_04', 'SIDE A · 第 2 次轮回', 240, 306),
        ('ch_05', 'SIDE A · 第 3 次轮回', 307, 351),
        ('ch_06', 'SIDE A · 2025.11.02 教堂', 352, 427),
        ('ch_07', 'SIDE B · 2025.11.05 星期三', 428, 1464),
        ('ch_08', 'SIDE B · 2025.11.06 星期四', 1465, 2001),
        ('ch_09', 'SIDE C · 文学少女，魔法与改变的愿望', 2002, 2251),
        ('ch_10', 'SIDE C · 2025.11.07 星期五', 2252, len(paras)),
    ]

    chapters = []
    for ch_id, ch_title, start_1, end_1 in chapter_defs:
        chunk = paras[start_1 - 1:end_1]
        formatted: list[dict] = []
        for raw_line in chunk:
            line = raw_line.strip()
            speaker = None
            body = line
            m = re.match(r'^<([^>]+)>:\s*(.*)$', line)
            if m:
                speaker = m.group(1).strip()
                body = m.group(2).strip()
            if not body:
                continue
            if re.fullmatch(r'[—\-_=]{4,}', body):
                formatted.append({'kind': 'divider', 'text': '──────────'})
                continue
            if speaker in ('主持人', '主持人（副）') or speaker is None:
                if (
                    body.startswith('----')
                    or body.startswith('-SIDE ')
                    or body in ('覆辙', '序篇 PRELUDE')
                ):
                    clean_heading = body.strip('- ').strip()
                    formatted.append({'kind': 'heading', 'text': clean_heading})
                else:
                    formatted.append({'kind': 'narrator', 'text': body})
            elif speaker == '骰':
                formatted.append({'kind': 'note', 'speaker': '判定', 'text': body})
            else:
                formatted.append({'kind': 'dialogue', 'speaker': speaker, 'text': body})

        wc = _count_chars(formatted)
        chapters.append({
            'id': ch_id,
            'title': ch_title,
            'word_count': wc,
            'paragraphs': formatted,
        })

    total_wc = sum(ch['word_count'] for ch in chapters)
    return {
        'id': 'opening_fuzhe',
        'category': 'opening',
        'category_label': '大故事开篇',
        'title': '覆辙 · 序篇',
        'subtitle': '大故事开篇 · 序篇 PRELUDE（SIDE A / B / C）',
        'serial': None,
        'unit_name': None,
        'summary': '“来吧，起舞吧，歌唱吧，战斗吧，被命运裹挟的不幸者们！”——新海中学众少女与宿命轮回的宏大序幕。',
        'word_count': total_wc,
        'is_long': True,
        'chapter_count': len(chapters),
        'chapters': chapters,
    }


def _parse_y18_prequel(path: Path) -> dict:
    raw = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    lines = [ln.strip(' \t\r') for ln in raw.split('\n')]
    # Remove trailing empty/tab lines
    while lines and not lines[-1]:
        lines.pop()

    # Strip line 1 DS summary ("简述：【ds的概括】...")
    if lines and 'ds的概括' in lines[0]:
        lines = lines[1:]
    # Strip leading/trailing unmatched quotes
    cleaned_lines: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if ln.endswith('"'):
            ln = ln[:-1].rstrip()
        if ln.startswith('"'):
            ln = ln[1:].lstrip()
        # Clean inline PL/dice OOC block in Section 1
        ln = re.sub(r'（鸿鹄翱翔~激情浩荡～（pl的九岁习作x）.*?骰：1d6=1）', '', ln)
        if ln:
            cleaned_lines.append(ln)

    markers = [
        ('一、', 'ch_01', '一、四季山水与童年之诗，及其远去'),
        ('二', 'ch_02', '二、风平浪静的日常与《梦游仙境圆舞曲》'),
        ('三', 'ch_03', '三、音乐剧社与归宿'),
        ('四', 'ch_04', '四、崩解与重回日常'),
        ('五', 'ch_05', '五、初秋的告别前夕'),
    ]

    sec_indices: list[tuple[int, str, str]] = []
    for prefix, cid, ctitle in markers:
        idx = next(
            i for i, ln in enumerate(cleaned_lines)
            if (ln == prefix if len(prefix) == 1 else ln.startswith(prefix))
        )
        sec_indices.append((idx, cid, ctitle))

    chapters: list[dict] = []
    # Include opening two epigraph lines before "一、" in ch_01
    epigraph = cleaned_lines[:sec_indices[0][0]]
    for pos, (start_idx, cid, ctitle) in enumerate(sec_indices):
        end_idx = sec_indices[pos + 1][0] if pos + 1 < len(sec_indices) else len(cleaned_lines)
        body_lines = cleaned_lines[start_idx + 1:end_idx]
        paragraphs: list[dict] = []
        if pos == 0 and epigraph:
            for e in epigraph:
                paragraphs.append({'kind': 'quote', 'text': e})
            paragraphs.append({'kind': 'divider', 'text': '──────────'})
        for bl in body_lines:
            # Join orphan leading-punctuation lines such as "。..." from source text
            if paragraphs and bl and bl[0] in '。，！？；：、”」' and paragraphs[-1]['kind'] == 'narrator':
                paragraphs[-1]['text'] = paragraphs[-1]['text'] + bl
            else:
                paragraphs.append({'kind': 'narrator', 'text': bl})
        chapters.append({
            'id': cid,
            'title': ctitle,
            'word_count': _count_chars(paragraphs),
            'paragraphs': paragraphs,
        })

    total_wc = sum(ch['word_count'] for ch in chapters)
    return {
        'id': 'y18_prequel',
        'category': 'prequel',
        'category_label': '特别前传',
        'title': '夕歌谣梦 · 前传（四季山水与童年之诗）',
        'subtitle': 'Y18 夕歌谣梦（原名：张诗谣）单列背景前传',
        'serial': 'Y18',
        'unit_name': '夕歌谣梦',
        'summary': '张诗谣从与祖母、百灵鸟啾啾相伴的童年山溪，到失去庇护、在虚无与音乐剧社间沉浮的前传长篇。',
        'word_count': total_wc,
        'is_long': True,
        'chapter_count': len(chapters),
        'chapters': chapters,
    }


def _split_prose_block(text: str) -> list[dict]:
    """Split a single card text block into readable narrator/divider paragraphs."""
    paragraphs: list[dict] = []
    for raw in _clean_text(text).split('\n'):
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r'[—\-_=]{6,}', line):
            paragraphs.append({'kind': 'divider', 'text': '──────────'})
        else:
            paragraphs.append({'kind': 'narrator', 'text': line})
    return paragraphs


def build_lore_dataset() -> dict:
    juqing = _parse_juqing_txt(DOCS_DIR / '剧情.txt')
    pdf_pages = _load_pdf_pages(ATT_DIR / '模组：覆辙 (1).pdf')
    pdf_supp = _extract_pdf_supplemental(pdf_pages)

    y14_card = _read_xlsx_cells(ATT_DIR / '麦知夏.xlsx')
    y15_card = _read_xlsx_cells(ATT_DIR / '于长风.xlsx')
    y16_card = _read_xlsx_cells(ATT_DIR / '林白.xlsx')
    y16_pre_card = _read_xlsx_cells(ATT_DIR / 'COC7空白卡CY23.5.xlsx')
    y17_card = _read_xlsx_cells(ATT_DIR / '夜诏明（和平的魔法少女！闪亮登场）.xlsx')
    y18_card = _read_xlsx_cells(ATT_DIR / '不公平世界大战角色卡-张诗谣（夕诗遥梦）(Another world).xlsx')
    y19_card = _read_xlsx_cells(ATT_DIR / '不公平世界大战角色卡-木落(8)(1).xlsx')

    units: dict[str, dict] = {}
    char_stories: list[dict] = []

    def _add_short_unit(serial: str, fields: list[dict], story_text: str):
        story_id = f'unit_{serial}'
        clean_story = _clean_text(story_text)
        paras = _split_prose_block(clean_story)
        wc = _count_chars(paras)
        units[serial] = {
            'serial': serial,
            'profile_fields': fields,
            'story_mode': 'inline',
            'story_id': story_id,
            'story_text': clean_story,
            'story_excerpt': _make_excerpt(clean_story, 120),
            'extra_stories': [],
        }
        char_stories.append({
            'id': story_id,
            'category': 'character',
            'category_label': '角色背景故事',
            'title': f'{serial} {UNIT_NAMES[serial]} · 人物小传',
            'subtitle': f'棋子档案故事 · 原名：{next((f["value"] for f in fields if f["label"] == "原名"), "—")}',
            'serial': serial,
            'unit_name': UNIT_NAMES[serial],
            'summary': _make_excerpt(clean_story, 110),
            'word_count': wc,
            'is_long': False,
            'chapter_count': 1,
            'chapters': [{
                'id': 'ch_01',
                'title': '背景小传',
                'word_count': wc,
                'paragraphs': paras,
            }],
        })

    def _add_profile_only_unit(serial: str, fields: list[dict]):
        units[serial] = {
            'serial': serial,
            'profile_fields': fields,
            'story_mode': 'none',
            'story_id': None,
            'story_text': '',
            'story_excerpt': '',
            'extra_stories': [],
        }

    def _add_long_unit(
        serial: str,
        fields: list[dict],
        chapters: list[dict],
        subtitle: str,
        extra_stories: list[dict] | None = None,
    ):
        story_id = f'unit_{serial}'
        total_wc = sum(ch['word_count'] for ch in chapters)
        first_para_text = '\n'.join(p['text'] for p in chapters[0]['paragraphs'][:3] if p.get('kind') != 'divider')
        excerpt = _make_excerpt(first_para_text, 140)
        units[serial] = {
            'serial': serial,
            'profile_fields': fields,
            'story_mode': 'jump',
            'story_id': story_id,
            'story_text': '',
            'story_excerpt': excerpt,
            'extra_stories': extra_stories or [],
        }
        char_stories.append({
            'id': story_id,
            'category': 'character',
            'category_label': '角色背景故事',
            'title': f'{serial} {UNIT_NAMES[serial]} · 背景故事',
            'subtitle': subtitle,
            'serial': serial,
            'unit_name': UNIT_NAMES[serial],
            'summary': excerpt,
            'word_count': total_wc,
            'is_long': True,
            'chapter_count': len(chapters),
            'chapters': chapters,
        })

    # Helper to convert parsed 剧情.txt fields cleanly
    def _jq_fields(serial: str, skip_keys: set[str] | None = None) -> tuple[list[dict], str]:
        skip = skip_keys or set()
        out: list[dict] = []
        story = ''
        for k, v in juqing[serial]['fields']:
            if k in ('背景故事简介', '背景故事'):
                story = v
                continue
            if k in skip:
                continue
            label = '退出魔法少女的时间' if k.startswith('退出魔法少女') else k
            out.append({'label': label, 'value': v})
        return out, story

    # Y1–Y4: Short stories directly from docs/剧情.txt
    for s in ('Y1', 'Y2', 'Y3', 'Y4'):
        fields, story = _jq_fields(s)
        _add_short_unit(s, fields, story)

    # Y5–Y8: Appearance/Age/Short story supplemented from 模组：覆辙 (1).pdf
    # Y5 血天使
    y5_fields, _ = _jq_fields('Y5')
    _add_short_unit('Y5', y5_fields, pdf_supp['Y5']['story'])

    # Y6 雪人
    y6_fields, _ = _jq_fields('Y6')
    y6_fields = [
        {'label': k, 'value': (pdf_supp['Y6']['appearance'] if k == '外貌' else v)}
        for k, v in ((f['label'], f['value']) for f in y6_fields)
    ]
    _add_short_unit('Y6', y6_fields, pdf_supp['Y6']['story'])

    # Y7 环花暖 (insert age 14 from PDF P24, populate 外貌)
    y7_raw, _ = _jq_fields('Y7')
    y7_fields: list[dict] = []
    for f in y7_raw:
        if f['label'] == '外貌':
            y7_fields.append({'label': '外貌', 'value': pdf_supp['Y7']['appearance']})
        else:
            y7_fields.append(f)
            if f['label'] == '原名':
                y7_fields.append({'label': '年龄', 'value': pdf_supp['Y7']['age']})
    _add_short_unit('Y7', y7_fields, pdf_supp['Y7']['story'])

    # Y8 比哈米 (populate 外貌, deduplicate self '比哈米' in 友人)
    y8_raw, _ = _jq_fields('Y8')
    y8_fields: list[dict] = []
    for f in y8_raw:
        if f['label'] == '外貌':
            y8_fields.append({'label': '外貌', 'value': pdf_supp['Y8']['appearance']})
        elif f['label'] == '友人':
            friends = [p.strip() for p in re.split(r'[、,，]', f['value']) if p.strip() and p.strip() != '比哈米']
            y8_fields.append({'label': '友人', 'value': '、'.join(friends)})
        else:
            y8_fields.append(f)
    _add_short_unit('Y8', y8_fields, pdf_supp['Y8']['story'])

    # Y9 木落-荣枯: profile only
    y9_fields, _ = _jq_fields('Y9')
    y9_fields = [f for f in y9_fields if f['value']]
    _add_profile_only_unit('Y9', y9_fields)

    # Y10 春晌: profile + neutral appearance from PDF P16, no story
    y10_raw, _ = _jq_fields('Y10')
    y10_fields = [
        {'label': f['label'], 'value': (pdf_supp['Y10']['appearance'] if f['label'] == '外貌' else f['value'])}
        for f in y10_raw
    ]
    _add_profile_only_unit('Y10', y10_fields)

    # Y11 蓝: profile only
    y11_fields, _ = _jq_fields('Y11')
    y11_fields = [f for f in y11_fields if f['value']]
    _add_profile_only_unit('Y11', y11_fields)

    # Y12 斯瑞提卡: exception — PDF appearance + short backstory
    y12_raw, _ = _jq_fields('Y12')
    y12_fields = [
        {'label': f['label'], 'value': (pdf_supp['Y12']['appearance'] if f['label'] == '外貌' else f['value'])}
        for f in y12_raw
    ]
    _add_short_unit('Y12', y12_fields, pdf_supp['Y12']['story'])

    # Y13 巨人: profile only
    y13_fields, _ = _jq_fields('Y13')
    _add_profile_only_unit('Y13', y13_fields)

    # Y14 余烬 (麦知夏.xlsx)
    y14_fields, _ = _jq_fields('Y14')
    y14_app = _cell_str(y14_card['simple'][28][3])
    y14_extra = [
        ('思想与信念', _cell_str(y14_card['simple'][29][3])),
        ('重要之人', _cell_str(y14_card['simple'][30][3])),
        ('意义非凡之地', _cell_str(y14_card['simple'][31][3])),
        ('宝贵之物', _cell_str(y14_card['simple'][32][3])),
        ('特质', _cell_str(y14_card['simple'][33][3])),
        ('伤疤', _cell_str(y14_card['simple'][34][3])),
        ('恐惧', _cell_str(y14_card['simple'][35][3])),
    ]
    y14_fields = [
        {'label': f['label'], 'value': (y14_app if f['label'] == '外貌' else f['value'])}
        for f in y14_fields
    ] + [{'label': k, 'value': v} for k, v in y14_extra if v]
    y14_paras = _split_prose_block(_cell_str(y14_card['main'][77][23]))
    _add_long_unit(
        'Y14',
        y14_fields,
        [{'id': 'ch_01', 'title': '经历 · 麦知夏', 'word_count': _count_chars(y14_paras), 'paragraphs': y14_paras}],
        'Y14 余烬（原名：麦知夏）完整背景经历',
    )

    # Y15 葬火 (于长风.xlsx)
    y15_fields, _ = _jq_fields('Y15')
    y15_norm_app = _cell_str(y15_card['simple'][29][3]).removeprefix('常态：').strip()
    y15_raw_story = _clean_text(_cell_str(y15_card['main'][80][23]))
    y15_trans_app = ''
    y15_story_lines = []
    for ln in y15_raw_story.split('\n'):
        s = ln.strip()
        if s.startswith('变身：'):
            y15_trans_app = s.removeprefix('变身：').strip()
            continue
        if 'pl个人层面' in s or s.startswith('魔法的话可能是火系'):
            continue
        y15_story_lines.append(ln)
    y15_clean_fields = []
    for f in y15_fields:
        if f['label'] == '外貌':
            y15_clean_fields.append({'label': '外貌（常态）', 'value': y15_norm_app})
            if y15_trans_app:
                y15_clean_fields.append({'label': '外貌（变身）', 'value': y15_trans_app})
        else:
            y15_clean_fields.append(f)
    y15_extra = [
        ('思想与信念', _cell_str(y15_card['simple'][30][3])),
        ('重要之人', _cell_str(y15_card['simple'][31][3])),
        ('意义非凡之地', _cell_str(y15_card['simple'][32][3])),
        ('宝贵之物', _cell_str(y15_card['simple'][33][3])),
        ('难言之隐', _cell_str(y15_card['main'][72].get(27, ''))),
        ('特质', _cell_str(y15_card['simple'][34][3])),
        ('伤疤', _cell_str(y15_card['simple'][35][3])),
    ]
    y15_clean_fields += [{'label': k, 'value': v} for k, v in y15_extra if v]
    y15_paras = _split_prose_block('\n'.join(y15_story_lines))
    _add_long_unit(
        'Y15',
        y15_clean_fields,
        [{'id': 'ch_01', 'title': '经历 · 于长风', 'word_count': _count_chars(y15_paras), 'paragraphs': y15_paras}],
        'Y15 葬火（原名：于长风）完整背景经历',
    )

    # Y16 罗杰 (林白.xlsx + COC7空白卡CY23.5.xlsx 前传《夜空之下》林墨)
    y16_raw, _ = _jq_fields('Y16')
    y16_app = _cell_str(y16_card['simple'][28][3])
    y16_fields: list[dict] = [{'label': '原名', 'value': '林白'}]
    for f in y16_raw:
        if f['label'] == '年龄':
            y16_fields.append({'label': '年龄', 'value': '14'})
        elif f['label'] == '外貌':
            y16_fields.append({'label': '外貌', 'value': y16_app})
        else:
            y16_fields.append(f)
    y16_extra = [
        ('思想与信念', _cell_str(y16_card['simple'][29][3])),
        ('重要之人', _cell_str(y16_card['simple'][30][3])),
        ('宝贵之物', _cell_str(y16_card['simple'][32][3])),
        ('特质', _cell_str(y16_card['simple'][33][3])),
    ]
    y16_fields += [{'label': k, 'value': v} for k, v in y16_extra if v]

    y16_pre_raw = _clean_text(_cell_str(y16_pre_card['main'][77][23]))
    y16_pre_lines = y16_pre_raw.split('\n')
    if y16_pre_lines and y16_pre_lines[0].strip().startswith('前传'):
        y16_pre_lines = y16_pre_lines[1:]
    y16_pre_paras = _split_prose_block(_unwrap_soft_lines('\n'.join(y16_pre_lines)))
    y16_main_paras = _split_prose_block(_unwrap_soft_lines(_cell_str(y16_card['main'][77][23])))
    _add_long_unit(
        'Y16',
        y16_fields,
        [
            {'id': 'ch_01', 'title': '前传 ·《夜空之下》（林墨）', 'word_count': _count_chars(y16_pre_paras), 'paragraphs': y16_pre_paras},
            {'id': 'ch_02', 'title': '本篇 · 林白', 'word_count': _count_chars(y16_main_paras), 'paragraphs': y16_main_paras},
        ],
        'Y16 罗杰（原名：林白）前传《夜空之下》与本篇完整背景',
    )

    # Y17 夜诏明 (全字段来自角色卡)
    y17_trait_raw = _cell_str(y17_card['simple'][33][3])
    y17_trait_clean = re.sub(r'（备注：.*?）\s*$', '', y17_trait_raw).strip()
    y17_fields = [
        {'label': '原名', 'value': '夜诏明'},
        {'label': '年龄', 'value': '16（轮回累计 211 岁）'},
        {'label': '职业', 'value': '“魔法少女”'},
        {'label': '外貌', 'value': _cell_str(y17_card['simple'][28][3])},
        {'label': '意义非凡之地', 'value': _cell_str(y17_card['simple'][31][3])},
        {'label': '特质', 'value': y17_trait_clean},
        {'label': '心理状态', 'value': _cell_str(y17_card['simple'][35][3])},
    ]
    y17_paras = _split_prose_block(_cell_str(y17_card['main'][77][23]))
    _add_long_unit(
        'Y17',
        y17_fields,
        [{'id': 'ch_01', 'title': '轮回经历 · 第 562 次', 'word_count': _count_chars(y17_paras), 'paragraphs': y17_paras}],
        'Y17 夜诏明角色卡完整经历',
    )

    # Y18 夕歌谣梦 (张诗谣角色卡 — 仅放置人物卡表示了的字段 + 单列前传)
    y18_rows = y18_card['rows']
    # Row index in 0-based rows: R2=1, R4=3, R6=5, R7=6, R8=7, R23=22
    y18_name = _cell_str(y18_rows[1][1])
    y18_age = _cell_str(y18_rows[3][1])
    y18_gender = _cell_str(y18_rows[3][3])
    y18_home = _cell_str(y18_rows[5][1])
    y18_bg = _cell_str(y18_rows[6][1])
    y18_app_full = _clean_text(_cell_str(y18_rows[7][1]))
    y18_personality = _clean_text(_cell_str(y18_rows[7][3]))
    y18_story_raw = _clean_text(_cell_str(y18_rows[22][1]))
    # Strip dangling quote left at the end of line 1 in the spreadsheet cell
    y18_story_raw = re.sub(r'神明大人阿。为何连这样的机会，您都要剥夺呢？"', '神明大人阿。为何连这样的机会，您都要剥夺呢？', y18_story_raw)
    if '变身后：' in y18_app_full:
        before_part, after_part = y18_app_full.split('变身后：', 1)
        y18_app_before = before_part.removeprefix('变身前：').strip()
        y18_app_after = after_part.strip()
    else:
        y18_app_before = y18_app_full
        y18_app_after = ''

    y18_fields = [
        {'label': '原名', 'value': y18_name},
        {'label': '年龄', 'value': y18_age},
        {'label': '性别', 'value': y18_gender},
        {'label': '居所 / 故乡', 'value': y18_home},
        {'label': '背景', 'value': y18_bg},
        {'label': '外貌（变身前）', 'value': y18_app_before},
    ]
    if y18_app_after:
        y18_fields.append({'label': '外貌（变身后）', 'value': y18_app_after})
    y18_fields.append({'label': '性格', 'value': y18_personality})

    y18_prequel_story = _parse_y18_prequel(PREQUEL_PATH)
    y18_paras = _split_prose_block(y18_story_raw)
    _add_long_unit(
        'Y18',
        y18_fields,
        [{'id': 'ch_01', 'title': '经历 · 后篇（一百天与金箔）', 'word_count': _count_chars(y18_paras), 'paragraphs': y18_paras}],
        'Y18 夕歌谣梦（原名：张诗谣）角色卡背景经历',
        extra_stories=[{
            'id': y18_prequel_story['id'],
            'title': y18_prequel_story['title'],
            'word_count': y18_prequel_story['word_count'],
        }],
    )

    # Y19 木落-焚秋 (石津/木落角色卡 — 仅放置人物卡表示了的字段)
    y19_rows = y19_card['rows']
    y19_name = _cell_str(y19_rows[1][1])
    y19_age = _cell_str(y19_rows[3][1])
    y19_gender = _cell_str(y19_rows[3][3])
    y19_bg = _cell_str(y19_rows[6][1])
    y19_app_full = _clean_text(_cell_str(y19_rows[7][1]))
    y19_personality = _clean_text(_cell_str(y19_rows[7][3]))
    y19_hobby = _cell_str(y19_rows[11][1])
    y19_dislike = _cell_str(y19_rows[11][3])
    y19_story_raw = _clean_text(_cell_str(y19_rows[22][1]))
    if '变身后第一形态：' in y19_app_full:
        norm_p, trans_p = y19_app_full.split('变身后第一形态：', 1)
        y19_app_norm = norm_p.strip()
        y19_app_trans = '第一形态：' + trans_p.strip()
    else:
        y19_app_norm = y19_app_full
        y19_app_trans = ''

    y19_fields = [
        {'label': '原名', 'value': '石津（笔下人物/代号：木落）' if '石津' in y19_name else y19_name},
        {'label': '年龄', 'value': y19_age},
        {'label': '性别', 'value': y19_gender},
        {'label': '背景', 'value': y19_bg},
        {'label': '外貌（常态）', 'value': y19_app_norm},
    ]
    if y19_app_trans:
        y19_fields.append({'label': '外貌（变身后）', 'value': y19_app_trans})
    y19_fields.extend([
        {'label': '性格', 'value': y19_personality},
        {'label': '爱好', 'value': y19_hobby or '无'},
        {'label': '厌恶', 'value': y19_dislike or '无'},
    ])
    y19_paras = _split_prose_block(y19_story_raw)
    _add_long_unit(
        'Y19',
        y19_fields,
        [{'id': 'ch_01', 'title': '经历 · 石津 / 木落', 'word_count': _count_chars(y19_paras), 'paragraphs': y19_paras}],
        'Y19 木落-焚秋（原名：石津）角色卡完整背景经历',
    )

    opening_story = _parse_opening_fuzhe(ATT_DIR / '覆辙_log0727 (1).docx')

    # Order stories: Opening -> Y18 Standalone Prequel -> Character stories by Y1..Y19
    char_stories.sort(key=lambda s: int(s['serial'][1:]))
    stories = [opening_story, y18_prequel_story] + char_stories

    return {
        'version': 1,
        'units': {k: units[k] for k in sorted(units, key=lambda s: int(s[1:]))},
        'stories': stories,
    }


def validate_dataset(data: dict) -> None:
    assert isinstance(data, dict), 'root must be object'
    units = data.get('units', {})
    stories = data.get('stories', [])
    expected_serials = {f'Y{i}' for i in range(1, 20)}
    assert set(units.keys()) == expected_serials, f'missing serials: {expected_serials - set(units.keys())}'

    inline_expected = {'Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8', 'Y12'}
    none_expected = {'Y9', 'Y10', 'Y11', 'Y13'}
    jump_expected = {'Y14', 'Y15', 'Y16', 'Y17', 'Y18', 'Y19'}

    story_map = {s['id']: s for s in stories}
    assert len(story_map) == len(stories), 'duplicate story id'

    for serial, unit in units.items():
        fields = unit.get('profile_fields') or []
        assert fields, f'{serial} missing profile_fields'
        mode = unit.get('story_mode')
        if serial in inline_expected:
            assert mode == 'inline', f'{serial} expected inline, got {mode}'
            assert unit.get('story_text'), f'{serial} empty story_text'
            assert unit.get('story_id') in story_map, f'{serial} missing story entry'
        elif serial in none_expected:
            assert mode == 'none', f'{serial} expected none, got {mode}'
            assert unit.get('story_id') is None
        elif serial in jump_expected:
            assert mode == 'jump', f'{serial} expected jump, got {mode}'
            assert unit.get('story_excerpt'), f'{serial} missing excerpt'
            assert unit.get('story_id') in story_map, f'{serial} missing story entry'

    # Strict card-only checks on Y18 & Y19
    forbidden_card_labels = {'学校', '班级', '年级', '社团', '成为魔法少女的时间', '退出魔法少女的时间', '友人', '讨厌的人'}
    for s in ('Y18', 'Y19'):
        labels = {f['label'] for f in units[s]['profile_fields']}
        overlap = labels & forbidden_card_labels
        assert not overlap, f'{s} contains forbidden non-card labels: {overlap}'

    # Y16 dual-chapter check
    y16_st = story_map['unit_Y16']
    assert len(y16_st['chapters']) == 2, 'Y16 must have 2 chapters (prequel + main)'
    assert y16_st['word_count'] > 3000, 'Y16 total word count too low'

    # Y18 standalone prequel & OOC cleanup checks
    assert 'y18_prequel' in story_map
    assert any(ex['id'] == 'y18_prequel' for ex in units['Y18'].get('extra_stories', []))
    prequel = story_map['y18_prequel']
    assert prequel['category'] == 'prequel'
    assert len(prequel['chapters']) == 5
    prequel_txt = '\n'.join(p['text'] for ch in prequel['chapters'] for p in ch['paragraphs'])
    for bad in ('ds的概括', 'pl的九岁习作', '1d6=1'):
        assert bad not in prequel_txt, f'OOC marker remained in prequel: {bad}'

    y15_txt = '\n'.join(p['text'] for ch in story_map['unit_Y15']['chapters'] for p in ch['paragraphs'])
    assert 'pl个人层面' not in y15_txt
    y17_prof = ' '.join(f['value'] for f in units['Y17']['profile_fields'])
    assert '我设计的初衷就是这个' not in y17_prof

    # Opening story check
    opening = story_map['opening_fuzhe']
    assert opening['category'] == 'opening'
    assert len(opening['chapters']) == 10
    assert opening['word_count'] > 85000


def main() -> int:
    parser = argparse.ArgumentParser(description='Import or validate Auto-Chess unit lore and stories.')
    parser.add_argument('--check', action='store_true', help='Validate existing JSON without overwriting.')
    args = parser.parse_args()

    if args.check:
        if not OUT_PATH.exists():
            print(f'ERROR: {OUT_PATH} does not exist.', file=sys.stderr)
            return 1
        data = json.loads(OUT_PATH.read_text(encoding='utf-8'))
        validate_dataset(data)
    else:
        data = build_lore_dataset()
        validate_dataset(data)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f'Validated {OUT_PATH.relative_to(ROOT)} ({size_kb:.1f} KB)')
    print(f'Units: {len(data["units"])} | Stories: {len(data["stories"])}')
    for st in data['stories']:
        print(f'  - [{st["category_label"]}] {st["id"]}: {st["title"]} ({st["chapter_count"]} ch, {st["word_count"]} chars)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
