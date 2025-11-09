import re
import requests
import os
from datetime import datetime

# ======================
# 🔑 НАСТРОЙКИ
# ======================
YANDEX_DISK_TOKEN = "y0__xCdoeLYBRjblgMgtZWKihWiDf1au7jJtVsy4bQO-a5A7-NMJA"
YANDEX_DISK_REMOTE_PATH = "/parcer_data"

# Для тестов на ПК: задайте здесь свою тему ntfy (необязательно, если используете env)
NTFY_TOPIC_FALLBACK = None  # например: "mypricewatch_abc123"
# ======================

HEADERS = {"Authorization": f"OAuth {YANDEX_DISK_TOKEN}"}
BASE_URL = "https://cloud-api.yandex.net/v1/disk/resources"


def parse_timestamp_from_filename(name: str):
    stem = name.rsplit('.', 1)[0]
    try:
        return datetime.strptime(stem, "%d.%m.%Y_%H.%M.%S")
    except ValueError:
        return None


def parse_products(text: str):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    products = {}
    i = 0
    while i < len(lines):
        if (i + 2 < len(lines)
            and lines[i].startswith("Артикул:")
            and lines[i+1].startswith("Название:")
            and lines[i+2].startswith("Цена:")):
            try:
                art_match = re.search(r"Артикул:\s*(\d+)", lines[i])
                name_match = re.search(r"Название:\s*(.+)", lines[i+1])
                price_match = re.search(r"Цена:\s*(.+)", lines[i+2])
                if art_match and name_match and price_match:
                    article = art_match.group(1)
                    name = name_match.group(1).strip()
                    price_clean = re.sub(r"[^\d]", "", price_match.group(1))
                    price = int(price_clean) if price_clean else 0
                    products[article] = {"name": name, "price": price}
                i += 3
            except Exception:
                i += 1
        else:
            i += 1
    return products


def get_download_url(file_path: str) -> str:
    url = "https://cloud-api.yandex.net/v1/disk/resources/download"
    params = {"path": file_path}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        return data["href"]
    else:
        raise RuntimeError(f"Не удалось получить ссылку для '{file_path}': {resp.status_code} {resp.text}")


def download_file_content(download_url: str) -> str:
    response = requests.get(download_url, timeout=30)
    response.raise_for_status()
    raw = response.content
    for encoding in ('utf-8', 'cp1251'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Не удалось декодировать файл (попробованы utf-8 и cp1251)")


def format_price(n: int) -> str:
    return f"{n:,} ₽".replace(",", " ")


def main():
    print("🔍 Получение списка файлов из папки '/parcer_data' на Яндекс.Диске...")
    
    params = {
        "path": YANDEX_DISK_REMOTE_PATH,
        "limit": 100,
        "fields": "items.name,items.path"
    }
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 401:
            print("❌ Ошибка 401: Неверный/просроченный токен.")
            print("→ Получите новый: https://yandex.ru/dev/disk/poligon/")
            return
        elif resp.status_code == 404:
            print(f"❌ Папка '{YANDEX_DISK_REMOTE_PATH}' не найдена.")
            print("→ Проверьте имя (регистр!) и наличие папки в корне Диска.")
            return
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Ошибка сети: {e}")
        return

    data = resp.json()
    items = data.get("_embedded", {}).get("items", [])
    
    txt_files = []
    for item in items:
        name = item.get("name", "")
        path = item.get("path", "")
        if name.lower().endswith(".txt") and path:
            txt_files.append((name, path))
    
    if not txt_files:
        print("📂 В папке 'parcer_data' нет .txt файлов.")
        return

    print(f"📁 Найдено {len(txt_files)} .txt файлов. Анализ имён...")
    
    dated_files = []
    for name, path in txt_files:
        dt = parse_timestamp_from_filename(name)
        if dt:
            dated_files.append((dt, name, path))
    
    if len(dated_files) < 2:
        print(f"❌ Найдено только {len(dated_files)} файлов с датой в имени.")
        print("→ Ожидаются имена: 09.11.2025_15.30.00.txt")
        return

    dated_files.sort(key=lambda x: x[0], reverse=True)
    latest_dt, latest_name, latest_path = dated_files[0]
    prev_dt, prev_name, prev_path = dated_files[1]

    print(f"\n✅ Сравниваем:")
    print(f"  🆕 {latest_name}  ({latest_dt.strftime('%d.%m.%Y %H:%M:%S')})")
    print(f"  📅 {prev_name}  ({prev_dt.strftime('%d.%m.%Y %H:%M:%S')})\n")

    try:
        print("📥 Получение ссылок на скачивание...")
        latest_url = get_download_url(latest_path)
        prev_url = get_download_url(prev_path)

        print("📥 Скачивание содержимого...")
        text_new = download_file_content(latest_url)
        text_old = download_file_content(prev_url)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return

    products_new = parse_products(text_new)
    products_old = parse_products(text_old)

    print(f"📦 Товаров: {len(products_new)} (новый), {len(products_old)} (старый)\n")

    all_articles = set(products_new.keys()) | set(products_old.keys())
    changes = []

    for art in sorted(all_articles):
        new = products_new.get(art)
        old = products_old.get(art)

        if new and not old:
            changes.append(
                f"🆕 [{art}] {new['name']}\n"
                f"   → Добавлен! Цена: {format_price(new['price'])}"
            )
        elif old and not new:
            changes.append(
                f"❌ [{art}] {old['name']}\n"
                f"   → Удалён. Была цена: {format_price(old['price'])}"
            )
        elif new and old and new["price"] != old["price"]:
            diff = new["price"] - old["price"]
            arrow = "📈" if diff > 0 else "📉"
            change_desc = f"Подорожал на {format_price(diff)}" if diff > 0 else f"Подешевел на {format_price(-diff)}"
            changes.append(
                f"{arrow} [{art}] {new['name']}\n"
                f"   {format_price(old['price'])} → {format_price(new['price'])} ({change_desc})"
            )

    # 6. Вывод и отправка уведомления
    if changes:
        print("🔔 Изменения:\n")
        for ch in changes:
            print(ch)
            print()
    else:
        print("✅ Изменений не обнаружено.")

    print(f"ℹ️ Всего изменений: {len(changes)}")

    # ✅ Отправка уведомления в ntfy.sh (если есть изменения)
    if changes:
        try:
            topic = os.getenv("parcing") or NTFY_TOPIC_FALLBACK
            if not topic:
                print("ℹ️ NTFY_TOPIC не задан — уведомление не отправлено.")
            else:
                message = "🔔 Изменения в прайсе:\n\n" + "\n".join(changes)
                if len(message) > 4000:
                    message = message[:4000] + "...\n\n(полный лог — в логах)"
                
                # 🔥 КРИТИЧЕСКИ ВАЖНО: убран пробел в URL!
                response = requests.post(
                    f"https://ntfy.sh/{topic}",  # ← без пробела!
                    data=message.encode("utf-8"),
                    headers={
                        "Title": "🆕 Изменения в прайсе!",
                        "Priority": "high",
                        "Tags": "chart_with_upwards_trend,moneybag"
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    print("✅ Уведомление успешно отправлено в ntfy.sh")
                else:
                    print(f"⚠️ ntfy.sh вернул ошибку: {response.status_code} {response.text}")
        except Exception as e:
            print(f"⚠️ Ошибка при отправке в ntfy.sh: {e}")


if __name__ == "__main__":
    main()

