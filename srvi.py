#!/usr/bin/env python3
import time
import socket
import os
import shutil
import glob
from datetime import datetime
from typing import List, Dict, Tuple
import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich import box

# ========== НАСТРОЙКИ ==========
DEFAULT_DOMAINS = [
    "google.com",
    "github.com",
    "stackoverflow.com",
    "nonexistent.example.com",
    "httpbin.org",
    "yandex.ru",
]
CHECK_INTERVAL = 10
HTTP_TIMEOUT = 5
USER_AGENT = "DNS-HTTP-Checker/1.0"
MAX_LOG_FILES = 50
MAX_LOG_DAYS = 30

# ========== ЗАГРУЗКА ДОМЕНОВ ИЗ ФАЙЛА ==========
def load_domains_from_file(filename: str = "domains.txt") -> List[str]:
    """Загружает список доменов из файла (по одному на строку).
    Если файл не найден или пуст, возвращает DEFAULT_DOMAINS."""
    if not os.path.exists(filename):
        return DEFAULT_DOMAINS.copy()
    domains = []
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                domains.append(line)
    if not domains:
        return DEFAULT_DOMAINS.copy()
    return domains

# ========== ФУНКЦИИ ПРОВЕРОК ==========
def check_dns(domain: str) -> Tuple[bool, str]:
    try:
        ips = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
        ip_list = sorted(set(ip[4][0] for ip in ips))
        if ip_list:
            return True, ", ".join(ip_list[:3])
        return False, "Нет A-записей"
    except Exception as e:
        return False, f"Ошибка: {str(e)}"

def check_http(domain: str) -> Tuple[bool, str, int | None]:
    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}"
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            if 200 <= resp.status_code < 400:
                return True, f"{scheme.upper()} {resp.status_code}", resp.status_code
            return False, f"{scheme.upper()} {resp.status_code}", resp.status_code
        except requests.exceptions.Timeout:
            return False, f"{scheme.upper()} таймаут", None
        except requests.exceptions.ConnectionError:
            continue
        except Exception as e:
            return False, f"{scheme.upper()} ошибка: {str(e)[:30]}", None
    return False, "HTTP/HTTPS недоступен", None

def check_overall(dns_ok: bool, http_ok: bool) -> Tuple[bool, str]:
    if dns_ok and http_ok:
        return True, "ДОСТУПЕН"
    if not dns_ok:
        return False, "DNS ошибка"
    if not http_ok:
        return False, "HTTP ошибка"
    return False, "НЕДОСТУПЕН"

def run_checks(domains: List[str]) -> List[Dict]:
    results = []
    for domain in domains:
        dns_ok, dns_msg = check_dns(domain)
        http_ok, http_msg, status = check_http(domain)
        overall_ok, overall_msg = check_overall(dns_ok, http_ok)
        results.append({
            "domain": domain,
            "dns_ok": dns_ok,
            "dns_msg": dns_msg,
            "http_ok": http_ok,
            "http_msg": http_msg,
            "status_code": status,
            "overall_ok": overall_ok,
            "overall_msg": overall_msg,
        })
    return results

def build_status_table(results: List[Dict]) -> Table:
    table = Table(title="Мониторинг доступности доменов", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Домен", style="dim", width=25)
    table.add_column("DNS (IP)", width=35)
    table.add_column("HTTP", justify="center", width=12)
    table.add_column("Статус", justify="center", width=15)

    for res in results:
        dns_text = Text(res["dns_msg"], style="green" if res["dns_ok"] else "red")
        if res["http_ok"]:
            http_style = "bold green" if res["status_code"] and 200 <= res["status_code"] < 300 else "bold yellow"
            http_display = f"🟢 {res['http_msg']}"
        else:
            http_style = "red"
            http_display = f"🔴 {res['http_msg']}"
        http_text = Text(http_display, style=http_style)
        overall_text = Text(res["overall_msg"], style="bold green" if res["overall_ok"] else "bold red")
        table.add_row(res["domain"], dns_text, http_text, overall_text)
    return table

def log_results_to_file(filepath: str, iteration: int, results: List[Dict]):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"Итерация #{iteration} | Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n")
        for res in results:
            status = "✅ ДОСТУПЕН" if res["overall_ok"] else "❌ НЕДОСТУПЕН"
            f.write(f"{res['domain']:30} | DNS: {res['dns_msg']:35} | HTTP: {res['http_msg']:20} | {status}\n")
        f.write(f"{'=' * 60}\n")

