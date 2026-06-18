#!/usr/bin/env python3
"""
Xshell Session 文件自动生成器

功能一 (generate): 模板 .xsh + CSV -> 批量生成 session 文件
功能二 (update-pwd): 从源 session 提取加密密码，批量替换到目标 session
"""

import argparse
import csv
import glob
import os
import re
import sys
from pathlib import Path

# ============================================================
# 常量
# ============================================================
PLACEHOLDER_HOST = '{{HOST}}'

# CSV 列名映射（中英文兼容）
COLUMN_MAP = {
    # SessionName
    'sessionname': 'SessionName',
    '会话名': 'SessionName',
    '名称': 'SessionName',
    '设备名': 'SessionName',
    'name': 'SessionName',
    'session': 'SessionName',
    'session_name': 'SessionName',
    # Host
    'host': 'Host',
    'ip': 'Host',
    '管理ip': 'Host',
    '地址': 'Host',
    'ip地址': 'Host',
    'hostip': 'Host',
    'host_ip': 'Host',
    '设备ip': 'Host',
    # Group
    'group': 'Group',
    '分组': 'Group',
    '目录': 'Group',
    'folder': 'Group',
}

# Xshell Sessions 目录候选路径
SESSIONS_CANDIDATES = [
    lambda: os.path.join(os.getenv('APPDATA', ''), 'NetSarang', 'Xshell', 'Sessions'),
    lambda: os.path.join(os.path.expanduser('~'), 'Documents', 'NetSarang Computer', '7', 'Xshell', 'Sessions'),
    lambda: os.path.join(os.path.expanduser('~'), 'Documents', 'NetSarang Computer', '8', 'Xshell', 'Sessions'),
    lambda: os.path.join(os.path.expanduser('~'), 'Documents', 'NetSarang Computer', '6', 'Xshell', 'Sessions'),
    lambda: os.path.join(os.path.expanduser('~'), 'Documents', 'NetSarang', 'Xshell', 'Sessions'),
]

AUTH_SECTION = '[CONNECTION:AUTHENTICATION]'


# ============================================================
# 工具函数
# ============================================================

def detect_encoding(filepath):
    """自动检测文件编码，依次尝试 utf-8、gbk、gb2312、utf-16"""
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'utf-16']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 'utf-8'  # fallback


def detect_sessions_dir():
    """自动检测 Xshell Sessions 目录"""
    for candidate in SESSIONS_CANDIDATES:
        try:
            path = candidate()
            if os.path.isdir(path):
                return path
        except Exception:
            continue
    return None


def normalize_column_name(name):
    """将列名映射到标准名称（大小写不敏感）"""
    return COLUMN_MAP.get(name.strip().lower(), name.strip())


def detect_delimiter(filepath, encoding):
    """自动检测 CSV 分隔符（逗号/制表符/分号/竖线）"""
    try:
        with open(filepath, 'r', encoding=encoding, newline='') as f:
            sample = f.read(8192)
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
        return dialect.delimiter
    except csv.Error:
        return ','


def read_csv_file(filepath):
    """读取 CSV 文件，自动检测编码、分隔符、列名映射"""
    encoding = detect_encoding(filepath)
    print(f'读取 CSV: {filepath} (编码: {encoding})')

    delimiter = detect_delimiter(filepath, encoding)
    if delimiter != ',':
        print(f'自动检测分隔符: {delimiter!r}')

    rows = []
    with open(filepath, 'r', encoding=encoding, newline='') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError('CSV 文件为空或格式错误')

        # 映射列名
        mapped_fieldnames = [normalize_column_name(fn) for fn in reader.fieldnames]
        print(f'识别列: {mapped_fieldnames}')

        for row in reader:
            # 用映射后的列名重建每一行
            mapped_row = {}
            for orig_key, value in row.items():
                mapped_key = normalize_column_name(orig_key)
                mapped_row[mapped_key] = value.strip() if value else ''
            rows.append(mapped_row)

    return rows


def validate_csv_rows(rows):
    """校验 CSV 数据"""
    errors = []
    for i, row in enumerate(rows, start=2):  # 从第2行开始（第1行是表头）
        if not row.get('SessionName'):
            errors.append(f'第{i}行: SessionName 为空')
        if not row.get('Host'):
            errors.append(f'第{i}行: Host 为空')
    return errors


