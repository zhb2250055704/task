import json
import os
import re
import shutil
import subprocess
import time
import unicodedata

from kongming_index import search_kongming_index


KONGMING_MAX_SEARCH_TERMS = 8
KONGMING_MAX_SEARCH_TERM_LENGTH = 80
KONGMING_MAX_TABLE_CANDIDATES = 12
KONGMING_MAX_CLIENT_CANDIDATES = 18
KONGMING_MAX_GM_COMMAND_CANDIDATES = 12
KONGMING_MAX_MATCHED_ROWS = 10
KONGMING_MAX_ROW_FIELDS = 22
KONGMING_MAX_CLIENT_SNIPPETS = 5
KONGMING_MAX_EVIDENCE_CHARS = 70000
KONGMING_MAX_REFERENCE_ROWS = 80
KONGMING_MAX_REFERENCE_FIELDS = 120
KONGMING_MAX_REFERENCE_RELATIONS = 40

_CJK_PATTERN = re.compile(r'[\u3400-\u9fff]{2,}')
_IDENTIFIER_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{2,}|\d{4,}')
_STOP_PHRASES = sorted({
    '帮我查找', '帮我查询', '帮我看看', '帮我', '请帮忙', '请问', '查找', '查询', '查阅', '查',
    '配置表', '客户端', '服务端', '前后端', '关键字段', '关联关系', '关联的', '关联',
    '活动', '玩法', '功能', '入口', '代码', '字段', '表格', '表里', '表中',
    '哪些', '哪个', '什么', '怎么', '如何', '最多', '列出', '相关的', '相关', '张', '最',
    '详细', '具体', '信息', '内容', '一下', '一下子', '这个', '那个', '以及',
    '是否', '可以', '需要', '对应', '里面', '中的', '里的', '和', '与', '的',
    'GM命令', 'gm命令', '命令', '指令', '口令', '有关的', '有关', '关于', '跟',
    '每个', '各个', '分别', '是多少', '有多少', '多少',
}, key=len, reverse=True)
_CJK_DIMENSION_TERMS = (
    '赛季', '阶段', '章节', '等级', '上限', '下限', '数量', '次数', '时间',
    '条件', '状态', '奖励', '概率', '范围',
)
_SEARCH_TERM_ALIASES = {
    '赛季': ('season',),
    '阶段': ('stage',),
    '章节': ('chapter',),
    '等级': ('level', 'lv'),
    '上限': ('limit', 'max'),
    '下限': ('min',),
    '数量': ('count', 'num'),
    '次数': ('times', 'count'),
    '时间': ('time',),
    '条件': ('condition', 'require'),
    '状态': ('status', 'state'),
    '奖励': ('reward',),
    '概率': ('rate', 'probability'),
    '范围': ('range',),
    '火炉': ('篝火', 'furnace', 'bonfire', 'stove'),
}
_GENERIC_IDENTIFIERS = {
    'xlsx', 'json', 'excel', 'client', 'server', 'sheet', 'field', 'fields',
    'activity', 'config', 'configuration', 'entry', 'table', 'tables', 'find',
    'search', 'related', 'relation', 'game', 'code', 'detail', 'details',
    'command', 'commands',
}
_FIELD_HINTS = (
    'id', 'name', 'title', 'desc', 'type', 'activity', 'switch', 'reward', 'drop',
    'store', 'item', 'time', 'level', 'group', 'server', 'function', 'open', 'close',
)
_CLIENT_GLOBS = ('*.ts', '*.tsx', '*.js', '*.jsx', '*.lua', '*.py', '*.cs')
_BRANCH_COMPARE_MARKERS = (
    '分支', '版本', 'branch', 'commit', 'diff', '对比', '比较', '新增', '删除', '变更',
    '改动', '修改', '相较',
)
_BRANCH_FIELD_HINTS = (
    '金冠', '保底', 'golden', 'crown', 'mercy', 'miss', 'pity', 'guarantee',
)
_REFERENCE_FIELD_HINTS = (
    'drop', 'group', 'reward', 'item', 'config', 'ref', 'id',
    '掉落', '奖池', '奖励', '配置', '引用',
)
_REFERENCE_TABLE_HINTS = (
    'dropgroup', 'drop_group', '掉落组', '掉落组表',
)
_PHYSICAL_ROW_RANGE_PATTERN = re.compile(
    r'(?<!\d)(\d{1,8})\s*(?:~|～|-|—|–|至|到)\s*(\d{1,8})\s*(?:行|row|rows)?',
    flags=re.IGNORECASE,
)
_PHYSICAL_ROW_PATTERN = re.compile(
    r'(?:(?:第|物理\s*行|physical\s*row|row|line)\s*)(\d{1,8})|'
    r'(?<!\d)(\d{1,8})\s*(?:行|rows?)',
    flags=re.IGNORECASE,
)


def extract_kongming_search_terms(text):
    normalized = unicodedata.normalize('NFKC', str(text or ''))
    terms = []

    for value in _IDENTIFIER_PATTERN.findall(normalized):
        clean = value.strip('._-')[:KONGMING_MAX_SEARCH_TERM_LENGTH]
        if len(clean) < 2 or clean.lower() in _GENERIC_IDENTIFIERS:
            continue
        if clean not in terms:
            terms.append(clean)

    for chunk in _CJK_PATTERN.findall(normalized):
        parts = [chunk]
        for phrase in _STOP_PHRASES:
            parts = [piece for part in parts for piece in part.split(phrase)]
        for part in parts:
            clean = part.strip()[:KONGMING_MAX_SEARCH_TERM_LENGTH]
            if len(clean) < 2:
                continue
            dimensions = [term for term in _CJK_DIMENSION_TERMS if term in clean]
            entity = clean
            for dimension in dimensions:
                entity = entity.replace(dimension, ' ')
            for value in (entity.strip(), *dimensions):
                if len(value) >= 2 and value not in terms:
                    terms.append(value)

    original_terms = list(terms)
    for alias_index in range(2):
        for term in original_terms:
            aliases = _SEARCH_TERM_ALIASES.get(term) or ()
            if alias_index < len(aliases) and aliases[alias_index] not in terms:
                terms.append(aliases[alias_index])
            if len(terms) >= KONGMING_MAX_SEARCH_TERMS:
                return terms[:KONGMING_MAX_SEARCH_TERMS]

    return terms[:KONGMING_MAX_SEARCH_TERMS]


