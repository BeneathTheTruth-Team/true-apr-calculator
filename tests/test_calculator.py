# -*- coding: utf-8 -*-
"""calculator.py 的单元测试，使用标准库 unittest。

运行方式（在项目根目录）：
    python -m unittest discover tests -v
"""
import os
import sys
import unittest

# 允许从项目根目录直接运行本测试文件
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from calculator import (
    annualized_irr,
    cashflows_for_installment,
    effective_annual_rate,
    monthly_irr,
    npv,
    simulate_min_payment,
)


class TestInstallmentIRR(unittest.TestCase):
    """分期方案现金流与 IRR 测试。"""

    def setUp(self):
        # 规格基准用例：借 1200 元，分 12 期，每期手续费率 0.6%
        self.principal = 1200.0
        self.periods = 12
        self.fee_rate = 0.006
        self.cashflows = cashflows_for_installment(
            self.principal, self.periods, self.fee_rate)

    def test_cashflow_structure(self):
        # 期初到手 1200，之后 12 期每期还款 107.2
        self.assertEqual(len(self.cashflows), 13)
        self.assertAlmostEqual(self.cashflows[0], 1200.0, places=2)
        for cf in self.cashflows[1:]:
            self.assertAlmostEqual(cf, -107.2, places=2)

    def test_total_interest(self):
        # 每期手续费 1200 * 0.006 = 7.2，总利息 86.4
        total_interest = self.principal * self.fee_rate * self.periods
        self.assertAlmostEqual(total_interest, 86.4, places=2)
        total_payment = -sum(self.cashflows[1:])
        self.assertAlmostEqual(total_payment - self.principal, 86.4, places=2)

    def test_monthly_irr_value(self):
        irr = monthly_irr(self.cashflows)
        self.assertIsNotNone(irr)
        self.assertAlmostEqual(irr, 0.0108618536, delta=0.0005)
        # 求得的 IRR 应使 NPV 归零
        self.assertAlmostEqual(npv(self.cashflows, irr), 0.0, delta=1e-6)

    def test_annualized_rates(self):
        irr = monthly_irr(self.cashflows)
        nominal = annualized_irr(irr, method="nominal")
        effective = annualized_irr(irr, method="effective")
        # 名义年化约 13.034224%，有效年利率约 13.84%
        self.assertAlmostEqual(nominal, 0.13034224, delta=0.0005)
        self.assertAlmostEqual(effective, 0.1384, delta=0.0005)
        # 有效年利率应略高于名义年化
        self.assertGreater(effective, nominal)

    def test_zero_fee_rate_returns_zero_irr(self):
        # fee_rate = 0 时还款总额等于本金，IRR 应直接为 0
        cashflows = cashflows_for_installment(1200.0, 12, 0.0)
        self.assertEqual(monthly_irr(cashflows), 0.0)

    def test_upfront_fee_raises_irr(self):
        # 同样条件下，加收 120 元砍头息后名义年化应更高
        irr_no_fee = monthly_irr(self.cashflows)
        cashflows_with_fee = cashflows_for_installment(
            self.principal, self.periods, self.fee_rate, upfront_fee=120.0)
        irr_with_fee = monthly_irr(cashflows_with_fee)
        self.assertIsNotNone(irr_with_fee)
        self.assertGreater(
            annualized_irr(irr_with_fee, "nominal"),
            annualized_irr(irr_no_fee, "nominal"),
        )

    def test_invalid_params(self):
        with self.assertRaises(ValueError):
            cashflows_for_installment(0, 12, 0.006)
        with self.assertRaises(ValueError):
            cashflows_for_installment(1200, 0, 0.006)
        with self.assertRaises(ValueError):
            cashflows_for_installment(1200, 12, -0.001)
        with self.assertRaises(ValueError):
            cashflows_for_installment(1200, 12, 0.006, upfront_fee=1200)


class TestMinPayment(unittest.TestCase):
    """最低还款模拟测试。"""

    def test_reference_case(self):
        # 规格基准用例：欠款 10000，月利率 1.5%，每月还 10%
        result = simulate_min_payment(
            balance=10000.0, monthly_rate=0.015, payment_ratio=0.10,
            stop_balance=0.01)
        # 约 153 个月还清
        self.assertAlmostEqual(result["months"], 153, delta=2)
        # 总利息约 1734.10（允许 ±5）
        self.assertAlmostEqual(result["total_interest"], 1734.10, delta=5.0)
        # 最后一笔后余额 <= 0.01
        self.assertLessEqual(result["rows"][-1]["ending_balance"], 0.01)
        # 明细行数与月数一致
        self.assertEqual(len(result["rows"]), result["months"])

    def test_row_fields(self):
        result = simulate_min_payment(1000.0, 0.01, 0.2)
        first = result["rows"][0]
        self.assertEqual(first["month"], 1)
        self.assertAlmostEqual(first["beginning_balance"], 1000.0, places=6)
        self.assertAlmostEqual(first["interest"], 10.0, places=6)
        # 还款 = 计息后余额 * 20% = 1010 * 0.2 = 202
        self.assertAlmostEqual(first["payment"], 202.0, places=6)
        self.assertAlmostEqual(first["ending_balance"], 808.0, places=6)

    def test_ratio_not_above_rate_raises(self):
        # payment_ratio <= monthly_rate 时必须抛 ValueError
        with self.assertRaises(ValueError):
            simulate_min_payment(10000.0, 0.015, 0.015)
        with self.assertRaises(ValueError):
            simulate_min_payment(10000.0, 0.015, 0.01)

    def test_balance_monotonically_decreases(self):
        result = simulate_min_payment(5000.0, 0.02, 0.1)
        last = float("inf")
        for row in result["rows"]:
            self.assertLess(row["ending_balance"], last)
            last = row["ending_balance"]


class TestAnnualizedConsistency(unittest.TestCase):
    """年化口径一致性测试。"""

    def test_effective_function_matches_annualized_irr(self):
        # effective_annual_rate 与 annualized_irr(..., "effective") 一致
        for rate in (0.0, 0.005, 0.0108618536, 0.03):
            self.assertAlmostEqual(
                effective_annual_rate(rate),
                annualized_irr(rate, "effective"),
                places=12,
            )

    def test_effective_slightly_above_nominal(self):
        # 对正的月利率，有效年利率应略高于名义年化
        for rate in (0.001, 0.01, 0.05):
            effective = annualized_irr(rate, "effective")
            nominal = annualized_irr(rate, "nominal")
            self.assertGreater(effective, nominal)

    def test_zero_rate(self):
        self.assertEqual(annualized_irr(0.0, "nominal"), 0.0)
        self.assertEqual(annualized_irr(0.0, "effective"), 0.0)

    def test_invalid_method(self):
        with self.assertRaises(ValueError):
            annualized_irr(0.01, method="unknown")


class TestNPV(unittest.TestCase):
    def test_npv_zero_rate_is_sum(self):
        cashflows = [100.0, -40.0, -40.0, -40.0]
        self.assertAlmostEqual(npv(cashflows, 0.0), -20.0, places=10)

    def test_npv_discounting(self):
        # 100 - 110/1.1 = 0
        self.assertAlmostEqual(npv([100.0, -110.0], 0.1), 0.0, places=10)


if __name__ == "__main__":
    unittest.main()