def list_first_level_subdirs(sessions_dir):
    """列出 Sessions 目录下第一层子文件夹及其 session 数量"""
    subdirs = []
    try:
        for entry in sorted(os.listdir(sessions_dir)):
            full = os.path.join(sessions_dir, entry)
            if os.path.isdir(full):
                count = len(glob.glob(os.path.join(full, '**', '*.xsh'), recursive=True))
                subdirs.append((entry, full, count))
    except OSError:
        pass
    return subdirs


def parse_target_selection(selection_str, max_index):
    """解析目标序号字符串，返回索引列表。

    支持格式: '1' / '1-3' / '1,3,5' / '1-3,5' / 'a' / 'all'
    """
    selection_str = selection_str.strip().lower()
    if selection_str in ('a', 'all'):
        return list(range(max_index))

    indices = set()
    parts = selection_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start, end = int(start.strip()), int(end.strip())
                for i in range(start, end + 1):
                    if 1 <= i <= max_index:
                        indices.add(i - 1)
            except ValueError:
                print(f'[!] 忽略无效范围: {part}')
        else:
            try:
                i = int(part)
                if 1 <= i <= max_index:
                    indices.add(i - 1)
            except ValueError:
                print(f'[!]  忽略无效序号: {part}')

    return sorted(indices)


def extract_auth_field(content, field):
    """从 xsh 内容的 [CONNECTION:AUTHENTICATION] section 中提取字段值"""
    in_auth = False
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_auth = (stripped.upper() == AUTH_SECTION.upper())
        elif in_auth and line.strip().startswith(f'{field}='):
            return line.strip()[len(f'{field}='):]
    return None


def replace_auth_field(content, field, new_value):
    """在 xsh 内容的 [CONNECTION:AUTHENTICATION] section 中替换字段值"""
    lines = content.split('\n')
    in_auth = False
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_auth = (stripped.upper() == AUTH_SECTION.upper())
        elif in_auth and line.strip().startswith(f'{field}='):
            # 保留原有缩进
            prefix = line[:len(line) - len(line.lstrip())]
            lines[i] = f'{prefix}{field}={new_value}'
            replaced = True

    if not replaced:
        # 字段不存在，在 section 末尾追加
        return _append_field_to_section('\n'.join(lines), field, new_value)

    return '\n'.join(lines)


def _append_field_to_section(content, field, new_value):
    """在 [CONNECTION:AUTHENTICATION] section 末尾追加字段"""
    lines = content.split('\n')
    in_auth = False
    insert_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_auth:
                # 已经离开了 auth section，在上一个 section 末尾插入
                insert_idx = i
                break
            in_auth = (stripped.upper() == AUTH_SECTION.upper())
        elif in_auth:
            insert_idx = i + 1

    if insert_idx is not None and in_auth:
        lines.insert(insert_idx, f'{field}={new_value}')
        return '\n'.join(lines)

    return content  # 找不到 section，不修改


def read_file_with_encoding(filepath):
    """读取文件，自动检测编码"""
    encoding = detect_encoding(filepath)
    with open(filepath, 'r', encoding=encoding) as f:
        return f.read()


def write_file_with_encoding(filepath, content):
    """写入文件，使用 utf-8 编码（保持与 Xshell 兼容）"""
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)


# ============================================================
# 功能一：批量生成
# ============================================================

