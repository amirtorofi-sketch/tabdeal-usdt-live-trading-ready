"""
موازی‌سازی درخواست‌های شبکه (فقط I/O) — هیچ منطق معاملاتی اینجا نیست.

parallel_map تابع fn را روی همه‌ی آیتم‌ها با تعداد محدودی ترد اجرا می‌کند و
دیکشنری {آیتم: نتیجه یا Exception} برمی‌گرداند (خطا پرتاب نمی‌شود، تا فراخواننده
دقیقاً مثل قبل برای هر آیتم جداگانه تصمیم بگیرد). روی خطاهای گذرا (مثل ۴۲۹)
با backoff کوتاه چند بار دوباره تلاش می‌کند.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

IO_WORKERS = int(os.environ.get("IO_WORKERS", "8"))
IO_RETRIES = int(os.environ.get("IO_RETRIES", "2"))


def _with_retry(fn, item):
    last = None
    for attempt in range(IO_RETRIES + 1):
        try:
            return fn(item)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < IO_RETRIES:
                time.sleep(1.0 * (attempt + 1))
    return last


def parallel_map(fn, items, workers: int = None) -> dict:
    items = list(items)
    if not items:
        return {}
    workers = max(1, min(workers or IO_WORKERS, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda it: _with_retry(fn, it), items))
    return dict(zip(items, results))
