"""
آشتی‌دادن (reconcile) لاگ معاملات فرضی + موجودی state.json.

چرا این لازم شد؟
----------------
کشف شد که وقتی دو اجرای این ورک‌فلو (به‌خاطر تریگر دوگانه‌ی بیرونی، مثلاً
cron-job.org) تقریباً هم‌زمان اجرا می‌شن، هر دو از روی همون state.json قدیمی
می‌بینن یه پوزیشن SL/TP خورده، هر دو مستقل می‌بندنش و می‌نویسنش، و بعد
`git pull --rebase` هر دو append رو (چون فایل CSV فقط append می‌شه و از نظر
git تعارض واقعی نداره) توی همون فایل نهایی نگه می‌داره - نتیجه: هر معامله
گاهی دوبار توی CSV ثبت می‌شه و موجودی هم دوبار کم/زیاد می‌شه.

این اسکریپت به‌عنوان لایه‌ی دوم دفاعی (علاوه بر رفع خودِ علت در منبع تریگر)
درست بعد از `git pull --rebase` و درست قبل از commit نهایی اجرا می‌شه: هر
ردیف «close» ی که دقیقاً با یه ردیف دیگه (نماد+منبع+جهت+قیمت ورود/خروج+حجم+
دلیل خروج) یکیه و فاصله‌ی زمانی‌شون کمتر از یه آستانه‌ست (پیش‌فرض ۵ دقیقه -
یه معامله‌ی واقعیِ متفاوت با همین دقتِ کامل توی چند دقیقه‌ی هم تقریباً
غیرممکنه) رو تکراری در نظر می‌گیره، فقط اولی رو نگه می‌داره، ستون
balance_after را برای کل فایل از نو (از روی موجودی شروع) می‌سازه، و
_paper_balance_irt در state.json را دقیقاً برابر همین عدد بازسازی‌شده تنظیم
می‌کند - یعنی موجودی همیشه از روی CSقطعی (نه از یه شمارنده‌ی راهرو که ممکنه
دوبار افزایش/کاهش پیدا کرده باشه) مشتق می‌شه.

اگه موقعی این اسکریپت لازم نبود (هیچ تکراری‌ای نبود)، فایل‌ها دست‌نخورده
می‌مونن (idempotent - اجرای دوباره‌ش هیچ اثر اضافه‌ای نداره).
"""
import sys
import json
import argparse
import pandas as pd

DUP_WINDOW_SECONDS = 300  # ۵ دقیقه - آستانه‌ی «همون معامله، دوبار ثبت شده»
KEY_COLS = ["symbol", "source", "direction", "entry_price", "exit_price", "quantity", "exit_reason"]


def _amount_col(df: pd.DataFrame) -> str:
    for c in ("notional_irt", "notional_usdt"):
        if c in df.columns:
            return c.replace("notional", "pnl"), c.replace("notional", "balance_after")
    raise ValueError("ستون notional_irt یا notional_usdt توی فایل پیدا نشد.")


def dedupe_closes(df: pd.DataFrame, pnl_col: str):
    """
    ردیف‌های close تکراری (طبق KEY_COLS + پنجره‌ی زمانی) را پیدا می‌کند.
    خروجی: (df با ستون کمکی _orig_order, مجموعه‌ی اندیس ردیف‌های تکراری)
    """
    df = df.copy().reset_index(drop=True)
    df["_t"] = pd.to_datetime(df["event_time_utc"], utc=True)
    df["_orig_order"] = range(len(df))

    drop_idx = set()
    closes = df[df["event_type"] == "close"].sort_values(KEY_COLS + ["_t"])
    for _, group in closes.groupby(KEY_COLS, dropna=False, sort=False):
        group = group.sort_values("_t")
        last_kept_t = None
        for idx, row in group.iterrows():
            if last_kept_t is not None and (row["_t"] - last_kept_t).total_seconds() <= DUP_WINDOW_SECONDS:
                drop_idx.add(idx)
            else:
                last_kept_t = row["_t"]
    return df, drop_idx


