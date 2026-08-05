import json
import os
import stat
import subprocess


class KongmingBridgeError(RuntimeError):
    pass


def _absolute_path(path, workspace):
    value = os.path.expandvars(os.path.expanduser(str(path or '').strip()))
    if not value:
        return ''
    if not os.path.isabs(value):
        value = os.path.join(workspace, value)
    return os.path.abspath(value)


def load_kongming_source(workspace, config_file, environ=None):
    workspace = os.path.abspath(workspace)
    environ = os.environ if environ is None else environ
    environment_path = str(environ.get('GM_KONGMING_SKILLS_DIR') or '').strip()
    if environment_path:
        return _absolute_path(environment_path, workspace), 'environment'

    configured_path = ''
    try:
        with open(config_file, 'r', encoding='utf-8') as source:
            payload = json.load(source)
        if isinstance(payload, dict):
            configured_path = str(payload.get('source_dir') or '').strip()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    if configured_path:
        return _absolute_path(configured_path, workspace), 'saved'
    return os.path.join(workspace, '.claude', 'skills'), 'default'


def save_kongming_source(config_file, source_dir, workspace):
    source_dir = _absolute_path(source_dir, workspace)
    if not source_dir:
        raise ValueError('请填写孔明 Skill 源目录')
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    temporary_file = config_file + '.tmp'
    with open(temporary_file, 'w', encoding='utf-8') as target:
        json.dump({'source_dir': source_dir}, target, ensure_ascii=False, indent=2)
    os.replace(temporary_file, config_file)
    return source_dir


def _same_path(left, right):
    if not left or not right:
        return False
    return os.path.normcase(os.path.realpath(os.path.abspath(left))) == os.path.normcase(
        os.path.realpath(os.path.abspath(right))
    )


def _is_directory_junction(path):
    if os.name != 'nt' or os.path.islink(path):
        return False
    try:
        path_stat = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(path_stat, 'st_file_attributes', 0)
    reparse_tag = getattr(path_stat, 'st_reparse_tag', 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) and (
        reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    )


def _is_directory_link(path):
    return os.path.islink(path) or _is_directory_junction(path)


def _resolved_link_target(link_path):
    raw_target = os.readlink(link_path)
    normalized_target = raw_target[4:] if raw_target.startswith('\\\\?\\') else raw_target
    if os.path.isabs(normalized_target):
        return os.path.abspath(normalized_target), raw_target
    resolved = os.path.abspath(os.path.join(os.path.dirname(link_path), normalized_target))
    return resolved, raw_target


def _directory_entries(source_dir, require_skill_file=False):
    if not os.path.isdir(source_dir):
        return []
    entries = []
    for entry in os.scandir(source_dir):
        try:
            is_directory = entry.is_dir(follow_symlinks=True)
        except OSError:
            is_directory = False
        if not is_directory:
            continue
        if require_skill_file and not os.path.isfile(os.path.join(entry.path, 'SKILL.md')):
            continue
        entries.append(entry)
    return sorted(entries, key=lambda item: item.name.casefold())


def _relative_link_target(target_path, link_parent):
    try:
        return os.path.relpath(target_path, link_parent)
    except ValueError:
        return os.path.abspath(target_path)


