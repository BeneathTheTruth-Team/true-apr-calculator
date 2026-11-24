# -*- coding: utf-8 -*-
"""真实资金成本计算器：核心算法模块。

本模块与 Web 层完全解耦，仅使用 Python 标准库，可在任何
Python 3.8+ 环境中独立运行和被单元测试。

约定：
- 现金流列表 index 0 表示期初（放款时刻），之后每个 index 表示一期期末。
- 放款（借款人拿到钱）为正，还款（借款人付出钱）为负。
- 所有金额内部用 float 计算，展示层保留两位小数。
"""


def cashflows_for_installment(principal, periods, fee_rate, upfront_fee=0.0):
    """构造"等本等息"分期方案的现金流列表。

    参数：
        principal   借款本金（放款金额）。
        periods     期数（正整数）。
        fee_rate    每期手续费率（小数，如 0.006 表示每期 0.6%）。
        upfront_fee 放款时一次性扣除的手续费/砍头息，默认 0。

    返回：
        长度为 periods + 1 的现金流列表。index 0 为期初实际到手金额
        principal - upfront_fee（正）；之后每期期末还款为负，
        每期还款 = principal / periods + principal * fee_rate。
    """
    if principal <= 0:
        raise ValueError("principal 必须大于 0")
    if not isinstance(periods, int) or isinstance(periods, bool) or periods <= 0:
        raise ValueError("periods 必须是正整数")
    if fee_rate < 0:
        raise ValueError("fee_rate 不能为负")
    if upfront_fee < 0:
        raise ValueError("upfront_fee 不能为负")
    if upfront_fee >= principal:
        raise ValueError("upfront_fee 不能大于等于本金，否则期初现金流非正")

    payment_per_period = principal / periods + principal * fee_rate
    cashflows = [principal - upfront_fee]
    cashflows.extend([-payment_per_period] * periods)
    return cashflows


def npv(cashflows, rate):
    """按给定每期折现率计算现金流的净现值（NPV）。

    参数：
        cashflows 现金流列表，index 0 为期初。
        rate      每期折现率（小数）。

    返回：
        NPV 的 float 值。rate <= -1 时抛出 ValueError。
    """
    if rate <= -1:
        raise ValueError("rate 必须大于 -1，否则折现无意义")
    total = 0.0
    discount = 1.0
    base = 1.0 + rate
    for cf in cashflows:
        total += cf / discount
        discount *= base
    return total


def monthly_irr(cashflows, tol=1e-10, max_iter=200):
    """用二分法求月内部收益率（使 NPV=0 的每期利率）。

    处理逻辑：
    1. 若 rate=0 时 NPV 已为 0（如无手续费分期，还款总额恰好等于
       期初到手金额），直接返回 0.0。
    2. 从区间 [0, 1] 开始找 NPV 变号区间；若 high=1 处仍未变号，
       逐步扩大 high（乘 2，最多扩到 1024）。
    3. 若仍找不到变号区间，返回 None（不硬猜）。
    4. 找到区间后二分迭代，直到区间宽度小于 tol 或达到 max_iter。

    返回：
        月 IRR（float），找不到时返回 None。
    """
    npv_at_zero = npv(cashflows, 0.0)
    if abs(npv_at_zero) < tol:
        return 0.0

    # 常规信贷现金流：期初为正、之后为负。rate 越大 NPV 越大，
    # 因此 low 处 NPV < 0、high 处 NPV > 0 才构成变号区间。
    low, high = 0.0, 1.0
    npv_low = npv_at_zero
    npv_high = npv(cashflows, high)
    # 找不到变号就扩大 high，最多扩到 1024（仍无 bracket 则返回 None）
    while npv_low * npv_high > 0 and high < 1024.0:
        high *= 2.0
        npv_high = npv(cashflows, high)
    if npv_low * npv_high > 0:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        npv_mid = npv(cashflows, mid)
        if abs(npv_mid) < tol or (high - low) < tol:
            return mid
        if npv_low * npv_mid < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    return (low + high) / 2.0


def annualized_irr(monthly_rate, method="nominal"):
    """把月 IRR 换算为年化口径。

    参数：
        monthly_rate 月 IRR（小数）。
        method       "nominal"   名义年化 = monthly_rate * 12
                     "effective" 有效年利率 = (1 + monthly_rate) ** 12 - 1

    返回：
        年化利率（float，小数）。method 非法时抛 ValueError。
    """
    if method == "nominal":
        return monthly_rate * 12
    if method == "effective":
        return (1.0 + monthly_rate) ** 12 - 1
    raise ValueError("method 必须是 'nominal' 或 'effective'")


def effective_annual_rate(monthly_rate):
    """有效年利率（EAR）便捷函数，等价于 annualized_irr(rate, "effective")。"""
    return annualized_irr(monthly_rate, method="effective")


def simulate_min_payment(balance, monthly_rate, payment_ratio,
                         stop_balance=0.01, max_months=1200):
    """模拟"每月只还最低还款"的信用卡/循环信贷还款过程。

    固定口径（每月顺序不可变）：
    1. 先按还款前余额计息：interest = balance * monthly_rate；
    2. 计息后余额 = balance + interest；
    3. 当月还款 payment = 计息后余额 * payment_ratio；
    4. 若 payment >= 计息后余额，则全额结清（ending_balance = 0）。

    停止条件：余额 <= stop_balance 视为还清；或达到 max_months。

    参数：
        balance       初始欠款金额。
        monthly_rate  月利率（小数）。
        payment_ratio 每月还款比例（小数，相对计息后余额）。
        stop_balance  视为还清的余额阈值，默认 0.01。
        max_months    最大模拟月数，默认 1200。

    返回：
        dict：months（还清月数）、total_interest（累计利息）、
        rows（逐月明细，每项含 month, beginning_balance, interest,
        payment, ending_balance）。

    异常：
        payment_ratio <= monthly_rate 时抛 ValueError —— 该参数下
        每月还款不高于当月利息，余额永远不会下降，无法还清。
    """
    if balance <= 0:
        raise ValueError("balance 必须大于 0")
    if monthly_rate < 0:
        raise ValueError("monthly_rate 不能为负")
    if payment_ratio <= 0:
        raise ValueError("payment_ratio 必须大于 0")
    if payment_ratio <= monthly_rate:
        raise ValueError(
            "每月还款比例（{:.2%}）不高于月利率（{:.2%}）：每月还款"
            "不高于当月利息，余额不会下降，永远无法还清。".format(
                payment_ratio, monthly_rate)
        )

    rows = []
    total_interest = 0.0
    month = 0
    current = balance

    while current > stop_balance and month < max_months:
        month += 1
        beginning = current
        interest = beginning * monthly_rate
        after_interest = beginning + interest
        payment = after_interest * payment_ratio
        if payment >= after_interest:
            payment = after_interest
            ending = 0.0
        else:
            ending = after_interest - payment
        total_interest += interest
        rows.append({
            "month": month,
            "beginning_balance": beginning,
            "interest": interest,
            "payment": payment,
            "ending_balance": ending,
        })
        current = ending

    return {
        "months": month,
        "total_interest": total_interest,
        "rows": rows,
    }
