# -*- coding: utf-8 -*-
"""真实资金成本计算器（true-apr-calculator）Flask Web 层。

仅负责：路由、表单校验、调用 calculator.py 核心算法、SQLite 存取、
渲染 Jinja2 模板。不调用任何网络 API，无登录/用户系统。
兼容 Python 3.8+，唯一第三方依赖为 Flask。
"""
import os
import sqlite3
from datetime import datetime

from flask import Flask, abort, g, redirect, render_template, request, url_for

import calculator

app = Flask(__name__)
app.config["DATABASE"] = os.path.join(app.instance_path, "true_apr.db")

# 表单校验的合理范围（百分数口径）
MAX_PERIODS = 360            # 分期期数上限
MAX_FEE_RATE_PERCENT = 20.0  # 每期手续费率上限（%）
MAX_MONTHLY_RATE_PERCENT = 20.0   # 月利率上限（%）
MAX_PAYMENT_RATIO_PERCENT = 100.0  # 每月还款比例上限（%）

SCHEMA = """
CREATE TABLE IF NOT EXISTS schemes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    principal REAL NOT NULL,
    periods INTEGER NOT NULL,
    fee_rate REAL NOT NULL,
    upfront_fee REAL NOT NULL DEFAULT 0,
    monthly_payment REAL NOT NULL,
    total_interest REAL NOT NULL,
    nominal_total_rate REAL NOT NULL,
    monthly_irr REAL,
    nominal_annual REAL,
    effective_annual REAL,
    created_at TEXT NOT NULL
);
"""


# ---------- 数据库 ----------