def _run_rg_files(root, terms, globs, limit, exclude_tool=False):
    rg_path = shutil.which('rg')
    if not rg_path or not os.path.isdir(root) or not terms:
        return {}
    args = [rg_path, '-l', '-F', '-i', '--no-messages']
    for pattern in globs:
        args.extend(['-g', pattern])
    args.extend([
        '-g', '!.git/**',
        '-g', '!**/.git/**',
        '-g', '!**/node_modules/**',
        '-g', '!**/Library/**',
        '-g', '!**/build-templates/**',
    ])
    if exclude_tool:
        args.extend(['-g', '!tools/gm-command-tool/**'])
    for term in terms:
        args.extend(['-e', term])
    args.extend(['--', root])
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode not in (0, 1):
        return {}
    matches = {}
    for line in result.stdout.splitlines():
        path = os.path.abspath(line.strip())
        if not path or not os.path.isfile(path):
            continue
        path_lower = path.lower()
        path_terms = {term for term in terms if term.lower() in path_lower}
        matches[path] = path_terms or set(terms)
        if len(matches) >= limit:
            break
    return matches


def _truncate(value, limit=360):
    text = str(value or '').replace('\x00', '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _matched_terms(value, terms):
    lowered = str(value or '').lower()
    return [term for term in terms if term.lower() in lowered]


def _gm_command_requested(question):
    source = unicodedata.normalize('NFKC', str(question or '')).lower()
    return any(marker in source for marker in ('gm', '命令', '指令', '口令')) or '#' in source


def _gm_command_values(command):
    values = []
    for field in ('name', 'command', 'category', 'params', 'example', 'description'):
        value = command.get(field)
        if value not in (None, ''):
            values.append(str(value))
    tags = command.get('tags')
    if isinstance(tags, list):
        values.extend(str(tag) for tag in tags if str(tag or '').strip())
    elif tags:
        values.append(str(tags))
    return values


def _search_gm_commands(question, terms, gm_commands_path):
    if not _gm_command_requested(question) or not os.path.isfile(gm_commands_path or ''):
        return []
    try:
        with open(gm_commands_path, 'r', encoding='utf-8-sig') as source:
            payload = json.load(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    commands = payload.get('commands') if isinstance(payload, dict) else payload
    if not isinstance(commands, list):
        return []

    question_lower = unicodedata.normalize('NFKC', str(question or '')).lower()
    search_terms = list(terms or [])
    categories = list(dict.fromkeys(
        str(command.get('category') or '').strip()
        for command in commands if isinstance(command, dict)
        and str(command.get('category') or '').strip()
    ))
    question_categories = [
        category for category in categories if category.lower() in question_lower
    ]
    focused_categories = [
        category for category in question_categories
        if any(
            term.lower() in category.lower() or category.lower() in term.lower()
            for term in search_terms
        )
    ]
    if focused_categories:
        question_categories = focused_categories
    elif search_terms:
        question_categories = []
    question_category_keys = {category.lower() for category in question_categories}
    for category in question_categories:
        if category not in search_terms:
            search_terms.append(category)

    for command in commands:
        if not isinstance(command, dict):
            continue
        name = str(command.get('name') or '').strip()
        if (
            len(name) >= 3
            and name.lower() not in ('command', 'cmd')
            and name.lower() in question_lower
            and name not in search_terms
        ):
            search_terms.append(name)

    candidates = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        values = _gm_command_values(command)
        combined = '\n'.join(values).lower()
        category = str(command.get('category') or '').strip()
        name = str(command.get('name') or '').strip()
        command_text = str(command.get('command') or '').strip()
        matched = [term for term in search_terms if term.lower() in combined]
        score = 0
        for term in matched:
            lowered = term.lower()
            if lowered == category.lower():
                score += 120
            elif lowered in category.lower():
                score += 70
            if lowered in (name.lower(), command_text.lower(), command_text.lstrip('#').lower()):
                score += 100
            elif lowered in name.lower() or lowered in command_text.lower():
                score += 55
            if lowered in str(command.get('description') or '').lower():
                score += 30
            if lowered in str(command.get('params') or '').lower():
                score += 12
        if category and category.lower() in question_category_keys:
            score += 140
            if category not in matched:
                matched.append(category)
        if name and name.lower() in question_lower:
            score += 110
            if name not in matched:
                matched.append(name)
        if command_text and command_text.lower() in question_lower:
            score += 130
        if score <= 0:
            continue
        candidates.append({
            'id': str(command.get('id') or ''),
            'name': name,
            'command': command_text,
            'category': category,
            'tags': command.get('tags') if isinstance(command.get('tags'), list) else [],
            'params': _truncate(command.get('params'), 500),
            'example': _truncate(command.get('example'), 500),
            'description': _truncate(command.get('description'), 700),
            'matched_terms': list(dict.fromkeys(matched)),
            'score': score,
        })
    candidates.sort(key=lambda item: (-item['score'], item['category'], item['name']))
    return candidates[:KONGMING_MAX_GM_COMMAND_CANDIDATES]


def _row_fields(cells, headers, terms):
    ranked = []
    for column, raw_value in (cells or {}).items():
        value = _truncate(raw_value)
        if not value:
            continue
        label = _truncate(headers.get(column) or column, 80)
        lowered_label = label.lower()
        lowered_value = value.lower()
        score = 0
        if any(term.lower() in lowered_value for term in terms):
            score += 20
        if any(hint in lowered_label for hint in _FIELD_HINTS):
            score += 5
        if lowered_label in ('id', 'name', 'title'):
            score += 5
        ranked.append((score, str(column), label, value))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return {label: value for _score, _column, label, value in ranked[:KONGMING_MAX_ROW_FIELDS]}


def _summarize_json_table(path, matched_by, json_root):
    relative = os.path.relpath(path, json_root).replace('\\', '/')
    candidate = {
        'json_path': relative,
        'xlsx_path': relative[:-5] + '.xlsx' if relative.lower().endswith('.json') else relative,
        'matched_terms': sorted(matched_by),
        'sheets': [],
        'matched_rows': [],
        'score': 0,
    }
    if '/language/' in '/' + relative.lower():
        candidate['score'] = -20
        return candidate
    try:
        with open(path, 'r', encoding='utf-8') as source:
            data = json.load(source)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return candidate

    terms = list(matched_by)
    for sheet in data.get('sheets') or []:
        if not isinstance(sheet, dict):
            continue
        sheet_name = _truncate(sheet.get('name'), 100)
        if sheet_name:
            candidate['sheets'].append(sheet_name)
        rows = sheet.get('rows') if isinstance(sheet.get('rows'), list) else []
        headers = {}
        for row in rows[:12]:
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            values = [str(value or '').strip().lower() for value in cells.values()]
            if str(cells.get('A') or '').strip().lower() == 'id' or 'id' in values:
                headers = {str(column): str(value or '').strip() for column, value in cells.items()}
                break

        for row_index, row in enumerate(rows, start=1):
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            joined = '\n'.join(str(value or '') for value in cells.values())
            row_terms = _matched_terms(joined, terms)
            if not row_terms:
                continue
            candidate['matched_rows'].append({
                'sheet': sheet_name,
                'row': row_index,
                'matched_terms': row_terms,
                'fields': _row_fields(cells, headers, row_terms),
            })
            if len(candidate['matched_rows']) >= KONGMING_MAX_MATCHED_ROWS:
                break
        if len(candidate['matched_rows']) >= KONGMING_MAX_MATCHED_ROWS:
            break

    relative_lower = relative.lower()
    stem_lower = os.path.splitext(os.path.basename(relative_lower))[0]
    normalized_stem = re.sub(r'^(sg_)?coa_', '', stem_lower)
    filename_hits = sum(
        1 for term in terms
        if term.lower() in stem_lower or term.lower() in normalized_stem
    )
    sheet_hits = sum(
        1 for term in terms
        if any(term.lower() in sheet.lower() for sheet in candidate['sheets'])
    )
    candidate['score'] = (
        len(candidate['matched_rows']) * 8
        + len(candidate['matched_terms']) * 5
        + (8 if '/common/' in '/' + relative_lower else 0)
        + (3 if os.path.basename(relative_lower).startswith(('coa_', 'sg_coa_')) else 0)
        + filename_hits * 60
        + sheet_hits * 30
    )
    candidate['sheets'] = candidate['sheets'][:30]
    return candidate


def _parse_physical_row_ranges(text):
    """Parse explicit spreadsheet physical rows without treating config IDs as rows."""
    source = unicodedata.normalize('NFKC', str(text or ''))
    ranges = []
    covered = set()
    for match in _PHYSICAL_ROW_RANGE_PATTERN.finditer(source):
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            start, end = end, start
        context = source[max(0, match.start() - 12):min(len(source), match.end() + 12)]
        has_row_marker = bool(re.search(r'行|row|line|物理', context, flags=re.IGNORECASE))
        if not has_row_marker:
            continue
        item = {'start': start, 'end': end}
        if item not in ranges:
            ranges.append(item)
        covered.update(range(start, min(end, start + KONGMING_MAX_REFERENCE_ROWS) + 1))

    singles = []
    for match in _PHYSICAL_ROW_PATTERN.finditer(source):
        value = next((group for group in match.groups() if group), '')
        if not value:
            continue
        row = int(value)
        if row in covered or row in singles:
            continue
        singles.append(row)
    if singles:
        ranges.extend({'start': row, 'end': row} for row in singles[:12])

    rows = []
    truncated = False
    for item in ranges:
        if item['end'] - item['start'] + 1 > KONGMING_MAX_REFERENCE_ROWS:
            truncated = True
        for row in range(item['start'], item['end'] + 1):
            if len(rows) >= KONGMING_MAX_REFERENCE_ROWS:
                truncated = True
                break
            if row not in rows:
                rows.append(row)
        if len(rows) >= KONGMING_MAX_REFERENCE_ROWS:
            break
    return {
        'ranges': ranges[:12],
        'rows': sorted(rows),
        'truncated': truncated,
    }


def _json_candidate_path(candidate, json_root):
    relative = str((candidate or {}).get('json_path') or '').replace('/', os.sep)
    if not relative:
        return ''
    root = os.path.abspath(json_root)
    path = os.path.abspath(os.path.join(root, relative))
    try:
        if os.path.commonpath((root, path)) != root:
            return ''
    except ValueError:
        return ''
    return path


def _load_json_table(candidate, json_root, excel_root='', ref=''):
    relative = str((candidate or {}).get('json_path') or '').replace('\\', '/')
    if not relative:
        return None
    if ref and excel_root:
        data = _git_show_json(excel_root, ref, relative)
        if isinstance(data, dict):
            return data
    path = _json_candidate_path(candidate, json_root)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8-sig') as source:
            data = json.load(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _reference_table_candidate_score(candidate, question, target=True):
    source = unicodedata.normalize('NFKC', str(question or '')).lower()
    haystack = ' '.join((
        str(candidate.get('json_path') or ''),
        str(candidate.get('xlsx_path') or ''),
        ' '.join(str(value or '') for value in candidate.get('sheets') or []),
    )).lower()
    score = 0
    if any(hint in source for hint in _REFERENCE_TABLE_HINTS):
        score += sum(100 for hint in _REFERENCE_TABLE_HINTS if hint in haystack)
    if any(hint in haystack for hint in _REFERENCE_TABLE_HINTS):
        score += 80 if target else 10
    if target and 'sg_coa_dropgroup' in haystack:
        score += 180
    if not target:
        explicit_table_tokens = re.findall(
            r'(?i)(?:sg_)?coa_[a-z0-9_.-]+', source
        )
        score += sum(
            180 for token in explicit_table_tokens
            if token.lower() in haystack
        )
        if any(
            token.lower() in haystack
            for token in ('coa_activityfishingevent', 'activityfishingevent')
        ):
            score += 180
    if '/common/' in '/' + haystack:
        score += 10
    return score


def _discover_reference_table_candidates(question, tables, json_root):
    """Add filename matches for explicitly named reference tables without scanning file contents."""
    candidates = {str(item.get('json_path') or ''): item for item in (tables or [])}
    source = unicodedata.normalize('NFKC', str(question or '')).lower()
    has_reference_signal = bool(
        any(hint in source for hint in _REFERENCE_TABLE_HINTS)
        or re.search(r'物理\s*行|physical\s*row|\brows?\b|\blines?\b', source)
    )
    if not has_reference_signal:
        return list(candidates.values())
    filename_hints = set(_REFERENCE_TABLE_HINTS)
    for token in re.findall(r'[A-Za-z][A-Za-z0-9_.-]{2,}', source):
        if any(marker in token for marker in ('coa_', 'drop', 'activity', 'event')):
            filename_hints.add(token)
    if not filename_hints or not os.path.isdir(json_root):
        return list(candidates.values())
    try:
        for base, _directories, names in os.walk(json_root):
            for name in names:
                lowered = name.lower()
                if not lowered.endswith('.json'):
                    continue
                if not any(hint in lowered for hint in filename_hints):
                    continue
                path = os.path.abspath(os.path.join(base, name))
                relative = os.path.relpath(path, json_root).replace('\\', '/')
                if relative in candidates:
                    continue
                candidates[relative] = {
                    'json_path': relative,
                    'xlsx_path': relative[:-5] + '.xlsx',
                    'matched_terms': [],
                    'sheets': [],
                    'matched_rows': [],
                    'score': 0,
                }
    except OSError:
        pass
    return list(candidates.values())


def _reference_sheet_layout(data, preferred_sheet=''):
    sheets = data.get('sheets') if isinstance(data, dict) else []
    ordered = list(sheets or [])
    if preferred_sheet:
        ordered.sort(key=lambda item: 0 if str(item.get('name') or '') == preferred_sheet else 1)
    layouts = []
    for sheet in ordered:
        if not isinstance(sheet, dict):
            continue
        rows = sheet.get('rows') if isinstance(sheet.get('rows'), list) else []
        header_index = -1
        for index, row in enumerate(rows):
            cells = row.get('cells') if isinstance(row, dict) else None
            if isinstance(cells, dict) and str(cells.get('A') or '').strip().lower() == 'id':
                header_index = index
        if header_index < 0:
            continue
        header_cells = rows[header_index].get('cells') or {}
        headers = {
            str(column): str(value or '').strip()
            for column, value in header_cells.items()
            if str(value or '').strip()
        }
        layouts.append({
            'name': str(sheet.get('name') or '').strip(),
            'rows': rows,
            'header_index': header_index,
            'headers': headers,
        })
    return layouts


def _reference_row_record(layout, physical_row):
    index = physical_row - 1
    rows = layout.get('rows') or []
    if index < 0 or index >= len(rows):
        return None
    row = rows[index]
    cells = row.get('cells') if isinstance(row, dict) else None
    if not isinstance(cells, dict):
        return None
    fields = []
    for column, raw_value in sorted(cells.items(), key=lambda item: _column_number(item[0])):
        value = str(raw_value or '').strip()
        if not value:
            continue
        fields.append({
            'column': str(column),
            'header': _truncate(layout.get('headers', {}).get(str(column)) or column, 240),
            'value': _truncate(value, 800),
        })
    if not fields:
        return None
    return {
        'sheet': layout.get('name') or '',
        'physical_row': physical_row,
        'id': str(cells.get('A') or '').strip(),
        'fields': fields[:KONGMING_MAX_REFERENCE_FIELDS],
    }


def _reference_scalar_id(value):
    text = str(value or '').strip()
    if not re.fullmatch(r'\d{4,}', text):
        return ''
    return text


def build_kongming_reference_evidence(
    question, context, excel_root, json_root, table_candidates, branch_comparison=None
):
    """Resolve explicit physical rows and config IDs across tables into deterministic evidence."""
    combined = '\n'.join((str(question or ''), str(context or '')))
    row_query = _parse_physical_row_ranges(combined)
    candidates = _discover_reference_table_candidates(combined, table_candidates, json_root)
    if not candidates:
        return None

    target_candidates = sorted(
        candidates,
        key=lambda item: (
            -_reference_table_candidate_score(item, combined, target=True),
            str(item.get('json_path') or ''),
        ),
    )
    target = target_candidates[0] if target_candidates else None
    target_score = _reference_table_candidate_score(target or {}, combined, target=True)
    explicit_target_requested = any(hint in combined.lower() for hint in _REFERENCE_TABLE_HINTS)
    if target_score <= 0 and not explicit_target_requested:
        return None

    target_ref = ''
    if isinstance(branch_comparison, dict) and branch_comparison.get('status') == 'compared':
        target_ref = str(branch_comparison.get('target_branch') or '')
    target_data = _load_json_table(target, json_root, excel_root, target_ref)
    target_layouts = _reference_sheet_layout(target_data)
    if not target_layouts:
        return None

    explicit_ids = set(
        value for value in re.findall(r'(?<!\d)(\d{4,})(?!\d)', combined)
        if value not in {str(row) for row in row_query.get('rows') or []}
    )
    target_rows = []
    for layout in target_layouts:
        for physical_row in row_query.get('rows') or []:
            record = _reference_row_record(layout, physical_row)
            if record:
                target_rows.append(record)
        if not row_query.get('rows') and explicit_ids:
            for physical_row, row in enumerate(layout.get('rows') or [], start=1):
                cells = row.get('cells') if isinstance(row, dict) else None
                if not isinstance(cells, dict):
                    continue
                if str(cells.get('A') or '').strip() not in explicit_ids:
                    continue
                record = _reference_row_record(layout, physical_row)
                if record:
                    target_rows.append(record)
                if len(target_rows) >= KONGMING_MAX_REFERENCE_ROWS:
                    break
    target_rows = target_rows[:KONGMING_MAX_REFERENCE_ROWS]
    target_ids = {
        record['id'] for record in target_rows if _reference_scalar_id(record.get('id'))
    }
    target_ids.update(value for value in explicit_ids if any(
        _reference_scalar_id(record.get('id')) == value for record in target_rows
    ))

    source_field_terms = {
        value.lower() for value in re.findall(r'[A-Za-z][A-Za-z0-9_.-]{2,}', combined)
    }
    references = []
    source_tables_checked = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -_reference_table_candidate_score(item, combined, target=False),
            str(item.get('json_path') or ''),
        ),
    ):
        if candidate is target:
            continue
        candidate_terms = {
            str(value or '').lower()
            for value in candidate.get('matched_terms') or []
        }
        candidate_path = str(candidate.get('json_path') or '').lower()
        source_candidate = bool(
            _reference_table_candidate_score(candidate, combined, target=False) > 100
            or candidate_terms.intersection(source_field_terms)
            or any(marker in candidate_path for marker in ('activity', 'event'))
        )
        if not source_candidate:
            continue
        data = _load_json_table(candidate, json_root, excel_root, target_ref)
        layouts = _reference_sheet_layout(data)
        if not layouts:
            continue
        source_tables_checked.append(candidate.get('xlsx_path') or candidate.get('json_path') or '')
        for layout in layouts:
            rows = layout.get('rows') or []
            for physical_row, row in enumerate(rows, start=1):
                cells = row.get('cells') if isinstance(row, dict) else None
                if not isinstance(cells, dict):
                    continue
                for column, raw_value in cells.items():
                    value = _reference_scalar_id(raw_value)
                    if not value or value not in target_ids:
                        continue
                    header = str(layout.get('headers', {}).get(str(column)) or column).strip()
                    lowered_header = header.lower()
                    if (
                        source_field_terms
                        and lowered_header not in source_field_terms
                        and str(column).lower() not in source_field_terms
                        and not any(hint in lowered_header for hint in _REFERENCE_FIELD_HINTS)
                    ):
                        continue
                    target_matches = [
                        item for item in target_rows if item.get('id') == value
                    ]
                    references.append({
                        'source_table': candidate.get('xlsx_path') or candidate.get('json_path') or '',
                        'source_sheet': layout.get('name') or '',
                        'source_physical_row': physical_row,
                        'source_field': str(column),
                        'source_header': _truncate(header, 240),
                        'source_value': value,
                        'target_table': target.get('xlsx_path') or target.get('json_path') or '',
                        'target_rows': target_matches,
                    })
                    if len(references) >= KONGMING_MAX_REFERENCE_RELATIONS:
                        break
                if len(references) >= KONGMING_MAX_REFERENCE_RELATIONS:
                    break
            if len(references) >= KONGMING_MAX_REFERENCE_RELATIONS:
                break
        if len(references) >= KONGMING_MAX_REFERENCE_RELATIONS:
            break

    if not target_rows and not references:
        return None
    return {
        'status': 'confirmed' if target_rows else 'unresolved',
        'physical_row_query': {
            'ranges': row_query.get('ranges') or [],
            'rows': row_query.get('rows') or [],
            'truncated': bool(row_query.get('truncated')),
        },
        'target_table': target.get('xlsx_path') or target.get('json_path') or '',
        'target_branch': target_ref,
        'target_headers': [
            {
                'column': column,
                'name': _truncate(name, 240),
            }
            for layout in target_layouts[:12]
            for column, name in sorted(
                layout.get('headers', {}).items(),
                key=lambda item: _column_number(item[0]),
            )
        ][:KONGMING_MAX_REFERENCE_FIELDS],
        'target_rows': target_rows,
        'references': references,
        'source_tables_checked': list(dict.fromkeys(source_tables_checked))[:20],
        'message': (
            '已读取目标表的指定物理行，并按字段值与来源表建立引用关系。'
            if references else '已读取目标表的指定物理行，但暂未找到来源字段引用。'
        ),
    }


def _building_season_level_fact(question, terms, json_root, table_candidates):
    source = unicodedata.normalize('NFKC', str(question or '')).lower()
    if not (
        any(marker in source for marker in ('赛季', 'season'))
        and any(marker in source for marker in ('等级', 'level', 'lv'))
        and any(marker in source for marker in ('上限', '最高', 'limit', 'max'))
    ):
        return None
    candidate = next((
        item for item in (table_candidates or [])
        if str(item.get('json_path') or '').replace('\\', '/').lower().endswith(
            '/coa_ab_buildinglevel.json'
        )
    ), None)
    if not candidate:
        return None
    path = os.path.abspath(os.path.join(
        json_root,
        str(candidate.get('json_path') or '').replace('/', os.sep),
    ))
    try:
        if os.path.commonpath((os.path.abspath(json_root), path)) != os.path.abspath(json_root):
            return None
        with open(path, 'r', encoding='utf-8-sig') as source_file:
            data = json.load(source_file)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    entity_terms = {
        str(term).lower() for term in terms
        if str(term or '').strip() and str(term).lower() not in {
            '赛季', '等级', '上限', 'season', 'level', 'limit',
        }
    }
    buildings = {}
    association_rows = []
    for sheet in data.get('sheets') or []:
        if not isinstance(sheet, dict):
            continue
        sheet_name = str(sheet.get('name') or '')
        for row in sheet.get('rows') or []:
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            if sheet_name.startswith('BuildingLevel'):
                name = str(cells.get('C') or '').strip()
                build_id = str(cells.get('B') or '').strip()
                levels = [
                    int(value) for value in str(cells.get('D') or '').split(';')
                    if value.strip().isdigit()
                ]
                if (
                    build_id.isdigit() and levels and name
                    and any(term in name.lower() for term in entity_terms)
                ):
                    item = buildings.setdefault(build_id, {
                        'name': name,
                        'levels': set(),
                        'sheets': [],
                    })
                    item['levels'].update(levels)
                    if sheet_name not in item['sheets']:
                        item['sheets'].append(sheet_name)
            elif sheet_name == 'BuildingAssociationB':
                level = cells.get('B')
                season = cells.get('D')
                build_name = str(cells.get('F') or '')
                if isinstance(level, (int, float)) and isinstance(season, (int, float)):
                    association_rows.append({
                        'level': int(level),
                        'season': int(season),
                        'build_name': build_name,
                    })

    facts = []
    for build_id, building in buildings.items():
        levels = sorted(building['levels'])
        unlocks = {}
        marker = f'_{build_id}_'
        for row in association_rows:
            if marker not in row['build_name'] or row['season'] <= 0:
                continue
            unlocks.setdefault(row['season'], []).append(row['level'])
        if not unlocks:
            continue
        stages = [
            {
                'season': season,
                'min_level': min(stage_levels),
                'max_level': max(stage_levels),
            }
            for season, stage_levels in sorted(unlocks.items())
        ]
        ranges = []
        first_unlock_level = min(stage['min_level'] for stage in stages)
        current_start = 1
        current_max = first_unlock_level - 1
        for stage in stages:
            if stage['season'] > current_start:
                ranges.append({
                    'season_from': current_start,
                    'season_to': stage['season'] - 1,
                    'max_level': current_max,
                })
            current_start = stage['season']
            current_max = max(current_max, stage['max_level'])
        ranges.append({
            'season_from': current_start,
            'season_to': None,
            'max_level': current_max,
        })
        facts.append({
            'type': 'building_season_level_limits',
            'entity': building['name'],
            'build_id': int(build_id),
            'configured_min_level': min(levels),
            'configured_max_level': max(levels),
            'season_unlock_stages': stages,
            'season_level_limits': ranges,
            'source': candidate.get('xlsx_path') or '',
            'level_sheets': building['sheets'],
            'association_sheet': 'BuildingAssociationB',
            'confidence': 'derived_from_complete_rows',
        })
    return facts[0] if facts else None


def _client_search_terms(question_terms, table_candidates):
    terms = list(question_terms)
    top_score = int(table_candidates[0].get('score') or 0) if table_candidates else 0
    focused_tables = [
        table for table in table_candidates[:3]
        if int(table.get('score') or 0) >= max(1, int(top_score * .75))
    ]
    for table in focused_tables:
        stem = os.path.splitext(os.path.basename(table.get('xlsx_path') or ''))[0]
        for value in (stem, *(table.get('sheets') or [])[:8]):
            if value and len(value) >= 3 and value not in terms:
                terms.append(value)
            if len(terms) >= 20:
                return terms
    return terms


def _read_client_summary(path, matched_by, client_root):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as source:
            content = source.read(2 * 1024 * 1024)
    except OSError:
        content = ''
    content_lower = content.lower()
    actual_terms = {term for term in matched_by if term.lower() in content_lower}
    terms = sorted(actual_terms, key=len, reverse=True)
    snippets = []
    lines = content.splitlines()
    used_lines = set()
    for index, line in enumerate(lines):
        line_lower = line.lower()
        hit_terms = [term for term in terms if term.lower() in line_lower]
        if not hit_terms:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        if any(number in used_lines for number in range(start, end)):
            continue
        snippet = '\n'.join(
            f'{number + 1}: {_truncate(lines[number], 520)}'
            for number in range(start, end)
        )
        snippets.append({'matched_terms': hit_terms, 'text': snippet})
        used_lines.update(range(start, end))
        if len(snippets) >= KONGMING_MAX_CLIENT_SNIPPETS:
            break
    relative = os.path.relpath(path, client_root).replace('\\', '/')
    score = len(actual_terms) * 8 + len(snippets) * 3
    lowered = relative.lower()
    if '/modules/logic/' in '/' + lowered:
        score += 8
    if '/creator/assets/scripts/' in '/' + lowered:
        score += 4
    return {
        'path': relative,
        'matched_terms': sorted(actual_terms),
        'snippets': snippets,
        'score': score,
    }


def _table_path_score(path, matched_by):
    lowered = path.replace('\\', '/').lower()
    stem = os.path.splitext(os.path.basename(lowered))[0]
    normalized_stem = re.sub(r'^(sg_)?coa_', '', stem)
    score = len(matched_by) * 4
    score += sum(
        60 for term in matched_by
        if term.lower() in stem or term.lower() in normalized_stem
    )
    if '/common/' in lowered:
        score += 10
    if '/language/' in lowered:
        score -= 100
    return score


def _client_path_score(path, matched_by):
    lowered = path.replace('\\', '/').lower()
    score = len(matched_by) * 5
    if '/modules/logic/' in lowered:
        score += 20
    if '/creator/assets/scripts/' in lowered:
        score += 8
    if any(term.lower() in lowered for term in matched_by):
        score += 12
    if '/tools/' in lowered or '/test/' in lowered or '/tests/' in lowered:
        score -= 20
    return score


def _fit_evidence(evidence):
    while True:
        serialized = json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))
        if len(serialized) <= KONGMING_MAX_EVIDENCE_CHARS:
            evidence['serialized_chars'] = len(serialized)
            return evidence
        clients = evidence.get('client_candidates') or []
        tables = evidence.get('table_candidates') or []
        commands = evidence.get('gm_command_candidates') or []
        if len(clients) > 6:
            clients.pop()
            continue
        if len(tables) > 4:
            tables.pop()
            continue
        if len(commands) > 6:
            commands.pop()
            continue
        for client in clients:
            snippets = client.get('snippets') or []
            if len(snippets) > 2:
                snippets.pop()
                break
        else:
            evidence['truncated'] = True
            evidence['serialized_chars'] = len(serialized)
            return evidence