def _create_directory_link(link_path, target_path):
    link_target = _relative_link_target(target_path, os.path.dirname(link_path))
    try:
        os.symlink(link_target, link_path, target_is_directory=True)
        return 'symlink'
    except OSError as exc:
        if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
            completed = subprocess.run(
                [
                    os.environ.get('COMSPEC', 'cmd.exe'),
                    '/d',
                    '/c',
                    'mklink',
                    '/J',
                    os.path.abspath(link_path),
                    os.path.abspath(target_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='mbcs',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if completed.returncode == 0 and _is_directory_junction(link_path):
                return 'junction'
            diagnostic = (completed.stderr or completed.stdout or '').strip()
            raise KongmingBridgeError(f'创建 Windows 目录联接失败：{diagnostic or exc}') from exc
        raise KongmingBridgeError(f'创建 Skill 符号链接失败：{exc}') from exc


def get_kongming_bridge_status(workspace, source_dir):
    workspace = os.path.abspath(workspace)
    source_dir = _absolute_path(source_dir, workspace)
    agents_dir = os.path.join(workspace, '.agents')
    discovery_dir = os.path.join(agents_dir, 'skills')
    source_exists = os.path.isdir(source_dir)
    source_skills = _directory_entries(source_dir, require_skill_file=True)

    link_target = ''
    resolved_link_target = ''
    direct_link = _is_directory_link(discovery_dir)
    link_kind = 'symlink' if os.path.islink(discovery_dir) else ('junction' if direct_link else '')
    direct_link_matches = False
    if direct_link:
        try:
            resolved_link_target, link_target = _resolved_link_target(discovery_dir)
            direct_link_matches = _same_path(resolved_link_target, source_dir)
        except OSError:
            pass

    discovery_exists = os.path.lexists(discovery_dir)
    discovery_is_directory = os.path.isdir(discovery_dir)
    skills = []
    for entry in source_skills:
        exposed_path = os.path.join(discovery_dir, entry.name)
        if direct_link_matches:
            exposure = 'linked'
        elif _is_directory_link(exposed_path):
            try:
                exposed_target, _ = _resolved_link_target(exposed_path)
                exposure = 'linked' if _same_path(exposed_target, entry.path) else 'existing'
            except OSError:
                exposure = 'existing'
        elif os.path.lexists(exposed_path):
            exposure = 'existing'
        else:
            exposure = 'missing'
        skills.append({
            'name': entry.name,
            'source_path': entry.path,
            'exposed_path': exposed_path,
            'exposure': exposure,
            'exposed': exposure != 'missing',
        })

    exposed_count = sum(1 for item in skills if item['exposed'])
    if not link_kind and any(item['exposure'] == 'linked' for item in skills):
        link_kind = 'merged'
    if not source_exists:
        state = 'source_missing'
        ready = False
        message = '尚未找到孔明 Skill 源目录，请确认公司孔明目录后重新建立桥接。'
    elif not source_skills:
        state = 'source_empty'
        ready = False
        message = '源目录中未发现包含 SKILL.md 的孔明 Skill。'
    elif direct_link_matches:
        state = 'linked'
        ready = True
        link_label = 'Windows 目录联接' if link_kind == 'junction' else '符号链接'
        message = f'孔明 Skill 已通过{link_label}接入 Codex。'
    elif direct_link:
        state = 'conflict'
        ready = False
        message = '发现目录已链接到其他位置，为避免覆盖已停止操作。'
    elif not discovery_exists:
        state = 'unlinked'
        ready = False
        message = '孔明 Skill 已识别，等待建立桥接。'
    elif not discovery_is_directory:
        state = 'conflict'
        ready = False
        message = '.agents/skills 已被文件占用，为避免覆盖已停止操作。'
    elif exposed_count == len(skills):
        state = 'merged'
        ready = True
        message = '孔明 Skill 已合并到现有 Codex Skill 目录，同名目录保持原样。'
    else:
        state = 'merge_pending'
        ready = False
        message = '检测到现有 Codex Skill 目录，等待合并孔明 Skill。'

    return {
        'workspace': workspace,
        'source_dir': source_dir,
        'source_exists': source_exists,
        'agents_dir': agents_dir,
        'discovery_dir': discovery_dir,
        'discovery_exists': discovery_exists,
        'link_target': link_target,
        'link_kind': link_kind,
        'resolved_link_target': resolved_link_target,
        'state': state,
        'ready': ready,
        'message': message,
        'skill_count': len(skills),
        'exposed_count': exposed_count,
        'skills': skills,
    }


def ensure_agents_skills_link(workspace, source_dir):
    workspace = os.path.abspath(workspace)
    source_dir = _absolute_path(source_dir, workspace)
    before = get_kongming_bridge_status(workspace, source_dir)
    before.update({'changed': False, 'created': [], 'skipped': []})
    if not before['source_exists'] or before['state'] == 'source_empty':
        return before

    discovery_dir = before['discovery_dir']
    if before['state'] in ('linked', 'merged'):
        before['skipped'] = [item['name'] for item in before['skills']]
        return before
    if before['state'] == 'conflict':
        return before

    os.makedirs(before['agents_dir'], exist_ok=True)
    created = []
    skipped = []
    if not os.path.lexists(discovery_dir):
        _create_directory_link(discovery_dir, source_dir)
        created.append('skills')
    elif os.path.isdir(discovery_dir):
        for entry in _directory_entries(source_dir):
            destination = os.path.join(discovery_dir, entry.name)
            if os.path.lexists(destination):
                skipped.append(entry.name)
                continue
            _create_directory_link(destination, entry.path)
            created.append(entry.name)

    after = get_kongming_bridge_status(workspace, source_dir)
    after.update({
        'changed': bool(created),
        'created': created,
        'skipped': skipped,
    })
    return after