def get_db():
    """获取当前请求内的 SQLite 连接（按请求复用）。"""
    if "db" not in g:
        os.makedirs(app.instance_path, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """建表（幂等），应用启动时调用。"""
    os.makedirs(app.instance_path, exist_ok=True)
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------- 表单校验工具 ----------

def parse_float(value):
    """把表单字符串解析为 float，失败返回 None。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value):
    """把表单字符串解析为正整数，失败返回 None。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number


def validate_installment_form(form):
    """校验分期计算器表单。

    返回 (params, errors)：params 为清洗后的 dict，errors 为错误信息列表。
    """
    errors = []
    name = (form.get("name") or "").strip()[:50]  # 方案名可选，限长 50
    principal = parse_float(form.get("principal"))
    periods = parse_int(form.get("periods"))
    fee_rate_percent = parse_float(form.get("fee_rate"))
    upfront_raw = (form.get("upfront_fee") or "").strip()
    upfront_fee = parse_float(upfront_raw) if upfront_raw else 0.0

    if principal is None or principal <= 0:
        errors.append("借款金额必须是大于 0 的数字。")
    if periods is None or periods <= 0:
        errors.append("期数必须是正整数。")
    elif periods > MAX_PERIODS:
        errors.append("期数不能超过 {} 期。".format(MAX_PERIODS))
    if fee_rate_percent is None or fee_rate_percent < 0:
        errors.append("每期手续费率必须是不小于 0 的百分数。")
    elif fee_rate_percent > MAX_FEE_RATE_PERCENT:
        errors.append(
            "每期手续费率超过 {}%，超出合理范围，请确认输入的是百分数。".format(
                MAX_FEE_RATE_PERCENT))
    if upfront_fee is None or upfront_fee < 0:
        errors.append("放款手续费/砍头息必须是不小于 0 的数字，可留空表示无。")
    elif principal is not None and principal > 0 and upfront_fee >= principal:
        errors.append("放款手续费/砍头息不能大于等于借款金额。")

    params = {
        "name": name,
        "principal": principal,
        "periods": periods,
        "fee_rate": fee_rate_percent / 100.0 if fee_rate_percent is not None else None,
        "fee_rate_percent": fee_rate_percent,
        "upfront_fee": upfront_fee,
    }
    return params, errors


def validate_min_payment_form(form):
    """校验最低还款模拟表单。返回 (params, errors)。"""
    errors = []
    balance = parse_float(form.get("balance"))
    monthly_rate_percent = parse_float(form.get("monthly_rate"))
    payment_ratio_percent = parse_float(form.get("payment_ratio"))

    if balance is None or balance <= 0:
        errors.append("欠款金额必须是大于 0 的数字。")
    if monthly_rate_percent is None or monthly_rate_percent <= 0:
        errors.append("月利率必须是大于 0 的百分数。")
    elif monthly_rate_percent > MAX_MONTHLY_RATE_PERCENT:
        errors.append(
            "月利率超过 {}%，超出合理范围，请确认输入的是百分数。".format(
                MAX_MONTHLY_RATE_PERCENT))
    if payment_ratio_percent is None or payment_ratio_percent <= 0:
        errors.append("每月还款比例必须是大于 0 的百分数。")
    elif payment_ratio_percent > MAX_PAYMENT_RATIO_PERCENT:
        errors.append("每月还款比例不能超过 100%。")

    # 硬性规则：最低还款比例必须大于月利率，否则余额不会下降
    if (monthly_rate_percent is not None and payment_ratio_percent is not None
            and monthly_rate_percent > 0 and payment_ratio_percent > 0
            and payment_ratio_percent <= monthly_rate_percent):
        errors.append(
            "每月还款比例（{:.2f}%）必须大于月利率（{:.2f}%），"
            "否则每月还款不高于当月利息，余额不会下降，永远无法还清。".format(
                payment_ratio_percent, monthly_rate_percent))

    params = {
        "balance": balance,
        "monthly_rate": (monthly_rate_percent / 100.0
                         if monthly_rate_percent is not None else None),
        "monthly_rate_percent": monthly_rate_percent,
        "payment_ratio": (payment_ratio_percent / 100.0
                          if payment_ratio_percent is not None else None),
        "payment_ratio_percent": payment_ratio_percent,
    }
    return params, errors


# ---------- 计算逻辑（Web 层薄封装） ----------

def compute_installment(params):
    """根据校验后的分期参数计算全部结果指标。"""
    cashflows = calculator.cashflows_for_installment(
        params["principal"], params["periods"],
        params["fee_rate"], params["upfront_fee"])
    monthly_payment = -cashflows[1]
    total_interest = params["principal"] * params["fee_rate"] * params["periods"]
    nominal_total_rate = total_interest / params["principal"]
    irr = calculator.monthly_irr(cashflows)
    nominal_annual = (calculator.annualized_irr(irr, "nominal")
                      if irr is not None else None)
    effective_annual = (calculator.annualized_irr(irr, "effective")
                        if irr is not None else None)
    return {
        "cashflows": cashflows,
        "monthly_payment": monthly_payment,
        "total_interest": total_interest,
        "nominal_total_rate": nominal_total_rate,
        "monthly_irr": irr,
        "nominal_annual": nominal_annual,
        "effective_annual": effective_annual,
        "amount_received": params["principal"] - params["upfront_fee"],
        "total_payment": monthly_payment * params["periods"],
    }


def save_scheme(params, result):
    """把有效方案写入 SQLite（全部使用参数化 SQL）。"""
    name = params["name"] or "未命名方案"
    db = get_db()
    db.execute(
        "INSERT INTO schemes (name, principal, periods, fee_rate, upfront_fee,"
        " monthly_payment, total_interest, nominal_total_rate, monthly_irr,"
        " nominal_annual, effective_annual, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, params["principal"], params["periods"], params["fee_rate"],
         params["upfront_fee"], result["monthly_payment"],
         result["total_interest"], result["nominal_total_rate"],
         result["monthly_irr"], result["nominal_annual"],
         result["effective_annual"],
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    db.commit()


def build_balance_chart_points(rows, max_points=200):
    """把逐月余额明细抽稀为最多 max_points 个 (month, balance) 点，
    保证首尾点始终保留，用于内联 SVG 折线图。"""
    points = [(row["month"], row["ending_balance"]) for row in rows]
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / float(max_points - 1)
    sampled = [points[round(i * step)] for i in range(max_points - 1)]
    sampled.append(points[-1])
    return sampled


def build_svg_polyline(points, width=720.0, height=240.0):
    """把 (month, balance) 点列转换为内联 SVG polyline 的 points 字符串。

    x 轴为月序，y 轴为余额（顶点为最大余额，即第 1 个月末之前的初始值
    由调用方保证包含在 points 内）。
    """
    if not points:
        return "", 0.0
    max_balance = max(balance for _, balance in points)
    if max_balance <= 0:
        max_balance = 1.0
    max_month = max(month for month, _ in points)
    if max_month <= 0:
        max_month = 1
    coords = []
    for month, balance in points:
        x = (month / float(max_month)) * width
        y = height - (balance / max_balance) * height
        coords.append("{:.1f},{:.1f}".format(x, y))
    return " ".join(coords), max_balance


def split_rows_for_table(rows, head=12, tail=12):
    """把逐月明细拆成"前若干月 + 省略 + 后若干月"，避免渲染上千行。"""
    if len(rows) <= head + tail + 1:
        return rows, None, []
    return rows[:head], len(rows) - head - tail, rows[-tail:]


# ---------- 路由 ----------

@app.route("/", methods=["GET", "POST"])
def index():
    errors = []
    form = {"name": "", "principal": "", "periods": "",
            "fee_rate": "", "upfront_fee": ""}
    result = None
    params = None
    if request.method == "POST":
        form = {key: (request.form.get(key) or "").strip()
                for key in ("name", "principal", "periods",
                            "fee_rate", "upfront_fee")}
        params, errors = validate_installment_form(request.form)
        if not errors:
            result = compute_installment(params)
            save_scheme(params, result)
    return render_template(
        "index.html", active_page="index", errors=errors, form=form,
        params=params, result=result)


@app.route("/schemes/")
def schemes():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM schemes ORDER BY created_at DESC, id DESC"
    ).fetchall()
    max_nominal = None
    valid = [r["nominal_annual"] for r in rows if r["nominal_annual"] is not None]
    if valid:
        max_nominal = max(valid)
    return render_template(
        "schemes.html", active_page="schemes", schemes=rows,
        max_nominal=max_nominal)


@app.route("/schemes/<int:scheme_id>/delete", methods=["POST"])
def delete_scheme(scheme_id):
    db = get_db()
    cursor = db.execute("DELETE FROM schemes WHERE id = ?", (scheme_id,))
    db.commit()
    if cursor.rowcount == 0:
        abort(404)
    return redirect(url_for("schemes"))


@app.route("/min-payment/", methods=["GET", "POST"])
def min_payment():
    errors = []
    form = {"balance": "", "monthly_rate": "", "payment_ratio": ""}
    result = None
    chart_points = None
    chart_polyline = None
    chart_max_balance = None
    head_rows = tail_rows = None
    omitted = 0
    if request.method == "POST":
        form = {key: (request.form.get(key) or "").strip()
                for key in ("balance", "monthly_rate", "payment_ratio")}
        params, errors = validate_min_payment_form(request.form)
        if not errors:
            try:
                result = calculator.simulate_min_payment(
                    balance=params["balance"],
                    monthly_rate=params["monthly_rate"],
                    payment_ratio=params["payment_ratio"])
            except ValueError as exc:
                errors.append(str(exc))
            else:
                chart_points = build_balance_chart_points(result["rows"])
                chart_polyline, chart_max_balance = build_svg_polyline(
                    chart_points)
                head_rows, omitted, tail_rows = split_rows_for_table(
                    result["rows"])
                if omitted is None:
                    omitted = 0
    return render_template(
        "min_payment.html", active_page="min_payment", errors=errors,
        form=form, result=result, chart_polyline=chart_polyline,
        chart_max_balance=chart_max_balance,
        head_rows=head_rows, omitted=omitted, tail_rows=tail_rows)


@app.route("/education/")
def education():
    return render_template("education.html", active_page="education")


@app.template_filter("money")
def money_filter(value):
    """金额展示：保留两位小数。"""
    if value is None:
        return "—"
    return "{:,.2f}".format(value)


@app.template_filter("percent")
def percent_filter(value, digits=2):
    """小数转百分数字符串展示。"""
    if value is None:
        return "—"
    return ("{:." + str(digits) + "f}%").format(value * 100)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