def _branch_version_value(value):
    source = str(value or '')
    matches = re.findall(r'(?<!\d)(20\d{6})(?!\d)', source)
    if matches:
        return int(matches[-1])
    matches = re.findall(r'(?<!\d)(0[1-9]\d{2})(?!\d)', source)
    if matches:
        return 20_260000 + int(matches[-1])
    return 0


def _branch_request_tokens(question):
    source = str(question or '')
    tokens = []
    for match in re.finditer(
        r'(?i)(?<![A-Za-z0-9])(?:(?:release)[\\/_-]?)?(?:v)?'
        r'(20\d{6}|0[1-9]\d{2})(?![A-Za-z0-9])',
        source,
    ):
        token = match.group(1)
        context = source[max(0, match.start() - 12):min(len(source), match.end() + 12)]
        explicit_ref = bool(re.search(r'(?i)release|(?<![A-Za-z0-9])v20', match.group(0)))
        if len(token) == 4 and not explicit_ref and not re.search(
            r'分支|版本|branch|commit|diff', context, flags=re.IGNORECASE
        ):
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens[:4]


def _branch_comparison_requested(question):
    source = str(question or '')
    return bool(
        _branch_request_tokens(source)
        and any(marker.lower() in source.lower() for marker in _BRANCH_COMPARE_MARKERS)
    )


