#!/usr/bin/env python3
"""Проверяет журнал изменений и привязку доказательств к текущему состоянию дерева.

Заменяет `.artifacts/<stage>/tools/validate_changes.py`, который лежал под
`.gitignore` и потому ничего не мог гарантировать: его правила ездили вместе с
доказательствами, которые он же проверял.

Сверх правил ADM-1..ADM-9 мастер-промпта добавлены пять, закрывающие ложный
пропуск, найденный ревью 2026-08-01: журнал проходил проверку, объявляя тесты,
которых в дереве нет.

    ADM-10  объявленный узел теста обязан существовать
    ADM-11  для layer domain/data/integration обязателен журнал мутаций
    ADM-12  HEAD в наборе доказательств совпадает с текущим HEAD
    ADM-13  хеш отслеживаемого диффа совпадает с текущим
    ADM-14  число записей совпадает с заявленным в наборе
    ADM-15  новые (неотслеживаемые) файлы не менялись после сборки набора
    ADM-16  каждая мутация называет существующий узел теста, который её убил
    ADM-17  журнал изменений не правился после сборки набора

Использование:

    python3 scripts/validate_evidence_bundle.py --emit    # собрать набор
    python3 scripts/validate_evidence_bundle.py           # проверить
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from datetime import UTC, datetime

BANNED = ("в целом", "улучшено", "оптимизировано", "отрефакторено")
NUMBER = re.compile(r"\d")
MUTATION_LAYERS = {"domain", "data", "integration"}


def _repo_root(start: pathlib.Path) -> pathlib.Path:
    root = start.resolve()
    for _ in range(6):
        if (root / "backend").is_dir() and (root / "frontend").is_dir():
            return root
        root = root.parent
    raise SystemExit("не найден корень репозитория (нет backend/ и frontend/)")


def _git(root: pathlib.Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def current_head(root: pathlib.Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def tracked_diff_sha256(root: pathlib.Path) -> str:
    """Хеш диффа по отслеживаемым файлам.

    Неотслеживаемые файлы сознательно не входят: они не являются частью
    заявленного изменения и меняются у каждого исполнителя по-своему.
    """

    return hashlib.sha256(_git(root, "diff", "HEAD").encode("utf-8")).hexdigest()


#: Каталоги, чьи неотслеживаемые файлы считаются частью доказательства.
#: Ограничение намеренное: сюда попадают исходники, тесты и миграции, но не
#: `.artifacts` и не документы — их содержимое меняется отдельно от кода.
UNTRACKED_ROOTS = ("backend/", "frontend/", "scripts/")


def untracked_manifest_sha256(root: pathlib.Path) -> str:
    """Хеш новых файлов, которых ещё нет в git.

    ADM-13 покрывает только изменения отслеживаемых файлов, а новый тест — это
    обычно новый файл. Без этой проверки набор доказательств оставался бы
    «свежим» после того, как половину доказательств удалили: за прогон
    2026-08-01 в дереве появилось 12 таких файлов, включая миграцию.
    """

    listing = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    lines: list[str] = []
    for rel in sorted(listing):
        if not rel.startswith(UNTRACKED_ROOTS):
            continue
        target = root / rel
        if not target.is_file():
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{digest}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _suite_failures(text: str) -> int:
    match = re.search(r"(\d+)\s+failed", text)
    return int(match.group(1)) if match else 0


def changes_sha256(changes: pathlib.Path) -> str:
    """Хеш самого журнала.

    Без него набор доказательств удостоверяет дерево, но не собственные
    утверждения: строки журнала можно переписать после сборки, и проверка этого
    не заметит.
    """

    return hashlib.sha256(changes.read_bytes()).hexdigest()


def _resolve_test_node(root: pathlib.Path, declared: str) -> tuple[bool, str]:
    """Разрешить узел теста, записанный от корня или от ``backend/``.

    В журнале соседствуют оба написания: пути в ``files`` даны от корня, а
    узлы тестов исторически записаны так, как их запускает pytest — из
    ``backend/``. Проверка обязана принимать оба, иначе честная запись
    выглядит как подделка.
    """

    for candidate in (declared, f"backend/{declared}"):
        ok, reason = _node_exists(root, candidate)
        if ok:
            return True, ""
    return False, reason


def _node_exists(root: pathlib.Path, declared: str) -> tuple[bool, str]:
    """Существует ли объявленный узел теста.

    Это правило и есть ADM-10. Ревью 2026-08-01 показало, что без него журнал
    сообщает «ОШИБОК: 0», объявляя восемь тестов, которых в дереве нет: запись
    считалась доказанной, а доказательства не было.
    """

    if not declared.strip():
        return False, "путь пуст"
    path_part, _, node = declared.partition("::")
    target = root / path_part
    if not target.exists():
        return False, f"файла нет: {path_part}"
    if not node:
        return True, ""
    # Параметризованный узел вида name[case] проверяется по имени функции.
    base = node.split("[", 1)[0].strip()
    if not base:
        return True, ""
    try:
        body = target.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return False, f"файл нечитаем: {exc}"
    if base not in body:
        return False, f"узла нет в файле: {base}"
    return True, ""


def check_record(rec: dict, root: pathlib.Path) -> list[str]:
    errs: list[str] = []

    if not rec.get("files"):
        errs.append("ADM-1: files пуст")
    for path in rec.get("files", []):
        if not (root / path).exists():
            errs.append(f"ADM-1: файла нет на диске: {path}")

    if len(str(rec.get("why", ""))) < 20:
        errs.append("ADM-2: why слишком короткое, нужна причина в единицах заказчика")

    before, after = rec.get("before") or {}, rec.get("after") or {}
    for name, block in (("before", before), ("after", after)):
        if block.get("value") is None:
            errs.append(f"ADM-3: {name}.value не заполнен")
        if not str(block.get("method", "")).strip():
            errs.append(f"ADM-3: {name}.method не заполнен")
    if before.get("method") and before.get("method") != after.get("method"):
        errs.append("ADM-3: методика before и after различается — сравнение невалидно")

    test = rec.get("failing_test") or {}
    if test.get("failed_before") is not True:
        errs.append("ADM-4: failing_test.failed_before должно быть true")
    if len(str(test.get("output_excerpt", ""))) < 10:
        errs.append("ADM-4: нет вывода падения на прежнем коде")

    sb, sa = rec.get("suite_before") or {}, rec.get("suite_after") or {}
    for side, block in (("suite_before", sb), ("suite_after", sa)):
        for key in ("backend", "frontend"):
            if not str(block.get(key, "")).strip():
                errs.append(f"ADM-5: {side}.{key} не заполнен")
    for key in ("backend", "frontend"):
        if sb.get(key) and sa.get(key):
            if _suite_failures(str(sa[key])) > _suite_failures(str(sb[key])):
                errs.append(f"ADM-5: падений в {key} стало больше, чем было")

    if rec.get("migration") and "downgrade" not in str(rec.get("rollback", "")).lower():
        errs.append("ADM-6: миграция без описанного downgrade в rollback")

    if not str(rec.get("rollback", "")).strip():
        errs.append("ADM-7: rollback пуст")

    if rec.get("status") == "PARTIAL" and "непокрыт" not in json.dumps(
        rec, ensure_ascii=False
    ).lower():
        errs.append("ADM-8: status=PARTIAL без перечня непокрытого")

    blob = " ".join(str(rec.get(f, "")) for f in ("title", "why", "risk")).lower()
    for word in BANNED:
        index = blob.find(word)
        if index >= 0 and not NUMBER.search(blob[index : index + 80]):
            errs.append(f"ADM-9: «{word}» без числа рядом")

    ok, reason = _node_exists(root, str(test.get("path", "")))
    if not ok:
        errs.append(f"ADM-10: объявленный узел теста не разрешается — {reason}")

    if rec.get("layer") in MUTATION_LAYERS and rec.get("status") != "BLOCKED":
        mutations = rec.get("mutations")
        if not isinstance(mutations, list) or not mutations:
            errs.append(
                f"ADM-11: layer={rec.get('layer')} требует журнал мутаций "
                "(§3.2), поле mutations пусто"
            )
        else:
            for index, entry in enumerate(mutations):
                if not isinstance(entry, dict):
                    errs.append(f"ADM-11: mutations[{index}] не объект")
                    continue
                if not str(entry.get("mutation", "")).strip():
                    errs.append(f"ADM-11: mutations[{index}].mutation пуст")
                killed_by = str(entry.get("killed_by", "")).strip()
                if not killed_by:
                    errs.append(
                        f"ADM-11: mutations[{index}].killed_by пуст — "
                        "выживший мутант означает недостаточный тест"
                    )
                    continue
                # ADM-16: связь «мутант убит» обязана быть проверяемой машиной,
                # а не прозой. Узел, названный в killed_by, должен существовать.
                if "::" not in killed_by:
                    errs.append(
                        f"ADM-16: mutations[{index}].killed_by не называет узел "
                        f"теста (нет '::'): {killed_by[:60]!r}"
                    )
                    continue
                first = killed_by.split(",")[0].strip()
                ok_node, why = _resolve_test_node(root, first)
                if not ok_node:
                    errs.append(
                        f"ADM-16: mutations[{index}].killed_by ссылается на "
                        f"несуществующий тест — {why}"
                    )

    return errs


def load_records(path: pathlib.Path) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    errs: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            errs.append(f"строка {lineno}: невалидный JSON: {exc}")
    return records, errs


def emit_bundle(root: pathlib.Path, changes: pathlib.Path, bundle: pathlib.Path) -> int:
    records, errs = load_records(changes)
    if errs:
        for err in errs:
            print(err)
        return 1
    payload = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": current_head(root),
        "tracked_diff_sha256": tracked_diff_sha256(root),
        "untracked_manifest_sha256": untracked_manifest_sha256(root),
        "changes_sha256": changes_sha256(changes),
        "change_count": len(records),
        "changes_path": str(changes.relative_to(root)),
        "note": (
            "Локальные тесты не являются доказательством готовности к "
            "продакшену. Набор фиксирует состояние дерева, а не пригодность."
        ),
    }
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"набор доказательств записан: {bundle}")
    print(f"  HEAD:                {payload['git_head']}")
    print(f"  хеш дифф(tracked):   {payload['tracked_diff_sha256']}")
    print(f"  хеш новых файлов:    {payload['untracked_manifest_sha256']}")
    print(f"  хеш журнала:         {payload['changes_sha256']}")
    print(f"  записей:             {payload['change_count']}")
    return 0


def validate(root: pathlib.Path, changes: pathlib.Path, bundle: pathlib.Path) -> int:
    records, failures_text = load_records(changes)
    failures = 0
    for err in failures_text:
        print(err)
        failures += 1

    for index, rec in enumerate(records, 1):
        for err in check_record(rec, root):
            print(f"{rec.get('id', f'запись {index}')}: {err}")
            failures += 1

    ids = [rec.get("id") for rec in records]
    if len(ids) != len(set(ids)):
        print("дублирующиеся id в журнале")
        failures += 1

    if not bundle.exists():
        print(f"ADM-12..17: набора доказательств нет: {bundle} (собрать: --emit)")
        failures += 1
    else:
        data = json.loads(bundle.read_text(encoding="utf-8"))
        head = current_head(root)
        if data.get("git_head") != head:
            print(
                f"ADM-12: набор собран на HEAD {data.get('git_head')}, "
                f"а дерево на {head} — доказательства устарели"
            )
            failures += 1
        digest = tracked_diff_sha256(root)
        if data.get("tracked_diff_sha256") != digest:
            print(
                "ADM-13: отслеживаемый дифф изменился после сборки набора "
                f"({data.get('tracked_diff_sha256')} != {digest})"
            )
            failures += 1
        journal = changes_sha256(changes)
        if data.get("changes_sha256") != journal:
            print(
                "ADM-17: журнал изменений правился после сборки набора "
                f"({data.get('changes_sha256')} != {journal})"
            )
            failures += 1
        untracked = untracked_manifest_sha256(root)
        if data.get("untracked_manifest_sha256") != untracked:
            print(
                "ADM-15: набор новых (неотслеживаемых) файлов изменился после "
                f"сборки набора ({data.get('untracked_manifest_sha256')} != "
                f"{untracked})"
            )
            failures += 1
        if data.get("change_count") != len(records):
            print(
                f"ADM-14: в наборе заявлено {data.get('change_count')} записей, "
                f"в журнале {len(records)}"
            )
            failures += 1

    print(f"записей: {len(records)}; корень: {root}")
    print("ОШИБОК: 0" if failures == 0 else f"ОШИБОК: {failures}")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changes",
        default=".artifacts/improve-20260730/CHANGES.jsonl",
        help="журнал изменений",
    )
    parser.add_argument(
        "--bundle",
        default=".artifacts/improve-20260730/EVIDENCE_BUNDLE.json",
        help="набор доказательств",
    )
    parser.add_argument(
        "--emit",
        action="store_true",
        help="собрать набор по текущему состоянию дерева вместо проверки",
    )
    args = parser.parse_args(argv[1:])

    root = _repo_root(pathlib.Path(__file__).parent)
    changes = (root / args.changes).resolve()
    bundle = (root / args.bundle).resolve()
    if not changes.exists():
        print(f"журнала нет: {changes}", file=sys.stderr)
        return 2

    if args.emit:
        return emit_bundle(root, changes, bundle)
    return validate(root, changes, bundle)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
