from flask import Flask, render_template, request
from datetime import datetime, timedelta
from math import ceil
from collections import defaultdict

app = Flask(__name__)

# =============================
# 高額療養費 上限（簡易モデル）
# 1ヶ月ごとにカウントして4回目以降を多数回にする
# =============================
LIMIT_TABLE = {
    "ウ": {"normal": 57600, "many": 44400},
    "エ": {"normal": 35400, "many": 24600},
    "非課税": {"normal": 35400, "many": 24600},
}

# =============================
# 薬価マスタ（例：あとで差し替え可）
# =============================
INHALE_MAIN = {
    "テリルジー200": {"days": 28, "price": 11200},
    "アドエア500": {"days": 28, "price": 9800},
    "アドエアエアゾール250": {"days": 28, "price": 8600},
    "エナジア高用量": {"days": 28, "price": 10500},
}

INHALE_VARIABLE = {
    "フルティフォーム125（120吸入）": {"puffs": 120, "price": 8900},
    "ブデホル（60吸入）": {"puffs": 60, "price": 7600},
}

INHALE_ADDON = {
    "スピリーバ レスピマット2.5μg": {"days": 30, "price": 5200},
}

ORAL = {
    "モンテルカスト10": {"days": 30, "price": 2300},
    "テオフィリン徐放U200": {"days": 30, "price": 1800},
}

BIO = {
    "テゼスパイア": {"price": 145000},
    "ヌーカラ": {"price": 138000},
    "デュピルマブ": {"price": 82000},
}


def to_30days(price: float, days: int) -> int:
    return int((price / days) * 30)


def calc_existing(form) -> dict:
    """既存治療（30日換算）の合計と内訳を返す"""
    total = 0
    details = []

    # 吸入（28日→30日換算）
    for name, d in INHALE_MAIN.items():
        if form.get(name):
            m = to_30days(d["price"], d["days"])
            details.append((name, m))
            total += m

    # 可変吸入（本数切り上げ）
    for name, d in INHALE_VARIABLE.items():
        if form.get(name):
            puff = form.get(f"puff_{name}", "1")
            try:
                puff = int(puff)
            except:
                puff = 1
            if puff < 1:
                puff = 1

            daily = 2 * puff
            total_puff = daily * 30
            bottles = ceil(total_puff / d["puffs"])
            m = bottles * d["price"]
            details.append((f"{name}（1回{puff}吸入）", m))
            total += m

    # 追加吸入（簡易：チェックされたら加算）
    if form.get("use_addon"):
        for name, d in INHALE_ADDON.items():
            if form.get(name):
                m = to_30days(d["price"], d["days"])
                details.append((name, m))
                total += m

    # 内服（30日）
    for name, d in ORAL.items():
        if form.get(name):
            m = to_30days(d["price"], d["days"])
            details.append((name, m))
            total += m

    return {"total": total, "details": details}


def build_bio_events(start: datetime, drug: str, pattern: str):
    """
    生物学的製剤のイベント（日付, 本数）を作る
    ※説明用の簡易パターン
    """
    events = []
    d = start

    if drug in ["テゼスパイア", "ヌーカラ"]:
        if pattern == "査定配慮型（月初月末開始）":
            # 月初 1本 → 同月末 1本 → 以降 12週ごとに3本
            events.append((d, 1))
            events.append((d + timedelta(days=27), 1))
            d2 = d + timedelta(days=84)
            while len(events) < 10:
                events.append((d2, 3))
                d2 += timedelta(days=84)
        else:
            # 標準開始型：1本 → 以降 12週ごとに3本
            events.append((d, 1))
            d2 = d + timedelta(days=84)
            while len(events) < 10:
                events.append((d2, 3))
                d2 += timedelta(days=84)

    elif drug == "デュピルマブ":
        if pattern == "月初2→2週後1→4週後2→翌月以降6本まとめ":
            events.append((d, 2))
            events.append((d + timedelta(days=14), 1))
            events.append((d + timedelta(days=28), 2))
            d2 = d + timedelta(days=56)
            while len(events) < 10:
                events.append((d2, 6))
                d2 += timedelta(days=84)
        else:
            # 2→2週後1→翌月以降6本まとめ
            events.append((d, 2))
            events.append((d + timedelta(days=14), 1))
            d2 = d + timedelta(days=42)
            while len(events) < 10:
                events.append((d2, 6))
                d2 += timedelta(days=84)

    return events


def calc_bio_monthly_with_cap(start: datetime, drug: str, pattern: str, income: str):
    """
    月ごとに生物学的製剤の総額(raw)を集計し、上限(cap)を適用してpayを返す
    さらに 4回目以降(many) 判定も入れる
    """
    unit_price = BIO[drug]["price"]
    events = build_bio_events(start, drug, pattern)

    monthly_raw = defaultdict(int)
    for dt, n in events:
        key = dt.strftime("%Y-%m")
        monthly_raw[key] += n * unit_price

    results = []
    count = 0
    for month in sorted(monthly_raw.keys()):
        count += 1
        raw = monthly_raw[month]
        cap = LIMIT_TABLE[income]["many"] if count >= 4 else LIMIT_TABLE[income]["normal"]
        pay = min(raw, cap)
        results.append({
            "month": month,
            "raw": raw,
            "cap": cap,
            "pay": pay,
            "many": count >= 4,
            "count": count
        })

    return results


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        income = request.form["income"]

        # 既存治療（月額）
        base = calc_existing(request.form)

        # 生物学的製剤
        bio_drug = request.form["bio"]
        start = datetime.strptime(request.form["start"], "%Y-%m-%d")
        pattern = request.form.get("pattern", "標準開始型")

        bio = calc_bio_monthly_with_cap(start, bio_drug, pattern, income)

        # 開始月の支払い
        first_pay = bio[0]["pay"] if bio else 0
        diff = first_pay - base["total"]

        # ★4回目以降（多数回）最初の月＆金額を抽出
        many_first = next((r for r in bio if r["many"]), None)
        many_first_month = many_first["month"] if many_first else None
        many_first_pay = many_first["pay"] if many_first else None
        many_first_cap = many_first["cap"] if many_first else None

        return render_template(
            "result.html",
            base=base,
            bio=bio,
            diff=diff,
            bio_drug=bio_drug,
            income=income,
            pattern=pattern,
            many_first_month=many_first_month,
            many_first_pay=many_first_pay,
            many_first_cap=many_first_cap
        )

    return render_template(
        "index.html",
        inhale_main=INHALE_MAIN.keys(),
        inhale_var=INHALE_VARIABLE.keys(),
        inhale_addon=INHALE_ADDON.keys(),
        oral=ORAL.keys(),
        bio=BIO.keys()
    )


if __name__ == "__main__":
    app.run(debug=True)
