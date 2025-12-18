from flask import Flask, render_template, request
from datetime import datetime, timedelta
from math import ceil
from collections import defaultdict

app = Flask(__name__)

# =============================
# 高額療養費 上限（簡易）
# =============================
LIMIT_TABLE = {
    "ウ": {"normal": 57600, "many": 44400},
    "エ": {"normal": 35400, "many": 24600},
    "非課税": {"normal": 35400, "many": 24600},
}

# =============================
# 薬価マスタ（例）
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

def to_30days(price, days):
    return int((price / days) * 30)

def calc_existing(form):
    total = 0
    details = []

    for name, d in INHALE_MAIN.items():
        if form.get(name):
            m = to_30days(d["price"], d["days"])
            details.append((name, m))
            total += m

    for name, d in INHALE_VARIABLE.items():
        if form.get(name):
            puff = int(form.get(f"puff_{name}", 1))
            daily = 2 * puff
            total_puff = daily * 30
            bottles = ceil(total_puff / d["puffs"])
            m = bottles * d["price"]
            details.append((f"{name}（1回{puff}吸入）", m))
            total += m

    if form.get("use_addon"):
        for name, d in INHALE_ADDON.items():
            if form.get(name):
                m = to_30days(d["price"], d["days"])
                details.append((name, m))
                total += m

    for name, d in ORAL.items():
        if form.get(name):
            m = to_30days(d["price"], d["days"])
            details.append((name, m))
            total += m

    return {"total": total, "details": details}

def calc_bio(start, drug, income):
    events = []
    d = start

    if drug in ["テゼスパイア", "ヌーカラ"]:
        events.append((d, 1))
        d += timedelta(days=84)
        while len(events) < 6:
            events.append((d, 3))
            d += timedelta(days=84)

    if drug == "デュピルマブ":
        events.append((d, 2))
        events.append((d + timedelta(days=14), 1))
        d += timedelta(days=42)
        while len(events) < 6:
            events.append((d, 6))
            d += timedelta(days=84)

    monthly = defaultdict(int)
    for dt, n in events:
        monthly[dt.strftime("%Y-%m")] += n * BIO[drug]["price"]

    results = []
    count = 0
    for m in sorted(monthly):
        count += 1
        cap = LIMIT_TABLE[income]["many"] if count >= 4 else LIMIT_TABLE[income]["normal"]
        pay = min(monthly[m], cap)
        results.append({"month": m, "pay": pay})

    return results

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        income = request.form["income"]
        base = calc_existing(request.form)

        bio_drug = request.form["bio"]
        start = datetime.strptime(request.form["start"], "%Y-%m-%d")
        bio = calc_bio(start, bio_drug, income)

        diff = bio[0]["pay"] - base["total"]

        return render_template(
            "result.html",
            base=base,
            bio=bio,
            diff=diff,
            bio_drug=bio_drug
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
app.run(debug=True, port=5001)
