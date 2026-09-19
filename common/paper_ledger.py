"""
دفتر معاملات آزمایشی (Paper Ledger) — برای دوره‌ی «فعلاً زنده خاموش، فقط تست
سودآوری روی قیمت واقعی تبدیل». هیچ سفارش واقعی ثبت نمی‌کند؛ فقط با قیمت
لحظه‌ای *واقعی* تبدیل (از common.tabdeal_broker.get_mid_price) باز/بسته‌شدن
پوزیشن را شبیه‌سازی می‌کند و سود/زیان فرضی + موجودی فرضی را در یک CSV
ثبت می‌کند تا بعداً ببینی استراتژی روی این صرافی (با اسپرد/قیمت واقعی‌اش)
هنوز سودده هست یا نه.
"""

import csv
import os

FIELDS = [
    "event_time_utc", "event_type", "symbol", "source", "direction",
    "entry_price", "exit_price", "sl", "tp1", "tp2", "quantity",
    "notional_usdt", "pnl_usdt", "balance_after_usdt", "exit_reason",
]


def _ensure_header(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def _append_row(path: str, row: dict):
    _ensure_header(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)


def record_open(path: str, now_iso: str, symbol: str, source: str, direction: str,
                 entry_price: float, sl: float, tp1: float, tp2: float,
                 quantity: float, notional_usdt: float):
    _append_row(path, {
        "event_time_utc": now_iso, "event_type": "open", "symbol": symbol, "source": source,
        "direction": direction, "entry_price": entry_price, "exit_price": "",
        "sl": sl, "tp1": tp1, "tp2": tp2, "quantity": quantity,
        "notional_usdt": notional_usdt, "pnl_usdt": "", "balance_after_usdt": "", "exit_reason": "",
    })


def record_close(path: str, now_iso: str, symbol: str, source: str, direction: str,
                  entry_price: float, exit_price: float, quantity: float,
                  balance_before_usdt: float, exit_reason: str) -> float:
    """
    PnL فرضی را حساب می‌کند، موجودیِ فرضیِ *بعد از* همین معامله را در CSV
    ثبت می‌کند، و PnL را برمی‌گرداند (به تتر، بر پایه‌ی حرکت قیمت پایه).

    نکته: قبلاً این تابع مقدار balance_before_usdt را مستقیماً به‌عنوان
    balance_after_usdt می‌نوشت — یعنی هر ردیف CSV یک معامله عقب‌تر بود و
    آخرین ردیف اصلاً موجودی واقعی فعلی را نشان نمی‌داد. الان قبل از نوشتن،
    pnl همین معامله به موجودی قبلی اضافه می‌شود تا ستون واقعاً «بعد از» را
    نشان دهد.
    """
    sign = 1 if direction == "long" else -1
    pnl_usdt = (exit_price - entry_price) * quantity * sign
    balance_after_usdt = balance_before_usdt + pnl_usdt
    _append_row(path, {
        "event_time_utc": now_iso, "event_type": "close", "symbol": symbol, "source": source,
        "direction": direction, "entry_price": entry_price, "exit_price": exit_price,
        "sl": "", "tp1": "", "tp2": "", "quantity": quantity,
        "notional_usdt": "", "pnl_usdt": pnl_usdt, "balance_after_usdt": balance_after_usdt,
        "exit_reason": exit_reason,
    })
    return pnl_usdt
