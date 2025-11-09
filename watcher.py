import re
import requests
from datetime import datetime
import os

# ======================
# 🔑 ПУБЛИЧНАЯ ССЫЛКА НА ПАПКУ (получена через "Получить ссылку")
# ======================
# Пример: https://disk.yandex.ru/d/AbcDef123ghIjK/ → ключ = AbcDef123ghIjK
YANDEX_PUBLIC_KEY = "AbcDef123ghIjK"  # ← ЗАМЕНИТЕ НА ВАШ КЛЮЧ!
BASE_URL = f"https://disk.yandex.ru/d/{YANDEX_PUBLIC_KEY}"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "parcing")


def list_files():
    """Скачивает HTML папки и парсит имена .txt файлов."""
    resp = requests.get(BASE_URL, timeout=10)
    resp.raise_for_status()
    # Простой способ: ищем все ссылки на .txt
    import re
    links = re.findall(r'href="(/[^"]+\.txt)"', resp.text)
    # Оставляем только имена (убираем путь)
    names = [link.split('/')[-1] for link in links]
    return list(set(names))  # уникальные


def parse_timestamp_from_filename(name: str):
    stem = name.rsplit('.', 1)[0]
    try:
        return datetime.strptime(stem, "%d.%m.%Y_%H.%M.%S")
    except ValueError:
        return None


def download_file_content(name: str) -> str:
    url = f"{BASE_URL}/{name}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    for enc in ('utf-8', 'cp1251'):
        try:
            return response.content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Не удалось декодировать файл")


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
                if all((art_match, name_match, price_match)):
                    article = art_match.group(1)
                    name = name_match.group(1).strip()
                    price = int(re.sub(r"[^\d]", "", price_match.group(1)))
                    products[article] = {"name": name, "price": price}
                i += 3
            except:
                i += 1
        else:
            i += 1
    return products


def format_price(n: int) -> str:
    return f"{n:,} ₽".replace(",", " ")


def main():
    print("📥 Получение списка файлов через публичную ссылку...")
    
    try:
        filenames = list_files()
        txt_files = [f for f in filenames if f.lower().endswith('.txt')]
        print(f"📁 Найдено {len(txt_files)} .txt файлов")
        
        dated_files = []
        for name in txt_files:
            dt = parse_timestamp_from_filename(name)
            if dt:
                dated_files.append((dt, name))
        
        if len(dated_files) < 2:
            print(f"❌ Нужно ≥2 файлов с датой. Есть: {len(dated_files)}")
            return
        
        dated_files.sort(reverse=True)
        latest_name = dated_files[0][1]
        prev_name = dated_files[1][1]

        print(f"✅ Сравниваем: {latest_name} ↔ {prev_name}")

        text_new = download_file_content(latest_name)
        text_old = download_file_content(prev_name)

        products_new = parse_products(text_new)
        products_old = parse_products(text_old)

        all_articles = set(products_new) | set(products_old)
        changes = []

        for art in sorted(all_articles):
            new = products_new.get(art)
            old = products_old.get(art)
            if new and not old:
                changes.append(f"🆕 [{art}] {new['name']}\n   → Добавлен! {format_price(new['price'])}")
            elif old and not new:
                changes.append(f"❌ [{art}] {old['name']}\n   → Удалён. Было: {format_price(old['price'])}")
            elif new and old and new['price'] != old['price']:
                diff = new['price'] - old['price']
                arrow = "📈" if diff > 0 else "📉"
                desc = f"Подорожал на {format_price(diff)}" if diff > 0 else f"Подешевел на {format_price(-diff)}"
                changes.append(f"{arrow} [{art}] {new['name']}\n   {format_price(old['price'])} → {format_price(new['price'])} ({desc})")

        if changes:
            print("\n🔔 Изменения:")
            for ch in changes:
                print(ch)
            print(f"\nℹ️ Всего: {len(changes)}")

            # Отправка в ntfy.sh
            try:
                message = "🔔 Изменения в прайсе:\n\n" + "\n".join(changes)
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=message.encode("utf-8"),
                    headers={
                        "Title": "🆕 Изменения в прайсе!",
                        "Priority": "high",
                        "Tags": "money_with_wings,chart_with_upwards_trend"
                    },
                    timeout=10
                )
                print("✅ Уведомление отправлено в ntfy.sh")
            except Exception as e:
                print(f"⚠️ Ошибка отправки: {e}")
        else:
            print("✅ Изменений нет.")

    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    main()