def cmd_generate(args):
    """generate 子命令"""
    # 1. 读取模板
    template_encoding = detect_encoding(args.template)
    print(f'读取模板: {args.template} (编码: {template_encoding})')
    with open(args.template, 'r', encoding=template_encoding) as f:
        template = f.read()

    if PLACEHOLDER_HOST not in template:
        print(f'\n[!]  模板中未找到占位符 {PLACEHOLDER_HOST}')
        print('   请用文本编辑器打开模板文件，将设备 IP 替换为 {{HOST}}：')
        print('')
        print('   直接登录模式：')
        print('     [CONNECTION]')
        print('     Host={{HOST}}')
        print('')
        print('   堡垒机登录模式：')
        print('     在 Expect/Send 规则中，将发送设备 IP 的地方替换为 {{HOST}}')
        return

    # 2. 读取 CSV
    rows = read_csv_file(args.input)
    if not rows:
        print('CSV 文件中没有数据行')
        return

    # 3. 校验
    errors = validate_csv_rows(rows)
    if errors:
        print('\n[X] CSV 数据校验失败：')
        for e in errors:
            print(f'   {e}')
        return

    # 4. 确定输出目录
    output_dir = args.output or detect_sessions_dir()
    if output_dir is None:
        print('[X] 未找到 Xshell Sessions 目录，请用 -o 手动指定')
        return
    print(f'输出目录: {output_dir}')

    # 5. 逐行生成
    created, skipped = 0, 0
    for row in rows:
        name = row['SessionName']
        host = row['Host']
        group = row.get('Group', '')

        content = template.replace(PLACEHOLDER_HOST, host)

        # 确定输出路径
        if args.flat or not group:
            out_dir = output_dir
        else:
            out_dir = os.path.join(output_dir, *group.split('/'))

        # 确保文件名合法
        safe_name = _sanitize_filename(name)
        out_path = os.path.join(out_dir, f'{safe_name}.xsh')

        if args.dry_run:
            print(f'[预览] {out_path}  (Host={host})')
            created += 1
            continue

        if os.path.exists(out_path) and not args.force:
            print(f'[跳过] {out_path} (已存在)')
            skipped += 1
            continue

        os.makedirs(out_dir, exist_ok=True)
        write_file_with_encoding(out_path, content)
        print(f'[生成] {out_path}')
        created += 1

    # 6. 汇总
    print(f'\n完成: 生成 {created} 个' + (f', 跳过 {skipped} 个' if skipped else ''))