def correct_balances(df: pd.DataFrame, drop_idx: set, pnl_col: str, balance_col: str):
    """
    ستون balance_after را اصلاح می‌کند، بدون نیاز به دانستن «موجودی شروع».

    برای هر ردیف close نگه‌داشته‌شده: موجودی اصلاح‌شده = موجودی ثبت‌شده منهای
    جمع pnl ردیف‌های تکراریِ حذف‌شده‌ی *قبل از آن، در همان بخش*. «بخش» با
    ریست دستی موجودی (پرشی که با pnl توضیح داده نمی‌شود، مثل تغییر دستی
    state.json یا PAPER_STARTING_BALANCE) تعیین می‌شود: تکراری‌های قبل از یک
    ریست هیچ اثری روی موجودی بعد از آن ندارند.

    خروجی: (df اصلاح‌شده بدون ردیف‌های تکراری, extra_pnl_کل, extra_pnl_بخش_آخر)
    """
    df = df.copy()
    adj = 0.0                # جمع pnl تکراری‌های بخش فعلی
    total_extra = 0.0
    prev_balance = None
    new_balances = {}
    for idx, row in df[df["event_type"] == "close"].iterrows():
        bal, pnl = float(row[balance_col]), float(row[pnl_col])
        if prev_balance is not None and abs(bal - (prev_balance + pnl)) > 1e-6:
            adj = 0.0        # ریست دستی → بخش جدید
        if idx in drop_idx:
            adj += pnl
            total_extra += pnl
        else:
            new_balances[idx] = bal - adj
        prev_balance = bal

    df.loc[list(new_balances.keys()), balance_col] = pd.Series(new_balances)
    cleaned = df.drop(index=list(drop_idx)).sort_values("_orig_order")
    cleaned = cleaned.drop(columns=["_t", "_orig_order"]).reset_index(drop=True)
    return cleaned, total_extra, adj


def reconcile(bot_dir: str, dry_run_preview: bool = False) -> dict:
    """
    موجودی درست بدون حدس‌زدن «موجودی شروع» به‌دست می‌آید: موجودیِ فعلیِ
    state.json منهای جمع pnlِ تکراری‌های *بخش آخر* (بعد از آخرین ریست دستی).
    """
    csv_path = f"{bot_dir}/paper_trades_log.csv"
    state_path = f"{bot_dir}/state.json"

    df = pd.read_csv(csv_path)
    pnl_col, balance_col = _amount_col(df)
    balance_key = balance_col.replace("balance_after", "_paper_balance")

    state = json.load(open(state_path, encoding="utf-8"))
    current_balance = state.get(balance_key)
    if current_balance is None:
        raise ValueError(f"{balance_key} توی {state_path} پیدا نشد.")

    df, drop_idx = dedupe_closes(df, pnl_col)
    cleaned, total_extra, last_segment_extra = correct_balances(df, drop_idx, pnl_col, balance_col)
    corrected_balance = current_balance - last_segment_extra

    report = {
        "bot_dir": bot_dir,
        "rows_before": len(df),
        "rows_after": len(cleaned),
        "duplicate_rows_removed": len(drop_idx),
        "double_counted_pnl_total": total_extra,
        "double_counted_pnl_last_segment": last_segment_extra,
        "balance_before_state": current_balance,
        "final_balance_corrected": corrected_balance,
    }

    if not dry_run_preview and len(drop_idx) > 0:
        cleaned.to_csv(csv_path, index=False)
        state[balance_key] = corrected_balance
        json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bot_dir", help="مسیر پوشه‌ی بات، مثل bot1_live")
    parser.add_argument("--starting-balance", type=float, default=None,
                         help="[منسوخ/اختیاری - دیگه استفاده نمی‌شه، فقط برای سازگاری با فراخوانی‌های قدیمی]")
    parser.add_argument("--dry-run", action="store_true", help="فقط گزارش بده، فایلی ننویس")
    args = parser.parse_args()

    rep = reconcile(args.bot_dir, dry_run_preview=args.dry_run)
    print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    if rep["duplicate_rows_removed"] == 0:
        print("✅ هیچ ردیف تکراری‌ای پیدا نشد - فایل‌ها دست‌نخورده موندن.")
    else:
        print(f"🔧 {rep['duplicate_rows_removed']} ردیف تکراری حذف شد و موجودی بازسازی شد.")