def archive_log(temp_filepath: str) -> str | None:
    history_dir = "history"
    os.makedirs(history_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_filename = f"monitoring_{timestamp}.txt"
    new_path = os.path.join(history_dir, new_filename)
    shutil.move(temp_filepath, new_path)
    return new_path

def rotate_logs(history_dir="history", max_files=MAX_LOG_FILES, max_days=MAX_LOG_DAYS):
    if not os.path.exists(history_dir):
        return
    pattern = os.path.join(history_dir, "monitoring_*.txt")
    files = glob.glob(pattern)
    if not files:
        return
    files.sort(key=os.path.getmtime)
    now = time.time()
    cutoff = now - (max_days * 86400)
    deleted = 0
    for f in files[:]:
        if os.path.getmtime(f) < cutoff:
            try:
                os.remove(f)
                files.remove(f)
                deleted += 1
            except Exception:
                pass
    if deleted:
        console = Console()
        console.print(f"[dim]🧹 Удалено старых логов (>{max_days} дней): {deleted}[/dim]")
    if len(files) > max_files:
        to_remove = len(files) - max_files
        for f in files[:to_remove]:
            try:
                os.remove(f)
            except Exception:
                pass
        console = Console()
        console.print(f"[dim]🧹 Удалено лишних логов (осталось {max_files}): {to_remove}[/dim]")

def ask_for_logging() -> bool:
    console = Console()
    console.print("\n[bold cyan]🔍 Выберите режим работы:[/bold cyan]")
    answer = input("Сохранять результаты в файл? (y/N): ").strip().lower()
    if answer in ('y', 'yes', 'д', 'да', '1', 'true'):
        console.print("[green]✅ Логирование включено. Результаты будут сохранены.[/green]\n")
        return True
    else:
        console.print("[yellow]⚠️ Логирование отключено. Результаты не будут сохранены в файл.[/yellow]\n")
        return False

def main():
    console = Console()
    console.print(Panel.fit("🚀 Запуск мониторинга доменов", style="bold magenta"))

    # Загружаем домены из domains.txt или используем встроенные
    domains = load_domains_from_file("domains.txt")
    console.print(f"[dim]Загружено доменов: {len(domains)}[/dim]")

    logging_enabled = ask_for_logging()

    temp_log = None
    if logging_enabled:
        temp_log = "monitoring_temp.txt"
        if os.path.exists(temp_log):
            os.remove(temp_log)
        rotate_logs()

    iteration = 0
    try:
        while True:
            iteration += 1
            start_time = time.time()

            results = run_checks(domains)
            table = build_status_table(results)

            if logging_enabled and temp_log:
                log_results_to_file(temp_log, iteration, results)

            footer = Text()
            footer.append(f"📅 Время: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  ", style="dim")
            footer.append(f"🔄 Итерация: {iteration}  |  ", style="dim")
            footer.append(f"⏱️ Интервал: {CHECK_INTERVAL} с", style="dim")
            if logging_enabled and temp_log:
                footer.append(f"💾 Лог: {temp_log}", style="dim")

            console.clear()
            console.print(table)
            console.print(footer)

            elapsed = time.time() - start_time
            sleep_time = max(0, CHECK_INTERVAL - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]🛑 Мониторинг остановлен пользователем.[/bold yellow]")
        if logging_enabled and temp_log and os.path.exists(temp_log):
            archived = archive_log(temp_log)
            if archived:
                console.print(f"[green]✅ Лог сохранён: {archived}[/green]")
                rotate_logs()
            else:
                console.print("[red]❌ Не удалось переместить лог[/red]")
        elif logging_enabled:
            console.print("[dim]Лог-файл не был создан.[/dim]")
        console.print("[bold cyan]👋 До свидания![/bold cyan]")

if __name__ == "__main__":
    main()