def _sanitize_filename(name):
    """移除文件名中的非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


# ============================================================
# 功能二：批量改密
# ============================================================

def cmd_update_pwd(args):
    """update-pwd 子命令"""
    # 1. 确定 Sessions 目录
    sessions_dir = args.output or detect_sessions_dir()
    if sessions_dir is None:
        print('[X] 未找到 Xshell Sessions 目录，请用 -o 手动指定')
        return
    print(f'Sessions 目录: {sessions_dir}')

    # 2. 定位源 session
    source_path = os.path.join(sessions_dir, args.source)
    if not os.path.isfile(source_path):
        print(f'[X] 源 session 不存在: {source_path}')
        return
    print(f'源 session: {source_path}')

    # 3. 提取加密密码
    source_content = read_file_with_encoding(source_path)

    field = args.field
    extract_password = field in ('password', 'all')
    extract_passphrase = field in ('passphrase', 'all')

    pwd_value = extract_auth_field(source_content, 'Password') if extract_password else None
    phrase_value = extract_auth_field(source_content, 'Passphrase') if extract_passphrase else None

    if extract_password and pwd_value is None:
        print('[!]  源 session 中未找到 Password 字段')
    if extract_passphrase and phrase_value is None:
        print('[!]  源 session 中未找到 Passphrase 字段')

    if pwd_value is None and phrase_value is None:
        print('[X] 未提取到任何加密值，请确认源 session 已保存密码/密钥密码')
        return

    if pwd_value:
        print(f'已提取 Password: {_mask_value(pwd_value)}')
    if phrase_value:
        print(f'已提取 Passphrase: {_mask_value(phrase_value)}')

    # 4. 目标文件夹选择
    subdirs = list_first_level_subdirs(sessions_dir)
    if not subdirs:
        print('[X] Sessions 目录下没有子文件夹')
        return

    targets = _resolve_targets(subdirs, args.target)
    if not targets:
        print('未选择任何目标文件夹')
        return

    # 5. 收集并处理所有 .xsh 文件
    all_xsh_files = []
    for _, dir_path, _ in targets:
        xsh_files = glob.glob(os.path.join(dir_path, '**', '*.xsh'), recursive=True)
        all_xsh_files.extend(xsh_files)

    if not all_xsh_files:
        print('[X] 目标文件夹中没有 .xsh 文件')
        return

    print(f'\n目标: {len(targets)} 个文件夹, 共 {len(all_xsh_files)} 个 .xsh 文件')
    print('-' * 50)

    updated, unchanged = 0, 0
    for xsh_path in all_xsh_files:
        rel = os.path.relpath(xsh_path, sessions_dir)
        try:
            content = read_file_with_encoding(xsh_path)
            new_content = content
            changes = []

            if pwd_value:
                old_pwd = extract_auth_field(content, 'Password')
                if old_pwd and old_pwd != pwd_value:
                    new_content = replace_auth_field(new_content, 'Password', pwd_value)
                    changes.append('Password')
                elif old_pwd and old_pwd == pwd_value:
                    pass  # 已经是目标值

            if phrase_value:
                old_phrase = extract_auth_field(content, 'Passphrase')
                if old_phrase and old_phrase != phrase_value:
                    new_content = replace_auth_field(new_content, 'Passphrase', phrase_value)
                    changes.append('Passphrase')
                elif old_phrase and old_phrase == phrase_value:
                    pass

            if changes:
                if args.dry_run:
                    print(f'[预览] {rel}  更新: {", ".join(changes)}')
                else:
                    write_file_with_encoding(xsh_path, new_content)
                    print(f'[更新] {rel}  ({", ".join(changes)})')
                updated += 1
            else:
                unchanged += 1

        except Exception as e:
            print(f'[错误] {rel}: {e}')

    # 6. 汇总
    print('-' * 50)
    action = '预览' if args.dry_run else '更新'
    print(f'完成: {action} {updated} 个, 无需修改 {unchanged} 个')
    if args.dry_run:
        print('(dry-run 模式，未实际修改文件)')


def _mask_value(value, show=6):
    """遮盖敏感值，只显示前几个字符"""
    if len(value) <= show:
        return value[:2] + '****'
    return value[:show] + '****'


def _resolve_targets(subdirs, target_arg):
    """解析目标文件夹选择。

    如果 target_arg 已提供，直接解析；
    否则进入交互模式让用户选择。
    """
    if target_arg is not None:
        indices = parse_target_selection(target_arg, len(subdirs))
        return [subdirs[i] for i in indices]

    # 交互模式
    print(f'\n第一层文件夹：')
    for idx, (name, _, count) in enumerate(subdirs, start=1):
        print(f'  [{idx}] {name:<20} ({count} 个 session)')
    print(f'  [a] 全部')

    while True:
        try:
            choice = input('\n请选择目标文件夹（如: 1 / 1-3 / 1,3,5 / a）: ').strip()
            if not choice:
                continue
            indices = parse_target_selection(choice, len(subdirs))
            if indices:
                return [subdirs[i] for i in indices]
            print(f'  无效选择，请重试')
        except (KeyboardInterrupt, EOFError):
            print()
            return []


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Xshell Session 文件自动生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 批量生成 session 文件
  python xshell_gen.py generate 模板.xsh 服务器.csv
  python xshell_gen.py generate 模板.xsh 服务器.csv --dry-run
  python xshell_gen.py generate 模板.xsh 服务器.csv -o "D:\\Sessions"

  # 批量修改密码
  python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh
  python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh -t all
  python xshell_gen.py update-pwd 北京四/az1/fa/sw01.xsh --field password -t 1,3-5
        ''',
    )
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # ---- generate ----
    gen_parser = subparsers.add_parser('generate', help='批量生成 session 文件')
    gen_parser.add_argument('template', help='模板 .xsh 文件路径')
    gen_parser.add_argument('input', help='CSV 输入文件路径')
    gen_parser.add_argument('-o', '--output', help='输出目录（默认自动检测 Xshell Sessions 目录）')
    gen_parser.add_argument('--dry-run', action='store_true', help='预览模式，不写入文件')
    gen_parser.add_argument('--flat', action='store_true', help='平铺输出，不创建分组文件夹')
    gen_parser.add_argument('--force', action='store_true', help='覆盖已存在的文件')

    # ---- update-pwd ----
    upd_parser = subparsers.add_parser('update-pwd', help='批量修改 session 密码')
    upd_parser.add_argument('source', help='源 session 相对路径（相对于 Sessions 目录）')
    upd_parser.add_argument('-o', '--output', help='Sessions 目录路径（默认自动检测）')
    upd_parser.add_argument('-t', '--target', help='目标文件夹序号（如: 1, 1-3, 1,3-5, all）')
    upd_parser.add_argument('--field', choices=['passphrase', 'password', 'all'],
                            default='passphrase',
                            help='要更新的字段（默认: passphrase）')
    upd_parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际修改文件')

    args = parser.parse_args()

    if args.command == 'generate':
        cmd_generate(args)
    elif args.command == 'update-pwd':
        cmd_update_pwd(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