def _git_branch_refs(repo_root):
    git_path = shutil.which('git')
    if not git_path or not os.path.isdir(os.path.join(repo_root, '.git')):
        return []
    try:
        result = subprocess.run(
            [git_path, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/remotes'],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _resolve_branch_ref(refs, token):
    token = str(token or '').strip().lower()
    if not token:
        return ''
    exact = [ref for ref in refs if ref.lower() == token]
    if exact:
        return sorted(exact, key=lambda ref: ref.lower().startswith('origin/'))[0]
    version = _branch_version_value(token)
    candidates = [
        ref for ref in refs
        if version and _branch_version_value(ref) == version
        and ('release' in ref.lower() or 'v20' in ref.lower() or ref.lower().endswith(token))
    ]
    candidates.sort(key=lambda ref: (
        ref.lower().startswith('origin/'),
        0 if ref.lower().startswith('release/') else 1,
        len(ref),
        ref.lower(),
    ))
    return candidates[0] if candidates else ''


def _infer_previous_branch(refs, target_ref):
    target_version = _branch_version_value(target_ref)
    candidates = [
        ref for ref in refs
        if target_version and 0 < _branch_version_value(ref) < target_version
        and re.search(r'(?i)(?:release[\\/_-]?v20|v20)', ref)
    ]
    candidates.sort(key=lambda ref: (
        -_branch_version_value(ref),
        ref.lower().startswith('origin/'),
        len(ref),
        ref.lower(),
    ))
    return candidates[0] if candidates else ''


def _git_show_json(repo_root, ref, relative_json_path):
    git_path = shutil.which('git')
    if not git_path or not ref or not relative_json_path:
        return None
    # Git object paths always use '/', including on Windows.
    repo_path = 'json/' + relative_json_path.replace('\\', '/').lstrip('/')
    try:
        result = subprocess.run(
            [git_path, 'show', f'{ref}:{repo_path}'],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _column_number(value):
    number = 0
    for char in str(value or '').upper():
        if not 'A' <= char <= 'Z':
            return 0
        number = number * 26 + ord(char) - ord('A') + 1
    return number


def _table_headers_by_sheet(data):
    result = {}
    sheets = data.get('sheets') if isinstance(data, dict) else []
    for sheet in sheets or []:
        if not isinstance(sheet, dict):
            continue
        sheet_name = str(sheet.get('name') or '').strip()
        if not sheet_name:
            continue
        header = None
        for row in sheet.get('rows') or []:
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            if str(cells.get('A') or '').strip().lower() == 'id':
                header = cells
                break
        if not header:
            continue
        result[sheet_name] = {
            str(value).strip(): {'column': column}
            for column, value in sorted(header.items(), key=lambda item: _column_number(item[0]))
            if str(value or '').strip()
        }
    return result


def _relevant_branch_fields(fields, question):
    source = str(question or '').lower()
    has_guarantee = any(marker in source for marker in ('保底', 'mercy', 'miss', 'pity', 'guarantee'))
    has_crown = any(marker in source for marker in ('金冠', 'golden', 'crown'))
    if not has_guarantee and not has_crown:
        return list(fields)
    if has_guarantee:
        guarantee_hints = ('mercy', 'miss', 'pity', 'guarantee')
        return [
            field for field in fields
            if any(marker in field.lower() for marker in guarantee_hints)
            or (has_crown and 'crown' in field.lower() and 'mercy' in field.lower())
        ]
    return [
        field for field in fields
        if 'golden' in field.lower() or 'crown' in field.lower()
    ]


def _first_data_row_by_id(data):
    result = {}
    sheets = data.get('sheets') if isinstance(data, dict) else []
    for sheet in sheets or []:
        if not isinstance(sheet, dict):
            continue
        rows = sheet.get('rows') or []
        last_header_index = -1
        for index, row in enumerate(rows):
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            if str(cells.get('A') or '').strip().lower() == 'id':
                last_header_index = index
        if last_header_index < 0:
            continue
        for row in rows[last_header_index + 1:]:
            cells = row.get('cells') if isinstance(row, dict) else None
            if isinstance(cells, dict) and isinstance(cells.get('A'), (int, float)):
                result[str(sheet.get('name') or '')] = cells
                break
    return result


def build_kongming_branch_comparison(question, excel_root, table_candidates):
    if not _branch_comparison_requested(question):
        return None
    table = next((
        item for item in (table_candidates or [])
        if isinstance(item, dict) and item.get('json_path')
    ), None)
    if not table:
        return {
            'status': 'table_not_found',
            'requested_branches': _branch_request_tokens(question),
            'message': '未找到可用于分支对比的配置表候选。',
        }

    refs = _git_branch_refs(excel_root)
    requested_tokens = _branch_request_tokens(question)
    resolved = []
    for token in requested_tokens:
        ref = _resolve_branch_ref(refs, token)
        if ref and ref not in [item['ref'] for item in resolved]:
            resolved.append({'token': token, 'ref': ref})
    if not resolved:
        return {
            'status': 'branch_not_found',
            'table': table.get('xlsx_path') or '',
            'requested_branches': requested_tokens,
            'available_release_branches': [
                ref for ref in refs if re.search(r'(?i)release[\\/_-]?v20', ref)
            ][:20],
            'message': '未找到问题中指定的本地分支，无法完成分支对比。',
        }

    resolved.sort(key=lambda item: _branch_version_value(item['ref']))
    base_ref = resolved[0]['ref'] if len(resolved) > 1 else _infer_previous_branch(refs, resolved[0]['ref'])
    target_ref = resolved[-1]['ref']
    if not base_ref or base_ref == target_ref:
        return {
            'status': 'base_branch_not_found',
            'table': table.get('xlsx_path') or '',
            'target_branch': target_ref,
            'requested_branches': requested_tokens,
            'message': '找到了目标分支，但没有找到可用于比较的上一版分支。',
        }

    relative_json_path = str(table.get('json_path') or '').replace('\\', '/')
    base_data = _git_show_json(excel_root, base_ref, relative_json_path)
    target_data = _git_show_json(excel_root, target_ref, relative_json_path)
    if not isinstance(base_data, dict) or not isinstance(target_data, dict):
        return {
            'status': 'file_not_found',
            'table': table.get('xlsx_path') or '',
            'base_branch': base_ref,
            'target_branch': target_ref,
            'message': '分支中缺少可解析的配置 JSON，无法完成字段对比。',
        }

    base_sheets = _table_headers_by_sheet(base_data)
    target_sheets = _table_headers_by_sheet(target_data)
    base_rows = _first_data_row_by_id(base_data)
    target_rows = _first_data_row_by_id(target_data)
    sheet_results = []
    sheet_names = list(target_sheets) + [name for name in base_sheets if name not in target_sheets]
    for sheet_name in sheet_names:
        before = base_sheets.get(sheet_name, {})
        after = target_sheets.get(sheet_name, {})
        before_fields = list(before)
        after_fields = list(after)
        added = [field for field in after_fields if field not in before]
        removed = [field for field in before_fields if field not in after]
        common = [field for field in after_fields if field in before]
        relevant = _relevant_branch_fields(list(dict.fromkeys(after_fields + before_fields)), question)
        moved = [
            {'field': field, 'from': before[field]['column'], 'to': after[field]['column']}
            for field in common
            if before[field]['column'] != after[field]['column'] and field in relevant
        ]
        field_statuses = []
        for field in relevant:
            if field not in before and field in after:
                status = 'added'
            elif field in before and field not in after:
                status = 'removed'
            elif before[field]['column'] != after[field]['column']:
                status = 'existing_moved'
            else:
                status = 'existing'
            field_statuses.append({
                'field': field,
                'status': status,
                'base_column': before.get(field, {}).get('column', ''),
                'target_column': after.get(field, {}).get('column', ''),
                'base_sample': str((base_rows.get(sheet_name) or {}).get(before.get(field, {}).get('column', ''), ''))[:160],
                'target_sample': str((target_rows.get(sheet_name) or {}).get(after.get(field, {}).get('column', ''), ''))[:160],
            })
        if added or removed or moved or field_statuses:
            sheet_results.append({
                'sheet': sheet_name,
                'added_fields': added,
                'removed_fields': removed,
                'moved_fields': moved,
                'field_statuses': field_statuses,
            })

    relevant_statuses = [
        item for sheet in sheet_results for item in sheet.get('field_statuses') or []
    ]
    added_relevant = [item['field'] for item in relevant_statuses if item['status'] == 'added']
    existing_relevant = [
        item['field'] for item in relevant_statuses
        if item['status'] in ('existing', 'existing_moved')
    ]
    conclusion = (
        f'对比 {base_ref} 与 {target_ref}：'
        + (f'相关新增字段为 {"、".join(added_relevant)}；' if added_relevant else '未发现相关字段新增；')
        + (f'{"、".join(existing_relevant)} 在基线分支已存在。' if existing_relevant else '')
    )
    return {
        'status': 'compared',
        'repository': 'excel',
        'table': table.get('xlsx_path') or '',
        'base_branch': base_ref,
        'target_branch': target_ref,
        'conclusion': conclusion,
        'sheets': sheet_results[:12],
    }


def build_kongming_evidence(
    question, client_root, excel_root, json_root, context='', index_path='',
    gm_commands_path=''
):
    started_at = time.time()
    combined_context = '\n'.join((str(question or ''), str(context or '')))
    terms = extract_kongming_search_terms(combined_context)
    gm_command_requested = _gm_command_requested(question)
    reference_requested = bool(
        _parse_physical_row_ranges(combined_context).get('rows')
        or any(hint in combined_context.lower() for hint in _REFERENCE_TABLE_HINTS)
    )
    if not terms and not gm_command_requested and not reference_requested:
        return {
            'keywords': [],
            'table_candidates': [],
            'client_candidates': [],
            'gm_command_candidates': [],
            'duration_ms': int((time.time() - started_at) * 1000),
            'message': '未能提取有效检索词，需要孔明进行定向分析。',
        }

    gm_commands = _search_gm_commands(question, terms, gm_commands_path)

    table_paths = {}
    index_status = {}
    table_search_source = 'rg'
    if index_path:
        table_paths, index_status = search_kongming_index(
            index_path,
            json_root,
            terms,
            limit=500,
        )
        if table_paths:
            table_search_source = 'index'
    index_state = index_status.get('state', '')
    needs_fallback = not table_paths or index_state in ('queued', 'building', 'updating', 'failed')
    if needs_fallback:
        fallback_paths = _run_rg_files(json_root, terms, ('*.json',), 100)
        for path, matched_terms in fallback_paths.items():
            table_paths.setdefault(path, set()).update(matched_terms)
        if table_search_source == 'index' and fallback_paths:
            table_search_source = 'hybrid'
    prioritized_table_paths = sorted(
        table_paths.items(),
        key=lambda item: (-_table_path_score(item[0], item[1]), item[0]),
    )[:24]
    tables = [
        _summarize_json_table(path, matched_by, json_root)
        for path, matched_by in prioritized_table_paths
    ]
    tables.sort(key=lambda item: (-item.get('score', 0), item.get('json_path', '')))
    tables = [item for item in tables if item.get('score', 0) >= 0][:KONGMING_MAX_TABLE_CANDIDATES]
    building_season_level_fact = _building_season_level_fact(
        question, terms, json_root, tables
    )
    branch_comparison = build_kongming_branch_comparison(combined_context, excel_root, tables)
    reference_evidence = build_kongming_reference_evidence(
        question,
        context,
        excel_root,
        json_root,
        tables,
        branch_comparison=branch_comparison,
    )

    client_terms = _client_search_terms(terms, tables)
    client_paths = _run_rg_files(
        client_root,
        client_terms,
        _CLIENT_GLOBS,
        500,
        exclude_tool=True,
    )
    prioritized_client_paths = sorted(
        client_paths.items(),
        key=lambda item: (-_client_path_score(item[0], item[1]), item[0]),
    )[:50]
    clients = [
        _read_client_summary(path, matched_by, client_root)
        for path, matched_by in prioritized_client_paths
    ]
    clients.sort(key=lambda item: (-item.get('score', 0), item.get('path', '')))
    clients = clients[:KONGMING_MAX_CLIENT_CANDIDATES]

    evidence = {
        'version': 4,
        'keywords': terms,
        'table_candidates': tables,
        'client_candidates': clients,
        'gm_command_candidates': gm_commands,
        'duration_ms': int((time.time() - started_at) * 1000),
        'table_search': {
            'source': table_search_source,
            'index_state': index_state or 'disabled',
            'index_generation': int(index_status.get('generation') or 0),
        },
        'search_roots': {
            'client': os.path.abspath(client_root),
            'excel': os.path.abspath(excel_root),
            'json': os.path.abspath(json_root),
            'gm_commands': os.path.abspath(gm_commands_path) if gm_commands_path else '',
        },
    }
    if gm_command_requested:
        evidence['gm_command_search'] = {
            'requested': True,
            'matched': bool(gm_commands),
            'candidate_count': len(gm_commands),
        }
        if not gm_commands:
            evidence['gm_command_search']['message'] = (
                '本地 GM 命令库中没有找到与当前问题匹配的真实命令。'
            )
    if building_season_level_fact:
        evidence['derived_facts'] = [building_season_level_fact]
    if branch_comparison:
        evidence['branch_comparison'] = branch_comparison
    if reference_evidence:
        evidence['reference_evidence'] = reference_evidence
    return _fit_evidence(evidence)
